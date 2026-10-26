"""Procesa los zips mensuales OCDS: extrae los concursos, los guarda en SQLite
(con índice de texto FTS5) y calcula los embeddings para búsqueda semántica.

Es INCREMENTAL: si ya existe un índice construido con el mismo modelo, reutiliza el
embedding de cada concurso cuyo texto no cambió y solo calcula los nuevos o modificados.

Uso (desde backend/):
    python -m scripts.ingest                 # ventana configurada (18 meses por defecto)
    python -m scripts.ingest --days 90
    python -m scripts.ingest --full          # recalcula todos los embeddings
    python -m scripts.ingest --limit 2000    # prueba rápida
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
import unicodedata
import zipfile
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ijson
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402
from app.vectors import Vectors, quantize  # noqa: E402

CATEGORIES = {"goods": "Bienes", "services": "Servicios", "works": "Obras",
              "consultingServices": "Consultoría"}

COLS = ["nog", "ocid", "title", "status", "status_detail", "date_published", "tender_end",
        "method", "method_detail", "category", "buyer_name", "unit_name", "departamento", "municipio",
        "entity_type", "sector", "n_tenderers", "n_items", "awarded_amount", "currency",
        "suppliers", "supplier_ids", "suppliers_norm", "unspsc", "embed_hash", "detail"]

SCHEMA = """
CREATE TABLE concursos (
  id INTEGER PRIMARY KEY,           -- = fila en embeddings.npy
  nog TEXT UNIQUE, ocid TEXT, title TEXT,
  status TEXT, status_detail TEXT,
  date_published TEXT, tender_end TEXT,
  method TEXT, method_detail TEXT, category TEXT,
  buyer_name TEXT, unit_name TEXT, departamento TEXT, municipio TEXT,
  entity_type TEXT, sector TEXT,
  n_tenderers INTEGER, n_items INTEGER,
  awarded_amount REAL, currency TEXT,
  suppliers TEXT, supplier_ids TEXT, unspsc TEXT,
  suppliers_norm TEXT,              -- proveedores en minúsculas y sin tildes (filtro rápido)
  embed_hash TEXT,                  -- md5 del texto embebido (para reutilizar embeddings)
  detail BLOB                       -- JSON comprimido con zlib
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

INDEXES = """
CREATE INDEX ix_date ON concursos(date_published);
CREATE INDEX ix_status ON concursos(status_detail);
CREATE INDEX ix_cat ON concursos(category);
CREATE INDEX ix_dep ON concursos(departamento);
CREATE INDEX ix_method ON concursos(method_detail);
CREATE INDEX ix_etype ON concursos(entity_type);
CREATE INDEX ix_buyer ON concursos(buyer_name, unit_name);
CREATE INDEX ix_amount ON concursos(awarded_amount);
-- contentless: solo guarda el índice invertido, no una copia de los textos (≈15% menos espacio)
CREATE VIRTUAL TABLE concursos_fts USING fts5(
  title, items, buyer, suppliers, content='', tokenize='unicode61 remove_diacritics 2'
);
"""


def log(msg: str) -> None:
    print(msg, flush=True)


def unaccent(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def text_hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _g(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
        if d is None:
            return default
    return d


def parse_record(rec: dict) -> dict | None:
    cr = rec.get("compiledRelease") or {}
    t = cr.get("tender") or {}
    tid = t.get("id") or ""
    if not tid:
        return None
    nog = tid.replace("GT-NOG-", "")
    parties = cr.get("parties") or []

    # Entidad compradora (la que trae tipo de entidad) y unidad compradora (memberOf)
    entity = next((p for p in parties if "buyer" in (p.get("roles") or [])
                   and _g(p, "details", "entityType", "id", default="0") != "0"), None)
    unit = next((p for p in parties if "buyer" in (p.get("roles") or []) and p.get("memberOf")), None)
    entity = entity or next((p for p in parties if "buyer" in (p.get("roles") or [])), {}) or {}

    items = []
    for it in t.get("items") or []:
        items.append({
            "description": (it.get("description") or "").strip(),
            "quantity": it.get("quantity"),
            "unit": _g(it, "unit", "name"),
            "unspsc": _g(it, "classification", "id"),
        })

    awards = []
    amount, currency = 0.0, None
    sup_names, sup_ids = [], []
    for a in cr.get("awards") or []:
        val = a.get("value") or {}
        sups = a.get("suppliers") or []
        awards.append({
            "id": a.get("id"), "status": a.get("status"), "statusDetails": a.get("statusDetails"),
            "date": a.get("date"), "amount": val.get("amount"), "currency": val.get("currency"),
            "suppliers": [{"id": s.get("id"), "name": s.get("name")} for s in sups],
        })
        if a.get("status") in (None, "active", "pending") and isinstance(val.get("amount"), (int, float)):
            amount += float(val["amount"])
            currency = currency or val.get("currency")
        for s in sups:
            if s.get("name") and s["name"] not in sup_names:
                sup_names.append(s["name"])
                sup_ids.append((s.get("id") or "").replace("GT-NIT-", ""))

    bids = [{"date": b.get("date"), "status": b.get("status"),
             "amount": _g(b, "value", "amount"), "currency": _g(b, "value", "currency"),
             "tenderers": [x.get("name") for x in b.get("tenderers") or []]}
            for b in _g(cr, "bids", "details", default=[]) or []]
    docs = [{"title": d.get("title"), "url": d.get("url"), "type": d.get("documentTypeDetails"),
             "date": d.get("datePublished")} for d in (t.get("documents") or [])[:40]]

    title = (t.get("title") or "").strip()
    buyer_name = _g(cr, "buyer", "name") or entity.get("name") or ""
    category = CATEGORIES.get(t.get("mainProcurementCategory"), t.get("mainProcurementCategory") or "")

    uniq_desc = []
    for it in items:
        d = it["description"]
        if d and d.lower() != title.lower() and d not in uniq_desc:
            uniq_desc.append(d)
    embed_text = f"{title}. Categoría: {category}."
    if uniq_desc:
        embed_text += " Ítems: " + "; ".join(uniq_desc)
    embed_text = embed_text[:1200] + f" Entidad: {buyer_name}."

    return {
        "nog": nog, "ocid": cr.get("ocid"), "title": title,
        "status": t.get("status"), "status_detail": t.get("statusDetails"),
        "date_published": t.get("datePublished") or cr.get("date"),
        "tender_end": _g(t, "tenderPeriod", "endDate"),
        "method": t.get("procurementMethod"), "method_detail": t.get("procurementMethodDetails"),
        "category": category, "buyer_name": buyer_name,
        "unit_name": (unit or {}).get("name"),
        "departamento": _g(entity, "address", "region"),
        "municipio": _g(entity, "address", "locality"),
        "entity_type": _g(entity, "details", "entityType", "description"),
        "sector": _g(entity, "details", "type", "description"),
        "n_tenderers": t.get("numberOfTenderers"),
        "n_items": len(items),
        "awarded_amount": amount if awards else None, "currency": currency or ("GTQ" if awards else None),
        "suppliers": " | ".join(sup_names) or None, "supplier_ids": " ".join(sup_ids) or None,
        "unspsc": " ".join(sorted({i["unspsc"] for i in items if i["unspsc"]})) or None,
        "embed_text": embed_text,
        "detail": json.dumps({"items": items[:200], "awards": awards, "bids": bids[:100], "documents": docs,
                              "tenderers": [x.get("name") for x in t.get("tenderers") or []]},
                             ensure_ascii=False),
        "_items_text": " ; ".join(uniq_desc)[:4000],
    }


def iter_records(zpath: Path):
    with zipfile.ZipFile(zpath) as zf:
        for name in zf.namelist():
            if name.endswith(".json"):
                with zf.open(name) as f:
                    yield from ijson.items(f, "records.item", use_float=True)


def zips_in_window(days: int) -> list[Path]:
    zips = sorted(config.RAW_DIR.glob("*_json.zip"))
    if days <= 0:
        return zips
    start = date.today() - timedelta(days=days)
    out = []
    for z in zips:
        m = re.match(r"(\d{4})-(\d{2})_", z.name)
        if not m or (int(m[1]), int(m[2])) >= (start.year, start.month):
            out.append(z)
    return out


def _to_utc(s: str) -> str:
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat()
    except ValueError:
        return s


def load_previous(model_name: str):
    """Embeddings del índice anterior, indexados por NOG, si se construyó con el mismo modelo."""
    vecs = Vectors.load(config.DATA_DIR, config.EMB_NAME, config.SCALE_NAME, config.LEGACY_EMB_NAME)
    if not (config.DB_PATH.exists() and vecs is not None):
        return {}, None
    try:
        con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
        meta = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM meta")}
        if meta.get("model") != model_name:
            log(f"Índice anterior usa otro modelo ({meta.get('model')}); se recalculan todos los embeddings.")
            return {}, None
        cols = {r[1] for r in con.execute("PRAGMA table_info(concursos)")}
        if "embed_hash" in cols:
            prev = {nog: (i, h) for i, nog, h in con.execute("SELECT id, nog, embed_hash FROM concursos")}
        else:  # índice de una versión anterior: guardaba el texto completo
            prev = {nog: (i, text_hash(t or "")) for i, nog, t in con.execute("SELECT id, nog, embed_text FROM concursos")}
        con.close()
        return prev, vecs
    except Exception as e:  # índice dañado o de otra versión
        log(f"No se pudo leer el índice anterior ({e}); se recalcula todo.")
        return {}, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.WINDOW_DAYS, help="ventana por fecha de publicación (0 = todo)")
    ap.add_argument("--limit", type=int, default=0, help="máximo de concursos (para pruebas)")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--full", action="store_true", help="no reutilizar embeddings anteriores")
    args = ap.parse_args()

    zips = zips_in_window(args.days)
    if not zips:
        sys.exit(f"No hay zips en {config.RAW_DIR}. Corre primero: python -m scripts.download")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat() if args.days > 0 else None

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_db = config.DB_PATH.with_name("guatecompras.tmp.db")
    stg_db = config.DB_PATH.with_name("staging.tmp.db")
    for f in (tmp_db, stg_db):
        f.unlink(missing_ok=True)

    # ---- 1. Leer zips en streaming hacia una tabla de staging (dedupe por NOG) ----
    t0 = time.time()
    con = sqlite3.connect(tmp_db)
    con.executescript(SCHEMA)
    con.execute(f"ATTACH DATABASE '{stg_db}' AS stg")
    con.execute(f"CREATE TABLE stg.s ({', '.join(c + ' ' + ('BLOB' if c == 'detail' else '') for c in COLS)}, "
                "items_text TEXT, embed_text TEXT, PRIMARY KEY (nog))")
    ins = (f"INSERT INTO stg.s ({', '.join(COLS)}, items_text, embed_text) VALUES ({', '.join('?' * (len(COLS) + 2))}) "
           f"ON CONFLICT(nog) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in COLS[1:])}, "
           "items_text=excluded.items_text, embed_text=excluded.embed_text "
           "WHERE excluded.date_published >= s.date_published")
    batch: list[tuple] = []
    for zi, z in enumerate(zips, 1):
        n = 0
        for rec in iter_records(z):
            r = parse_record(rec)
            if not r or not r["date_published"]:
                continue
            if cutoff and _to_utc(r["date_published"]) < cutoff:
                continue
            r["embed_hash"] = text_hash(r["embed_text"])
            r["suppliers_norm"] = unaccent(r["suppliers"]) if r["suppliers"] else None
            r["detail"] = zlib.compress(r["detail"].encode("utf-8"), 6)
            batch.append(tuple(r[c] for c in COLS) + (r["_items_text"], r["embed_text"]))
            n += 1
            if len(batch) >= 5000:
                con.executemany(ins, batch); batch.clear()
        if batch:
            con.executemany(ins, batch); batch.clear()
        con.commit()
        log(f"[leer {zi}/{len(zips)}] {z.name}: {n:,} concursos en la ventana ({time.time() - t0:.0f}s)")

    # ---- 2. Tabla final con ids contiguos ordenados por fecha (id = fila de embeddings) ----
    limit = f"LIMIT {args.limit}" if args.limit else ""
    con.execute(f"INSERT INTO concursos (id, {', '.join(COLS)}) "
                f"SELECT row_number() OVER (ORDER BY date_published DESC) - 1, {', '.join(COLS)} "
                f"FROM stg.s ORDER BY date_published DESC {limit}")
    con.executescript(INDEXES)
    con.execute("INSERT INTO concursos_fts (rowid, title, items, buyer, suppliers) "
                "SELECT c.id, c.title, s.items_text, c.buyer_name || ' ' || COALESCE(c.unit_name, ''), c.suppliers "
                "FROM concursos c JOIN stg.s s ON s.nog = c.nog")
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM concursos").fetchone()[0]
    log(f"Total a indexar: {total:,}")

    # ---- 3. Embeddings: reutilizar los que no cambiaron, calcular el resto ----
    from app.embedder import get_embedder
    emb = get_embedder()
    prev, prev_vecs = ({}, None) if args.full else load_previous(emb.name)
    # Salida en int8 + escala por fila (ver app/vectors.py)
    q8 = np.zeros((total, emb.dim), dtype=np.int8)
    qs = np.ones(total, dtype=np.float32)
    todo_ids, todo_texts, reuse_new, reuse_old = [], [], [], []
    for i, nog, h, txt in con.execute(
            "SELECT c.id, c.nog, c.embed_hash, s.embed_text FROM concursos c JOIN stg.s s ON s.nog = c.nog ORDER BY c.id"):
        p = prev.get(nog)
        if p is not None and p[1] == h and prev_vecs is not None and p[0] < len(prev_vecs) \
                and prev_vecs.shape[1] == emb.dim:
            reuse_new.append(i); reuse_old.append(p[0])
        else:
            todo_ids.append(i); todo_texts.append(txt)
    reused = len(reuse_new)
    for k in range(0, reused, 65536):          # copiar por bloques (sin recuantizar si ya era int8)
        new_i, old_i = np.array(reuse_new[k:k + 65536]), np.array(reuse_old[k:k + 65536])
        if prev_vecs.scale is not None:
            q8[new_i] = prev_vecs.data[old_i]; qs[new_i] = prev_vecs.scale[old_i]
        else:
            q8[new_i], qs[new_i] = quantize(np.asarray(prev_vecs.data[old_i], dtype=np.float32))
    log(f"Embeddings reutilizados: {reused:,} · por calcular: {len(todo_ids):,} con {emb.name}")

    t1, chunk = time.time(), 2048
    for k in range(0, len(todo_ids), chunk):
        part = todo_texts[k:k + chunk]
        ids = todo_ids[k:k + chunk]
        q8[ids], qs[ids] = quantize(emb.encode_passages(part, batch_size=args.batch_size))
        done = min(k + chunk, len(todo_ids))
        rate = done / max(time.time() - t1, 1e-6)
        eta = (len(todo_ids) - done) / rate if rate else 0
        log(f"[embeddings] {done:,}/{len(todo_ids):,} ({100 * done / len(todo_ids):.0f}%) · ~{eta / 60:.0f} min restantes")

    # ---- 4. Metadatos y reemplazo atómico ----
    meta = {"model": emb.name, "dim": int(emb.dim), "rows": total, "emb_dtype": "int8",
            # UTC con "Z": el pipeline corre en GitHub Actions (UTC) y la API calcula la antigüedad
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "days": args.days,
            "reused": reused, "computed": len(todo_ids),
            "sources": [z.name for z in zips]}
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.commit()
    con.execute("DETACH DATABASE stg")
    con.close()
    stg_db.unlink(missing_ok=True)

    del prev_vecs
    tmp_e, tmp_s = config.DATA_DIR / "emb_i8.tmp.npy", config.DATA_DIR / "emb_scale.tmp.npy"
    np.save(tmp_e, q8)
    np.save(tmp_s, qs)
    tmp_e.replace(config.EMB_PATH)
    tmp_s.replace(config.SCALE_PATH)
    (config.DATA_DIR / config.LEGACY_EMB_NAME).unlink(missing_ok=True)   # formato float32 anterior
    tmp_db.replace(config.DB_PATH)
    config.EMB_META_PATH.write_text(json.dumps(meta, indent=2))
    log(f"Listo en {time.time() - t0:.0f}s → {total:,} concursos ({len(todo_ids):,} embeddings nuevos)")


if __name__ == "__main__":
    main()
