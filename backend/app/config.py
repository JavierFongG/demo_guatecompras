"""Configuración central. Todo se puede sobrescribir con variables de entorno.

La plataforma se compone de servicios independientes que comparten este módulo:
  - API (solo lectura): búsqueda y recomendaciones.          GC_MODE=api
  - Pipeline: descarga, indexa y publica los artefactos.      scripts/run_pipeline.py
  - Todo en uno (desarrollo / una sola máquina):             GC_MODE=local (por defecto)
"""
import json
import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "si", "sí")


ROOT = Path(__file__).resolve().parents[2]          # carpeta del proyecto
DATA_DIR = Path(os.getenv("GC_DATA_DIR", ROOT / "data"))
RAW_DIR = Path(os.getenv("GC_RAW_DIR", DATA_DIR / "raw"))  # zips mensuales (solo pipeline)
CACHE_DIR = Path(os.getenv("GC_CACHE_DIR", DATA_DIR / "cache"))  # modelos descargados

# Nombres de los artefactos del índice (lo que el pipeline publica y la API consume)
DB_NAME = "guatecompras.db"           # SQLite: metadatos, detalle comprimido, FTS
EMB_NAME = "emb_i8.npy"               # embeddings int8 (N x D)
SCALE_NAME = "emb_scale.npy"          # escala por fila (float32): vector ≈ int8 * escala
LEGACY_EMB_NAME = "embeddings.npy"    # formato anterior (float32), se sigue leyendo
MANIFEST_NAME = "manifest.json"

# ---- Modo de ejecución ----
MODE = os.getenv("GC_MODE", "local")              # "local" | "api"
ADMIN_TOKEN = os.getenv("GC_ADMIN_TOKEN", "")     # protege /api/update, /api/admin/*
# Exigir clave aunque sea modo local (p. ej. la imagen "todo en uno" expuesta a internet)
ADMIN_REQUIRED = _bool("GC_ADMIN_REQUIRED", MODE != "local")
# El botón "Actualizar datos" (descarga + ingesta en la misma máquina) solo en modo local
ENABLE_UPDATER = _bool("GC_ENABLE_UPDATER", MODE == "local")
CORS_ORIGINS = [o.strip() for o in os.getenv(
    "GC_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
RATE_LIMIT = int(os.getenv("GC_RATE_LIMIT", "0" if MODE == "local" else "120"))  # solicitudes/min por IP; 0 = sin límite

# ---- Artefactos remotos (modo api) ----
# URL base donde el pipeline publicó manifest.json, p. ej.:
#   https://huggingface.co/datasets/USUARIO/guatecompras-index/resolve/main/index
#   https://pub-XXXX.r2.dev/index      ·   file:///ruta/a/carpeta
ARTIFACTS_URL = os.getenv("GC_ARTIFACTS_URL", "").rstrip("/")
ARTIFACTS_TOKEN = os.getenv("GC_ARTIFACTS_TOKEN", "")      # opcional (repos privados de HF)
ARTIFACTS_POLL = int(os.getenv("GC_ARTIFACTS_POLL", "1800"))  # segundos entre revisiones; 0 = nunca

# ---- Modelo de embeddings ----
# "onnx" (por defecto, sin PyTorch) · "st" (sentence-transformers, opcional) · "hash" (pruebas)
EMBEDDER = os.getenv("GC_EMBEDDER", "onnx")
ONNX_REPO = os.getenv("GC_ONNX_REPO", "Xenova/multilingual-e5-small")
ONNX_FILE = os.getenv("GC_ONNX_FILE", "onnx/model_quantized.onnx")   # 118 MB, int8
MODEL_DIR = os.getenv("GC_MODEL_DIR", "")      # carpeta con model.onnx + tokenizer.json (sin descarga)
MAX_TOKENS = int(os.getenv("GC_MAX_TOKENS", "256"))
THREADS = int(os.getenv("GC_THREADS", "0"))     # 0 = automático
EMBED_MODEL = os.getenv("GC_EMBED_MODEL", "intfloat/multilingual-e5-small")  # solo para GC_EMBEDDER=st
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
HF_TOKEN = os.getenv("HF_TOKEN", "")

# ---- Datos ----
WINDOW_DAYS = int(os.getenv("GC_WINDOW_DAYS", "548"))    # 548 ≈ 18 meses
PORTAL_URL = os.getenv("GC_PORTAL_URL", os.getenv("GC_API_BASE", "https://ocds.guatecompras.gt"))
API_BASE = PORTAL_URL   # compatibilidad
GUATECOMPRAS_NOG_URL = "https://www.guatecompras.gt/concursos/consultaConcurso.aspx?nog={nog}"


def index_dir() -> Path:
    """Carpeta del índice activo. En modo api con artefactos remotos, la API descarga cada
    versión en data/versions/<v>/ y apunta a la vigente con data/current.json."""
    cur = DATA_DIR / "current.json"
    if cur.exists():
        try:
            d = DATA_DIR / "versions" / json.loads(cur.read_text())["version"]
            if (d / DB_NAME).exists():
                return d
        except (ValueError, KeyError):
            pass
    return DATA_DIR


# Rutas del índice en la carpeta de trabajo del pipeline / modo local
DB_PATH = DATA_DIR / DB_NAME
EMB_PATH = DATA_DIR / EMB_NAME
SCALE_PATH = DATA_DIR / SCALE_NAME
EMB_META_PATH = DATA_DIR / "embeddings.json"
