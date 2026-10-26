"""Artefactos versionados del índice: lo que el pipeline publica y la API consume.

Estructura publicada (en cualquier destino):
    <base>/manifest.json                 ← versión vigente (se escribe al final)
    <base>/<versión>/guatecompras.db.gz  ← SQLite comprimido
    <base>/<versión>/emb_i8.npy          ← embeddings int8
    <base>/<versión>/emb_scale.npy

Destinos para publicar (scripts/publish.py --to …):
    dir:/ruta/carpeta                       carpeta local o montada (también sirve con GCS FUSE)
    s3://bucket/prefijo                     S3 o compatibles: Cloudflare R2, Backblaze B2, MinIO, GCS
                                            (S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    hf://datasets/usuario/repo[/prefijo]    Hugging Face Datasets (HF_TOKEN)

Lectura (API y pipeline): GC_ARTIFACTS_URL = URL pública del <base> (https://… o file://…).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import config

GZ_FILES = {config.DB_NAME}                       # se publican comprimidos
INDEX_FILES = [config.DB_NAME, config.EMB_NAME, config.SCALE_NAME]


def log(msg: str) -> None:
    print(f"[artefactos] {msg}", flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- empaquetar
def package(folder: Path, out: Path) -> dict:
    """Prepara <out>/<versión>/… y <out>/manifest.json a partir del índice en `folder`."""
    con = sqlite3.connect(f"file:{folder / config.DB_NAME}?mode=ro", uri=True)
    meta = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM meta")}
    con.close()
    version = meta["built_at"].replace("-", "").replace(":", "")      # 20261022T123005
    vdir = out / version
    vdir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in INDEX_FILES:
        src = folder / name
        if not src.exists():
            raise FileNotFoundError(f"Falta {src}. ¿Corriste scripts.ingest con esta versión?")
        dst_name = name + (".gz" if name in GZ_FILES else "")
        dst = vdir / dst_name
        if name in GZ_FILES:
            with open(src, "rb") as f, gzip.open(dst, "wb", compresslevel=6) as g:
                shutil.copyfileobj(f, g, 1 << 20)
        else:
            shutil.copyfile(src, dst)
        files[name] = {"path": f"{version}/{dst_name}", "sha256": sha256(src),
                       "size": src.stat().st_size, "gz": name in GZ_FILES}
    manifest = {"version": version, "built_at": meta["built_at"], "rows": meta.get("rows"),
                "model": meta.get("model"), "dim": meta.get("dim"), "days": meta.get("days"), "files": files}
    (out / config.MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    log(f"Versión {version}: {sum((vdir / Path(f['path']).name).stat().st_size for f in files.values()) / 1e6:.0f} MB "
        f"para transferir ({manifest['rows']:,} concursos)")
    return manifest


# --------------------------------------------------------------------------- leer
def _get(url: str, dest: Path | None = None):
    """GET de http(s):// o file://. Devuelve bytes, o escribe en `dest` si se indica."""
    if url.startswith("file://"):
        p = Path(urlparse(url).path)
        if dest is None:
            return p.read_bytes()
        shutil.copyfile(p, dest)
        return None
    import requests

    headers = {"Authorization": f"Bearer {config.ARTIFACTS_TOKEN}"} if config.ARTIFACTS_TOKEN else {}
    with requests.get(url, headers=headers, stream=dest is not None, timeout=900) as r:
        r.raise_for_status()
        if dest is None:
            return r.content
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return None


def fetch_manifest(base: str) -> dict:
    return json.loads(_get(f"{base}/{config.MANIFEST_NAME}?t={int(time.time())}" if base.startswith("http")
                           else f"{base}/{config.MANIFEST_NAME}"))


def download(base: str, manifest: dict, dest: Path) -> None:
    """Descarga y verifica todos los archivos de una versión en `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    for name, f in manifest["files"].items():
        final = dest / name
        if final.exists() and final.stat().st_size == f["size"] and sha256(final) == f["sha256"]:
            continue
        t0 = time.time()
        tmp = dest / (name + ".part")
        _get(f"{base}/{f['path']}", tmp)
        if f.get("gz"):
            raw = dest / (name + ".raw")
            with gzip.open(tmp, "rb") as g, open(raw, "wb") as o:
                shutil.copyfileobj(g, o, 1 << 20)
            tmp.unlink()
            tmp = raw
        if sha256(tmp) != f["sha256"]:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"Hash incorrecto en {name}: la descarga está corrupta o incompleta")
        tmp.replace(final)
        log(f"{name}: {f['size'] / 1e6:.0f} MB en {time.time() - t0:.0f}s")


def pull_into(base: str, folder: Path) -> dict:
    """Pipeline: trae el índice publicado a la carpeta de trabajo (para ingesta incremental)."""
    m = fetch_manifest(base)
    download(base, m, folder)
    log(f"Índice {m['version']} descargado en {folder}")
    return m


# --------------------------------------------------------------------------- API: sincronización
class Syncer:
    """Revisa periódicamente el manifest remoto; si hay versión nueva la descarga en
    data/versions/<v>/, apunta data/current.json a ella y recarga el índice en caliente."""

    def __init__(self, on_new: Callable[[], None]):
        self.on_new = on_new
        self.state = {"enabled": bool(config.ARTIFACTS_URL), "syncing": False, "version": self.current_version(),
                      "last_check": None, "error": None}
        self._lock = threading.Lock()

    @staticmethod
    def current_version() -> str | None:
        cur = config.DATA_DIR / "current.json"
        try:
            return json.loads(cur.read_text())["version"]
        except (OSError, ValueError, KeyError):
            return None

    def start(self) -> None:
        if not config.ARTIFACTS_URL:
            return
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while True:
            self.sync()
            if config.ARTIFACTS_POLL <= 0:
                return
            time.sleep(config.ARTIFACTS_POLL)

    def sync(self) -> dict:
        if not self._lock.acquire(blocking=False):
            return self.state
        try:
            self.state.update(syncing=True, error=None)
            m = fetch_manifest(config.ARTIFACTS_URL)
            self.state["last_check"] = time.time()
            if m["version"] != self.state["version"]:
                log(f"Nueva versión {m['version']} ({m['rows']:,} concursos); descargando…")
                vdir = config.DATA_DIR / "versions" / m["version"]
                download(config.ARTIFACTS_URL, m, vdir)
                tmp = config.DATA_DIR / "current.json.tmp"
                tmp.write_text(json.dumps({"version": m["version"], "manifest": m}))
                tmp.replace(config.DATA_DIR / "current.json")
                prev = self.state["version"]
                self.state["version"] = m["version"]
                self.on_new()
                # conservar solo la versión vigente (y la anterior, por si hay lecturas en curso)
                for d in (config.DATA_DIR / "versions").iterdir():
                    if d.is_dir() and d.name not in (m["version"], prev):
                        shutil.rmtree(d, ignore_errors=True)
                log(f"Versión {m['version']} activa")
        except Exception as e:  # noqa: BLE001
            self.state["error"] = str(e)
            log(f"Error al sincronizar: {e}")
        finally:
            self.state["syncing"] = False
            self._lock.release()
        return self.state
