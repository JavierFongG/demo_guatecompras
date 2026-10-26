"""API FastAPI del buscador de concursos de Guatecompras.

Modos (GC_MODE):
  local  todo en una máquina: índice en data/, botón "Actualizar datos" activo (por defecto)
  api    servicio de solo lectura: descarga el índice publicado (GC_ARTIFACTS_URL) y lo
         actualiza en caliente; sin descargas ni ingesta en el servidor

Arranque:  uvicorn app.main:app --app-dir backend --port 8000
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .artifacts import Syncer
from .embedder import get_embedder
from .search import SearchRequest
from .suppliers import FullIndex, RecommendRequest
from .updater import Updater

index: FullIndex | None = None
updater: Updater | None = None
syncer: Syncer | None = None


def _warm() -> None:
    try:
        get_embedder()          # carga el modelo para que la primera búsqueda sea rápida
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo cargar el modelo de embeddings: {e}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global index, updater, syncer
    index = FullIndex()
    updater = Updater(on_done=lambda: index.load()) if config.ENABLE_UPDATER else None
    syncer = Syncer(on_new=lambda: index.load())
    syncer.start()                                  # solo actúa si hay GC_ARTIFACTS_URL
    threading.Thread(target=_warm, daemon=True).start()
    yield
    if updater:
        updater.cancel()


app = FastAPI(title="Buscador de concursos Guatecompras", version="2.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "X-Admin-Token"])


# --------------------------------------------------------------------------- límite por IP
_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    path = request.url.path
    exempt = path in ("/api/health", "/api/update/status") or path.startswith("/api/admin")
    if config.RATE_LIMIT and path.startswith("/api/") and not exempt:
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0]
        now, q = time.time(), _hits[ip]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= config.RATE_LIMIT:
            return JSONResponse({"detail": "Demasiadas solicitudes; intenta en un minuto"}, status_code=429)
        q.append(now)
    return await call_next(request)


def admin(x_admin_token: str = Header(default="")) -> None:
    """Protege las operaciones administrativas. En modo local sin token configurado se permiten
    (la app solo escucha en 127.0.0.1); en cualquier otro caso exigen GC_ADMIN_TOKEN."""
    if config.ADMIN_TOKEN:
        if x_admin_token != config.ADMIN_TOKEN:
            raise HTTPException(401, "Clave de administrador incorrecta")
    elif config.ADMIN_REQUIRED:
        raise HTTPException(403, "Operación deshabilitada: configura GC_ADMIN_TOKEN en el servidor")


def _idx() -> FullIndex:
    if not index or not index.ready:
        msg = "Descargando el índice publicado…" if syncer and syncer.state["syncing"] else \
            "Índice no construido. Corre el pipeline (scripts.run_pipeline) o usa Actualizar datos."
        raise HTTPException(503, msg)
    return index


# --------------------------------------------------------------------------- lectura
@app.get("/api/health")
def health():
    meta = index.meta if index else {}
    warn = None
    from . import embedder as _e
    if _e._instance and meta.get("model") and _e._instance.name != meta["model"]:
        warn = (f"El índice se construyó con '{meta['model']}' pero la API usa '{_e._instance.name}': "
                "la búsqueda semántica no será correcta. Usa el mismo modelo en ambos.")
    return {
        "ready": bool(index and index.ready), "meta": meta, "mode": config.MODE,
        "updating": bool(updater and updater.state["running"]),
        "syncing": bool(syncer and syncer.state["syncing"]),
        "features": {"update": bool(updater), "sync": bool(config.ARTIFACTS_URL),
                     "admin_token": bool(config.ADMIN_TOKEN)},
        "window_days": config.WINDOW_DAYS, "warning": warn,
    }


@app.get("/api/facets")
def facets():
    return _idx().facets()


@app.post("/api/search")
def search(req: SearchRequest):
    return _idx().search(req)


@app.get("/api/buyers")
def buyers(q: str = Query("", max_length=100)):
    return _idx().buyers(q)


@app.get("/api/concursos/{nog}")
def concurso(nog: str):
    d = _idx().get(nog)
    if not d:
        raise HTTPException(404, "Concurso no encontrado")
    return d


@app.get("/api/concursos/{nog}/referencias")
def referencias(nog: str, k: int = Query(5, ge=1, le=20)):
    """Concursos pasados y adjudicados más parecidos por descripción y entidad (referencia de precios)."""
    return _idx().awarded_references(nog, k)


@app.get("/api/suppliers")
def suppliers(q: str = Query("", max_length=100)):
    """Autocompletado de proveedores por NIT o nombre."""
    return _idx().supplier_search(q)


@app.get("/api/suppliers/{nit}")
def supplier_profile(nit: str):
    p = _idx().supplier_profile(nit)
    if not p:
        raise HTTPException(404, "No se encontraron adjudicaciones para ese NIT")
    return p


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    """Concursos relevantes para un proveedor según su historial de adjudicaciones."""
    return _idx().recommend(req)


# --------------------------------------------------------------------------- administración
@app.post("/api/reload", dependencies=[Depends(admin)])
def reload():
    """Recarga el índice desde disco (tras una ingesta local)."""
    if index:
        index.load()
    return health()


@app.post("/api/admin/sync", dependencies=[Depends(admin)])
def admin_sync():
    """Fuerza revisar si hay una versión nueva del índice publicado (modo api)."""
    if not config.ARTIFACTS_URL:
        raise HTTPException(400, "GC_ARTIFACTS_URL no está configurado")
    threading.Thread(target=syncer.sync, daemon=True).start()
    return syncer.state


@app.get("/api/admin/sync")
def admin_sync_status():
    return syncer.state if syncer else {}


def _updater() -> Updater:
    if not updater:
        raise HTTPException(404, "La actualización desde la interfaz está deshabilitada en este servidor; "
                                 "los datos se actualizan con el pipeline programado")
    return updater


@app.post("/api/update", dependencies=[Depends(admin)])
def update_start():
    """Descarga los meses que cambiaron y reconstruye el índice en esta máquina (modo local)."""
    u = _updater()
    if not u.start():
        raise HTTPException(409, "Ya hay una actualización en curso")
    return u.status()


@app.get("/api/update/status")
def update_status():
    return _updater().status()


@app.post("/api/update/cancel", dependencies=[Depends(admin)])
def update_cancel():
    u = _updater()
    u.cancel()
    return u.status()


# --------------------------------------------------------------------------- frontend (opcional)
# Si existe frontend/dist se sirve aquí (todo en una URL). Si el frontend se publica aparte
# (Cloudflare Pages, GitHub Pages…), basta con no compilarlo junto a la API.
DIST = config.ROOT / "frontend" / "dist"
if DIST.exists() and (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = (DIST / path).resolve()
        ok = path and f.is_file() and f.is_relative_to(DIST.resolve())
        return FileResponse(f if ok else DIST / "index.html")
