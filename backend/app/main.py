"""API FastAPI del buscador de concursos de Guatecompras.

Modos (GC_MODE):
  local  todo en una máquina: índice en data/, botón "Actualizar datos" activo (por defecto)
  api    servicio de solo lectura: descarga el índice publicado (GC_ARTIFACTS_URL) y lo
         actualiza en caliente; sin descargas ni ingesta en el servidor

Autenticación (app/auth.py): todas las rutas de datos exigen un token de Supabase cuando
GC_AUTH_REQUIRED=1 (por defecto en modo api). /api/health queda pública para el monitoreo.

Arranque:  uvicorn app.main:app --app-dir backend --port 8000
"""
from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config
from .artifacts import Syncer
from .embedder import get_embedder
from .search import SearchRequest
from .suppliers import FullIndex, RecommendRequest
from .updater import Updater

if config.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=config.SENTRY_DSN, environment=config.ENVIRONMENT, traces_sample_rate=0.0,
                    send_default_pii=False)

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
    auth.check_config()
    index = FullIndex()
    updater = Updater(on_done=lambda: index.load()) if config.ENABLE_UPDATER else None
    syncer = Syncer(on_new=lambda: index.load())
    syncer.start()                                  # solo actúa si hay GC_ARTIFACTS_URL
    threading.Thread(target=_warm, daemon=True).start()
    yield
    if updater:
        updater.cancel()


_docs = config.DOCS_ENABLED
app = FastAPI(title="Buscador de concursos Guatecompras", version="2.1", lifespan=lifespan,
              docs_url="/docs" if _docs else None, redoc_url="/redoc" if _docs else None,
              openapi_url="/openapi.json" if _docs else None)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "Authorization", "X-Admin-Token"])


# --------------------------------------------------------------------------- límite por usuario / IP
_hits: dict[str, deque] = defaultdict(deque)


def _client_key(request: Request) -> str:
    """Usuario del token si lo hay; si no, la IP real (Cloudflare la pone en CF-Connecting-IP)."""
    sub = auth.unverified_sub(request.headers.get("authorization", ""))
    if sub:
        return "u:" + sub
    ip = request.headers.get("cf-connecting-ip") or \
        (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0]
    return "ip:" + ip.strip()


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    path = request.url.path
    exempt = path in ("/api/health", "/api/update/status") or path.startswith("/api/admin")
    if config.RATE_LIMIT and path.startswith("/api/") and not exempt:
        now, q = time.time(), _hits[_client_key(request)]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= config.RATE_LIMIT:
            return JSONResponse({"detail": "Demasiadas solicitudes; intenta en un minuto"}, status_code=429)
        q.append(now)
    return await call_next(request)


def admin(x_admin_token: str = Header(default=""), authorization: str = Header(default="")) -> None:
    """Protege las operaciones administrativas. Se permiten con:
      - X-Admin-Token = GC_ADMIN_TOKEN (tareas automáticas, p. ej. el pipeline), o
      - un usuario con app_metadata.role = "admin" (login de Supabase).
    En modo local sin token ni login configurados se permiten (la app solo escucha en 127.0.0.1)."""
    if config.ADMIN_TOKEN and x_admin_token:
        if not hmac.compare_digest(x_admin_token, config.ADMIN_TOKEN):
            raise HTTPException(401, "Clave de administrador incorrecta")
        return
    if auth.bearer(authorization) and config.SUPABASE_URL:
        if not auth.is_admin(auth.verify(auth.bearer(authorization))):
            raise HTTPException(403, "Solo administradores")
        return
    if config.ADMIN_TOKEN or config.ADMIN_REQUIRED or config.AUTH_REQUIRED:
        raise HTTPException(401, "Se requiere un administrador")


def _idx() -> FullIndex:
    if not index or not index.ready:
        msg = "Descargando el índice publicado…" if syncer and syncer.state["syncing"] else \
            "Índice no construido. Corre el pipeline (scripts.run_pipeline) o usa Actualizar datos."
        raise HTTPException(503, msg)
    return index


# --------------------------------------------------------------------------- lectura
# Todas las rutas de datos van en este router: exigen sesión (ver app/auth.py).
api = APIRouter(dependencies=[Depends(auth.current_user)])


@app.get("/api/me")
def me(user: dict = Depends(auth.current_user)):
    """Usuario de la sesión actual (para el frontend)."""
    return {"id": user.get("sub"), "email": user.get("email"), "admin": auth.is_admin(user)}


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
        "index_age_hours": _age_hours(meta.get("built_at")),
        "auth": {"required": config.AUTH_REQUIRED},
    }


def _age_hours(built_at: str | None) -> float | None:
    """Horas desde que se construyó el índice. Las fechas sin zona son de índices construidos
    antes de usar UTC (hora de Guatemala)."""
    if not built_at:
        return None
    try:
        t = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone(timedelta(hours=config.LEGACY_TZ_OFFSET_HOURS)))
    return round((datetime.now(timezone.utc) - t).total_seconds() / 3600, 1)


@api.get("/api/facets")
def facets():
    return _idx().facets()


@api.post("/api/search")
def search(req: SearchRequest):
    return _idx().search(req)


@api.get("/api/buyers")
def buyers(q: str = Query("", max_length=100)):
    return _idx().buyers(q)


@api.get("/api/concursos/{nog}")
def concurso(nog: str):
    d = _idx().get(nog)
    if not d:
        raise HTTPException(404, "Concurso no encontrado")
    return d


@api.get("/api/concursos/{nog}/referencias")
def referencias(nog: str, k: int = Query(5, ge=1, le=20)):
    """Concursos pasados y adjudicados más parecidos por descripción y entidad (referencia de precios)."""
    return _idx().awarded_references(nog, k)


@api.get("/api/suppliers")
def suppliers(q: str = Query("", max_length=100)):
    """Autocompletado de proveedores por NIT o nombre."""
    return _idx().supplier_search(q)


@api.get("/api/suppliers/{nit}")
def supplier_profile(nit: str):
    p = _idx().supplier_profile(nit)
    if not p:
        raise HTTPException(404, "No se encontraron adjudicaciones para ese NIT")
    return p


@api.post("/api/recommend")
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


@app.get("/api/admin/sync", dependencies=[Depends(admin)])
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


@api.get("/api/update/status")
def update_status():
    return _updater().status()


@app.post("/api/update/cancel", dependencies=[Depends(admin)])
def update_cancel():
    u = _updater()
    u.cancel()
    return u.status()


app.include_router(api)


# --------------------------------------------------------------------------- frontend (opcional)
# Si existe frontend/dist se sirve aquí (todo en una URL). Si el frontend se publica aparte
# (Cloudflare Pages, GitHub Pages…), basta con no compilarlo junto a la API.
DIST = config.ROOT / "frontend" / "dist"
if DIST.exists() and (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/") or path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(404, "No encontrado")      # no servir la app en rutas de la API
        f = (DIST / path).resolve()
        ok = path and f.is_file() and f.is_relative_to(DIST.resolve())
        return FileResponse(f if ok else DIST / "index.html")
