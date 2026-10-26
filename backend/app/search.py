"""Índice en memoria + búsqueda semántica/híbrida con filtros SQL."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
import zlib
from typing import List, Literal, Optional

import numpy as np
from pydantic import BaseModel, Field

from . import config
from .embedder import get_embedder
from .vectors import Vectors

MAX_RANKED = 500          # máximo de resultados rankeados por relevancia
RRF_K = 60                # constante de Reciprocal Rank Fusion (modo híbrido)

# Referencia de precios: adjudicaciones pasadas más parecidas a un concurso.
# La puntuación es la similitud coseno de la descripción (embedding) más un bono si la compra
# la hizo la misma entidad (y otro adicional si fue la misma unidad compradora). Los cosenos de
# e5 se concentran entre ~0.80 y 0.95, por eso los bonos son pequeños.
REF_ENTITY_BONUS = 0.03
REF_UNIT_BONUS = 0.01

LIST_COLS = ("id, nog, ocid, title, status, status_detail, date_published, tender_end, category, "
             "method_detail, buyer_name, unit_name, departamento, municipio, entity_type, "
             "awarded_amount, currency, suppliers, n_tenderers, n_items")


STOPWORDS = {"para", "por", "con", "los", "las", "del", "que", "una", "uno", "unos", "unas", "sus",
              "compra", "adquisicion", "servicio", "servicios", "contratacion"}


def _stem(w: str) -> str:
    """Stemming mínimo en español para que el prefijo FTS cubra singular/plural."""
    if len(w) > 5 and w.endswith("es") and w[-3] not in "aeiou":
        return w[:-2]          # hospitales -> hospital
    if len(w) > 4 and w.endswith("s"):
        return w[:-1]          # computadoras -> computadora
    return w


def unaccent(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


class UnitRef(BaseModel):
    """Unidad compradora. El nombre de unidad se repite entre entidades
    (p. ej. 'DEPARTAMENTO DE COMPRAS'), por eso se identifica junto con su entidad."""
    entity: str
    unit: str


class SearchRequest(BaseModel):
    q: Optional[str] = None
    mode: Literal["semantic", "hybrid", "keyword"] = "hybrid"
    date_from: Optional[str] = None          # YYYY-MM-DD (fecha de publicación)
    date_to: Optional[str] = None
    status: List[str] = Field(default_factory=list)          # estado (statusDetails)
    category: List[str] = Field(default_factory=list)        # Bienes / Servicios / Obras
    method: List[str] = Field(default_factory=list)          # modalidad
    departamento: List[str] = Field(default_factory=list)
    entity_type: List[str] = Field(default_factory=list)
    buyer: Optional[str] = None              # texto contenido en entidad o unidad compradora
    supplier: Optional[str] = None           # nombre o NIT del adjudicado
    amount_min: Optional[float] = None       # monto adjudicado (GTQ)
    amount_max: Optional[float] = None
    only_awarded: bool = False
    open_only: bool = False               # recepción de ofertas aún abierta
    # Modo "excluir": valores a descartar (todo lo demás se incluye)
    status_not: List[str] = Field(default_factory=list)
    category_not: List[str] = Field(default_factory=list)
    method_not: List[str] = Field(default_factory=list)
    departamento_not: List[str] = Field(default_factory=list)
    entity_type_not: List[str] = Field(default_factory=list)
    # Entidades completas (todas sus unidades) y unidades compradoras específicas.
    # Incluir: entidad elegida O unidad elegida. Excluir: ninguna de las elegidas.
    buyers: List[str] = Field(default_factory=list)
    buyers_not: List[str] = Field(default_factory=list)
    units: List[UnitRef] = Field(default_factory=list)
    units_not: List[UnitRef] = Field(default_factory=list)
    sort: Literal["relevance", "date_desc", "date_asc", "amount_desc", "amount_asc"] = "relevance"
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class Index:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.emb: Vectors | None = None
        self.folder = config.index_dir()
        self.meta: dict = {}
        self.facets_cache: dict = {}
        self.has_suppliers_norm = False
        self.entities: list = []    # [nombre, nombre_sin_tildes, concursos, n_unidades]
        self.units: list = []       # (unidad, entidad, concursos, unidad_sin_tildes, entidad_sin_tildes)
        self.awarded_mask: np.ndarray | None = None   # fila -> tiene monto adjudicado > 0
        self.pub_day: np.ndarray | None = None        # fila -> fecha de publicación AAAAMMDD
        self.load()

    # ---------- carga ----------
    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.folder / config.DB_NAME}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.create_function("unaccent", 1, unaccent, deterministic=True)
        return con

    def load(self) -> None:
        """Carga (o recarga tras una actualización) el índice. Todo se prepara aparte y se
        reemplaza de una vez para que las búsquedas en curso no vean un estado mezclado."""
        folder = config.index_dir()
        emb = Vectors.load(folder, config.EMB_NAME, config.SCALE_NAME, config.LEGACY_EMB_NAME) \
            if (folder / config.DB_NAME).exists() else None
        if emb is None:
            self.emb, self.meta = None, {}
            return
        self.folder = folder
        con = self.connect()
        try:
            meta = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM meta")}
            has_norm = any(c[1] == "suppliers_norm" for c in con.execute("PRAGMA table_info(concursos)"))
            ents: dict[str, list] = {}
            units = []
            for b, u, c in con.execute(
                    "SELECT buyer_name, unit_name, COUNT(*) FROM concursos GROUP BY buyer_name, unit_name"):
                e = ents.setdefault(b, [b, unaccent(b), 0, 0])
                e[2] += c
                if u:
                    e[3] += 1
                    units.append((u, b, c, unaccent(u), unaccent(b)))
            facets = self._compute_facets(con, meta)
            n = len(emb)
            awarded_mask = np.zeros(n, dtype=bool)
            pub_day = np.zeros(n, dtype=np.int32)
            for i, day, aw in con.execute(
                    "SELECT id, CAST(replace(substr(date_published, 1, 10), '-', '') AS INTEGER), "
                    "COALESCE(awarded_amount, 0) > 0 FROM concursos"):
                if i < n:
                    pub_day[i] = day or 0
                    awarded_mask[i] = bool(aw)
        finally:
            con.close()
        with self.lock:
            self.emb, self.meta, self.facets_cache = emb, meta, facets
            self.has_suppliers_norm = has_norm
            self.entities = sorted(ents.values(), key=lambda e: -e[2])
            self.units = sorted(units, key=lambda u: -u[2])
            self.awarded_mask, self.pub_day = awarded_mask, pub_day
        # Precalienta la caché de páginas para que la primera búsqueda no sea lenta
        if len(emb):
            _ = emb.dot(np.zeros(emb.shape[1], dtype=np.float32))

    @property
    def ready(self) -> bool:
        return self.emb is not None

    # ---------- filtros ----------
    def _where(self, r: SearchRequest) -> tuple[str, list]:
        w, p = [], []

        def in_list(col: str, vals: list[str]):
            if vals:
                w.append(f"{col} IN ({','.join('?' * len(vals))})")
                p.extend(vals)

        def not_in_list(col: str, vals: list[str]):
            if vals:
                w.append(f"({col} IS NULL OR {col} NOT IN ({','.join('?' * len(vals))}))")
                p.extend(vals)

        not_in_list("status_detail", r.status_not)
        not_in_list("category", r.category_not)
        not_in_list("method_detail", r.method_not)
        not_in_list("departamento", r.departamento_not)
        not_in_list("entity_type", r.entity_type_not)

        def unit_pairs(units: list[UnitRef]) -> str:
            for u in units:
                p.extend([u.entity, u.unit])
            return " OR ".join(["(buyer_name = ? AND COALESCE(unit_name, '') = ?)"] * len(units))

        inc = []
        if r.buyers:
            inc.append(f"buyer_name IN ({','.join('?' * len(r.buyers))})")
            p.extend(r.buyers)
        if r.units:
            inc.append(unit_pairs(r.units))
        if inc:
            w.append("(" + " OR ".join(inc) + ")")
        not_in_list("buyer_name", r.buyers_not)
        if r.units_not:
            w.append(f"NOT ({unit_pairs(r.units_not)})")

        if r.date_from:
            w.append("date_published >= ?"); p.append(r.date_from)
        if r.date_to:
            w.append("date_published < date(?, '+1 day')"); p.append(r.date_to)
        in_list("status_detail", r.status)
        in_list("category", r.category)
        in_list("method_detail", r.method)
        in_list("departamento", r.departamento)
        in_list("entity_type", r.entity_type)
        if r.buyer:
            w.append("(unaccent(buyer_name) LIKE ? OR unaccent(unit_name) LIKE ?)")
            p += [f"%{unaccent(r.buyer)}%"] * 2
        if r.supplier:
            col = "suppliers_norm" if self.has_suppliers_norm else "unaccent(suppliers)"
            w.append(f"({col} LIKE ? OR supplier_ids LIKE ?)")
            p += [f"%{unaccent(r.supplier)}%", f"%{r.supplier.strip()}%"]
        if r.amount_min is not None:
            w.append("awarded_amount >= ?"); p.append(r.amount_min)
        if r.amount_max is not None:
            w.append("awarded_amount <= ?"); p.append(r.amount_max)
        if r.only_awarded:
            w.append("awarded_amount IS NOT NULL")
        if r.open_only:
            # Vigente = aún recibe ofertas. En los datos de Guatecompras los vigentes casi nunca
            # traen fecha de cierre; si la traen, debe ser futura (hora de Guatemala, UTC-6).
            w.append("status_detail = 'Vigente' AND (tender_end IS NULL OR "
                     "tender_end >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-6 hours'))")
        return (" WHERE " + " AND ".join(w)) if w else "", p

    @staticmethod
    def _fts_query(q: str, op: str) -> str | None:
        words = [x for x in re.findall(r"\w+", unaccent(q)) if len(x) > 2 and x not in STOPWORDS]
        if not words:
            return None
        return f" {op} ".join(f'"{_stem(x)}"*' for x in words[:12])

    # ---------- búsqueda ----------
    def search(self, r: SearchRequest) -> dict:
        con = self.connect()
        try:
            where, params = self._where(r)
            q = (r.q or "").strip()
            if not q:
                return self._browse(con, r, where, params)

            emb = self.emb
            n = len(emb)
            mask = None                       # None = sin filtros (todos permitidos)
            if where:
                ids = np.fromiter((row[0] for row in con.execute(f"SELECT id FROM concursos{where}", params)),
                                  dtype=np.int64)
                if ids.size == 0:
                    return {"total": 0, "results": [], "page": r.page, "page_size": r.page_size}
                mask = np.zeros(n, dtype=bool)
                mask[ids[ids < n]] = True

            ranked: list[tuple[int, float]] = []
            sem_scores: dict[int, float] = {}
            if r.mode in ("semantic", "hybrid"):
                qv = get_embedder().encode_query(q)
                scores = emb.dot(qv)          # producto contra toda la matriz (int8 por bloques)
                if mask is not None:
                    scores = np.where(mask, scores, -np.inf)
                k = min(MAX_RANKED, n)
                top = np.argpartition(-scores, k - 1)[:k]
                top = top[np.argsort(-scores[top])]
                sem = [(int(i), float(scores[i])) for i in top if np.isfinite(scores[i])]
                sem_scores = dict(sem)
                ranked = sem

            if r.mode in ("keyword", "hybrid"):
                fq = self._fts_query(q, "AND" if r.mode == "keyword" else "OR")
                kw: list[int] = []
                if fq:
                    for row in con.execute(
                        "SELECT rowid FROM concursos_fts WHERE concursos_fts MATCH ? ORDER BY rank LIMIT 20000", (fq,)
                    ):
                        if mask is None or (row[0] < n and mask[row[0]]):
                            kw.append(row[0])
                            if len(kw) >= MAX_RANKED:
                                break
                if r.mode == "keyword":
                    ranked = [(i, 1.0 / (RRF_K + n)) for n, i in enumerate(kw)]
                else:
                    fused: dict[int, float] = {}
                    for n, (i, _) in enumerate(ranked):
                        fused[i] = fused.get(i, 0) + 1.0 / (RRF_K + n)
                    for n, i in enumerate(kw):
                        fused[i] = fused.get(i, 0) + 1.0 / (RRF_K + n)
                    ranked = sorted(fused.items(), key=lambda x: -x[1])[:MAX_RANKED]

            rows = self._rows(con, [i for i, _ in ranked])
            for row, (i, s) in zip(rows, ranked):
                row["score"] = round(s, 5)
                row["similarity"] = round(sem_scores[i], 4) if i in sem_scores else None
            rows = self._sort(rows, r.sort)
            start = (r.page - 1) * r.page_size
            return {"total": len(rows), "results": rows[start:start + r.page_size],
                    "page": r.page, "page_size": r.page_size, "capped": len(rows) >= MAX_RANKED}
        finally:
            con.close()

    def _browse(self, con, r: SearchRequest, where: str, params: list) -> dict:
        order = {
            "date_asc": "date_published ASC",
            "amount_desc": "awarded_amount IS NULL, awarded_amount DESC",
            "amount_asc": "awarded_amount IS NULL, awarded_amount ASC",
        }.get(r.sort, "date_published DESC")
        total = con.execute(f"SELECT COUNT(*) FROM concursos{where}", params).fetchone()[0]
        cur = con.execute(f"SELECT {LIST_COLS} FROM concursos{where} ORDER BY {order} LIMIT ? OFFSET ?",
                          params + [r.page_size, (r.page - 1) * r.page_size])
        return {"total": total, "results": [self._fmt(dict(x)) for x in cur],
                "page": r.page, "page_size": r.page_size}

    @staticmethod
    def _sort(rows: list[dict], sort: str) -> list[dict]:
        if sort == "date_desc":
            return sorted(rows, key=lambda x: x["date_published"] or "", reverse=True)
        if sort == "date_asc":
            return sorted(rows, key=lambda x: x["date_published"] or "")
        if sort == "amount_desc":
            return sorted(rows, key=lambda x: -(x["awarded_amount"] or -1))
        if sort == "amount_asc":
            return sorted(rows, key=lambda x: (x["awarded_amount"] is None, x["awarded_amount"] or 0))
        return rows

    def _rows(self, con, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        out: dict[int, dict] = {}
        for chunk in range(0, len(ids), 900):
            part = ids[chunk:chunk + 900]
            for x in con.execute(f"SELECT {LIST_COLS} FROM concursos WHERE id IN ({','.join('?' * len(part))})", part):
                out[x["id"]] = self._fmt(dict(x))
        return [out[i] for i in ids if i in out]

    @staticmethod
    def _fmt(d: dict) -> dict:
        d["url"] = config.GUATECOMPRAS_NOG_URL.format(nog=d["nog"])
        return d

    # ---------- detalle ----------
    def get(self, nog: str) -> dict | None:
        con = self.connect()
        try:
            x = con.execute("SELECT * FROM concursos WHERE nog = ?", (nog,)).fetchone()
            if not x:
                return None
            d = self._fmt(dict(x))
            raw = d.get("detail")
            if isinstance(raw, bytes):               # índice nuevo: JSON comprimido con zlib
                raw = zlib.decompress(raw).decode("utf-8")
            d["detail"] = json.loads(raw or "{}")
            for k in ("embed_text", "embed_hash"):
                d.pop(k, None)
            return d
        finally:
            con.close()

    def awarded_references(self, nog: str, k: int = 5) -> dict:
        """Los k concursos ANTERIORES y ADJUDICADOS más parecidos por descripción y entidad,
        como referencia de los precios pagados en compras similares."""
        con = self.connect()
        try:
            x = con.execute("SELECT id, buyer_name, unit_name, date_published FROM concursos WHERE nog = ?",
                            (nog,)).fetchone()
            empty = {"results": [], "stats": None, "weights": {"entity": REF_ENTITY_BONUS, "unit": REF_UNIT_BONUS}}
            emb, mask, pub_day = self.emb, self.awarded_mask, self.pub_day
            if not x or mask is None or int(x["id"]) >= len(emb):
                return empty
            i0, n = int(x["id"]), len(emb)

            # Candidatos: adjudicados (monto > 0) y publicados antes que este concurso
            ok = mask.copy()
            day = int((x["date_published"] or "")[:10].replace("-", "") or 0)
            if day:
                ok &= pub_day < day
            ok[i0] = False
            if not ok.any():
                return empty

            desc = emb.dot(emb[i0])                     # similitud de descripción
            bonus = np.zeros(n, dtype=np.float32)
            if x["buyer_name"]:
                same = [(j, u) for j, u in con.execute(
                    "SELECT id, unit_name FROM concursos WHERE buyer_name = ?", (x["buyer_name"],)) if j < n]
                if same:
                    ids = np.fromiter((j for j, _ in same), dtype=np.int64)
                    bonus[ids] = REF_ENTITY_BONUS
                    if x["unit_name"]:
                        uids = np.fromiter((j for j, u in same if u == x["unit_name"]), dtype=np.int64)
                        bonus[uids] += REF_UNIT_BONUS
            score = np.where(ok, desc + bonus, -np.inf)
            kk = min(k, int(ok.sum()))
            top = np.argpartition(-score, kk - 1)[:kk]
            top = [int(i) for i in top[np.argsort(-score[top])] if np.isfinite(score[i])]

            out: dict[int, dict] = {}
            for r in con.execute(f"SELECT {LIST_COLS}, detail FROM concursos WHERE id IN ({','.join('?' * len(top))})", top):
                d = self._fmt(dict(r))
                raw = d.pop("detail")
                if isinstance(raw, bytes):
                    raw = zlib.decompress(raw).decode("utf-8")
                det = json.loads(raw or "{}")
                items = det.get("items") or []
                active = [a for a in det.get("awards") or [] if a.get("status") in (None, "active", "pending")]
                dates = [a["date"] for a in active if a.get("date")]
                d["award_date"] = max(dates) if dates else None
                d["items"] = [{"description": it.get("description"), "quantity": it.get("quantity"),
                               "unit": it.get("unit")} for it in items[:3]]
                # Precio unitario aproximado: solo tiene sentido con un único ítem y cantidad > 1
                q = items[0].get("quantity") if len(items) == 1 else None
                d["unit_price"] = round(d["awarded_amount"] / q, 2) \
                    if isinstance(q, (int, float)) and q > 1 and d["awarded_amount"] else None
                d["unit_label"] = items[0].get("unit") if d["unit_price"] else None
                d["similarity"] = round(float(desc[d["id"]]), 4)
                d["score"] = round(float(score[d["id"]]), 4)
                d["same_entity"] = bool(bonus[d["id"]] >= REF_ENTITY_BONUS)
                d["same_unit"] = bool(bonus[d["id"]] > REF_ENTITY_BONUS)
                out[d["id"]] = d
            rows = [out[i] for i in top if i in out]
            amounts = sorted(r["awarded_amount"] for r in rows if r["awarded_amount"])
            stats = {"count": len(amounts), "min": amounts[0], "max": amounts[-1],
                     "median": float(np.median(amounts)), "mean": round(float(np.mean(amounts)), 2)} if amounts else None
            return {"results": rows, "stats": stats,
                    "weights": {"entity": REF_ENTITY_BONUS, "unit": REF_UNIT_BONUS}}
        finally:
            con.close()

    # ---------- facetas (se calculan una vez al cargar) ----------
    @staticmethod
    def _compute_facets(con, meta: dict) -> dict:
        def counts(col: str):
            return [{"value": v, "count": c} for v, c in con.execute(
                f"SELECT {col}, COUNT(*) c FROM concursos WHERE {col} IS NOT NULL AND {col} != '' "
                f"GROUP BY {col} ORDER BY c DESC")]
        dmin, dmax, total, amin, amax = con.execute(
            "SELECT MIN(date_published), MAX(date_published), COUNT(*), MIN(awarded_amount), "
            "MAX(awarded_amount) FROM concursos").fetchone()
        return {
            "total": total, "date_min": (dmin or "")[:10], "date_max": (dmax or "")[:10],
            "amount_min": amin, "amount_max": amax,
            "status": counts("status_detail"), "category": counts("category"),
            "method": counts("method_detail"), "departamento": counts("departamento"),
            "entity_type": counts("entity_type"), "meta": meta,
        }

    def facets(self) -> dict:
        return self.facets_cache

    def buyers(self, q: str, limit: int = 8) -> dict:
        """Autocompletado en memoria: entidades que coinciden y unidades compradoras que
        coinciden por su nombre o por el de su entidad (al escribir 'igss' salen sus hospitales)."""
        pat = unaccent(q).strip()
        if not pat:
            return {"entities": [], "units": []}
        entities = [{"value": e[0], "count": e[2], "units": e[3]}
                    for e in self.entities if pat in e[1]][:limit]
        by_unit = [u for u in self.units if pat in u[3]]
        by_entity = [u for u in self.units if pat not in u[3] and pat in u[4]]
        units = [{"entity": u[1], "unit": u[0], "count": u[2]} for u in (by_unit + by_entity)[: limit * 2]]
        return {"entities": entities, "units": units}
