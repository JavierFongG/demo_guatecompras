"""Oportunidades por proveedor.

Dado un NIT (o un proveedor elegido por nombre):
1. Reúne su historial: todos los concursos que se le adjudicaron.
2. Construye un perfil semántico con los embeddings de ese historial. Como un proveedor puede
   vender cosas muy distintas (p. ej. medicamentos Y equipo médico), no se usa un solo promedio
   sino varios centroides (k-means esférico): cada línea de negocio queda representada.
3. Puntúa cada concurso candidato por su similitud con el centroide más cercano y lo explica
   con la adjudicación pasada más parecida.
"""
from __future__ import annotations

import json
import zlib
from collections import Counter
from typing import Optional

import numpy as np

from .search import LIST_COLS, MAX_RANKED, Index, SearchRequest, unaccent


class RecommendRequest(SearchRequest):
    nit: str
    open_only: bool = True               # por defecto: solo concursos que aún reciben ofertas
    include_history: bool = False        # incluir concursos que el proveedor ya ganó
    q: Optional[str] = None              # texto opcional para afinar ("solo lo de laboratorio")


def build_supplier_index(con) -> dict:
    """nit -> [nombre, concursos adjudicados, nombre_normalizado]"""
    idx: dict[str, list] = {}
    for names, ids in con.execute(
            "SELECT suppliers, supplier_ids FROM concursos WHERE supplier_ids IS NOT NULL"):
        ns = (names or "").split(" | ")
        for i, nit in enumerate(ids.split()):
            e = idx.get(nit)
            if e is None:
                name = ns[i] if i < len(ns) else nit
                idx[nit] = [name, 1, unaccent(name)]
            else:
                e[1] += 1
    return idx


def _kmeans(H: np.ndarray, k: int, iters: int = 10) -> np.ndarray:
    """k-means esférico sobre vectores normalizados; devuelve centroides normalizados."""
    if len(H) <= k:
        return H.copy()
    rng = np.random.default_rng(0)
    C = H[rng.choice(len(H), k, replace=False)].copy()
    for _ in range(iters):
        assign = np.argmax(H @ C.T, axis=1)
        for j in range(k):
            m = H[assign == j]
            if len(m):
                c = m.sum(0)
                C[j] = c / (np.linalg.norm(c) or 1)
    return C


class SupplierMixin:
    # Atributos provistos por Index: emb, suppliers, connect(), _where(), _rows(), _fmt()

    # ---------- búsqueda de proveedor ----------
    def supplier_search(self, q: str, limit: int = 12) -> list[dict]:
        q = q.strip()
        if not q:
            return []
        digits = q.replace("-", "").upper()
        if digits[:-1].isdigit() and len(digits) >= 3:      # parece un NIT (puede terminar en K)
            hits = [(nit, e) for nit, e in self.suppliers.items() if nit.upper().startswith(digits)]
        else:
            pat = unaccent(q)
            hits = [(nit, e) for nit, e in self.suppliers.items() if pat in e[2]]
        hits.sort(key=lambda x: -x[1][1])
        return [{"nit": nit, "name": e[0], "awards": e[1]} for nit, e in hits[:limit]]

    # ---------- historial / perfil ----------
    def _history_rows(self, con, nit: str) -> list[dict]:
        rows = []
        for x in con.execute(
                f"SELECT {LIST_COLS}, unspsc, detail FROM concursos "
                "WHERE (' ' || supplier_ids || ' ') LIKE ? ORDER BY date_published DESC", (f"% {nit} %",)):
            d = dict(x)
            raw = d.pop("detail")
            if isinstance(raw, bytes):
                raw = zlib.decompress(raw).decode("utf-8")
            det = json.loads(raw or "{}")
            # monto adjudicado específicamente a este proveedor (un concurso puede tener varios)
            mine = 0.0
            for a in det.get("awards", []):
                if any((s.get("id") or "").replace("GT-NIT-", "") == nit for s in a.get("suppliers", [])) \
                        and isinstance(a.get("amount"), (int, float)) and a.get("status") in (None, "active", "pending"):
                    mine += a["amount"]
            d["supplier_amount"] = mine or None
            rows.append(self._fmt(d))
        return rows

    def supplier_profile(self, nit: str) -> Optional[dict]:
        e = self.suppliers.get(nit)
        if not e:
            return None
        con = self.connect()
        try:
            hist = self._history_rows(con, nit)
        finally:
            con.close()
        top = lambda key, n=6: [{"value": v, "count": c} for v, c in Counter(  # noqa: E731
            h[key] for h in hist if h.get(key)).most_common(n)]
        dates = [h["date_published"] for h in hist if h.get("date_published")]
        return {
            "nit": nit, "name": e[0], "awards": len(hist),
            "total_amount": round(sum(h["supplier_amount"] or 0 for h in hist), 2),
            "first_date": min(dates) if dates else None, "last_date": max(dates) if dates else None,
            "top_buyers": top("buyer_name"), "top_categories": top("category", 4),
            "top_departamentos": top("departamento"), "top_methods": top("method_detail", 4),
            "history": [{k: h[k] for k in ("nog", "title", "date_published", "buyer_name", "unit_name",
                                            "category", "supplier_amount", "status_detail", "url")}
                        for h in hist[:300]],
        }

    # ---------- recomendaciones ----------
    def recommend(self, r: RecommendRequest) -> dict:
        nit = r.nit.strip()
        if nit not in self.suppliers:
            return {"total": 0, "results": [], "page": r.page, "page_size": r.page_size, "error": "NIT sin adjudicaciones"}
        con = self.connect()
        try:
            emb = self.emb
            n = len(emb)
            hist_ids = np.fromiter((row[0] for row in con.execute(
                "SELECT id FROM concursos WHERE (' ' || supplier_ids || ' ') LIKE ?", (f"% {nit} %",))), dtype=np.int64)
            hist_ids = hist_ids[hist_ids < n]
            if hist_ids.size == 0:
                return {"total": 0, "results": [], "page": r.page, "page_size": r.page_size}
            H = emb[hist_ids]
            k = int(min(24, max(1, round(len(H) ** 0.5))))
            C = _kmeans(H, k)

            # similitud de cada concurso con la línea de negocio (centroide) más cercana
            scores = emb.dot(C.T).max(axis=1)
            if r.q and r.q.strip():
                from .embedder import get_embedder
                qs = emb.dot(get_embedder().encode_query(r.q.strip()))
                scores = 0.6 * scores + 0.4 * qs

            where, params = self._where(r)
            if where:
                ok = np.zeros(n, dtype=bool)
                ids = np.fromiter((row[0] for row in con.execute(f"SELECT id FROM concursos{where}", params)),
                                  dtype=np.int64)
                ok[ids[ids < n]] = True
                scores = np.where(ok, scores, -np.inf)
            if not r.include_history:
                scores[hist_ids] = -np.inf

            kk = min(MAX_RANKED, n)
            top = np.argpartition(-scores, kk - 1)[:kk]
            top = top[np.argsort(-scores[top])]
            top = [int(i) for i in top if np.isfinite(scores[i])]

            rows = self._sort(self._rows(con, top), r.sort)
            start = (r.page - 1) * r.page_size
            page = rows[start:start + r.page_size]

            # Explicación: la adjudicación pasada más parecida a cada resultado de la página
            if page:
                P = emb[np.array([x["id"] for x in page])]
                sims = P @ H.T
                best = sims.argmax(axis=1)
                ref_ids = [int(hist_ids[b]) for b in best]
                refs = {x["id"]: x for x in self._rows(con, list(dict.fromkeys(ref_ids)))}
                for row, b, rid in zip(page, best, ref_ids):
                    row["similarity"] = round(float(scores[row["id"]]), 4)
                    ref = refs.get(rid)
                    if ref:
                        row["because"] = {"nog": ref["nog"], "title": ref["title"], "buyer_name": ref["buyer_name"],
                                          "date_published": ref["date_published"],
                                          "similarity": round(float(sims[page.index(row), b]), 4)}
            return {"total": len(rows), "results": page, "page": r.page, "page_size": r.page_size,
                    "capped": len(rows) >= MAX_RANKED, "history_size": int(hist_ids.size), "profiles": k}
        finally:
            con.close()


class FullIndex(SupplierMixin, Index):
    """Índice de búsqueda + funcionalidades por proveedor."""

    def __init__(self) -> None:
        self.suppliers: dict = {}
        super().__init__()

    def load(self) -> None:
        super().load()
        if self.emb is None:
            self.suppliers = {}
            return
        con = self.connect()
        try:
            self.suppliers = build_supplier_index(con)
        finally:
            con.close()
