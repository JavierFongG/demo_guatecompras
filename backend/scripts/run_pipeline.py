"""Pipeline completo de datos, pensado para correr como tarea programada en cualquier lado
(GitHub Actions, Cloud Run Jobs, cron en un servidor o tu Mac):

    1. pull     trae el índice publicado (GC_ARTIFACTS_URL) si no hay uno local → ingesta incremental
    2. download baja de Guatecompras solo los meses que cambiaron
    3. ingest   reconstruye el índice reutilizando embeddings
    4. publish  sube la nueva versión (GC_PUBLISH_TARGET)

Uso (desde backend/):  python -m scripts.run_pipeline [--days 548] [--no-pull] [--no-publish]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402
from app.artifacts import log, pull_into  # noqa: E402


def step(*args: str) -> None:
    log("$ python -m " + " ".join(args))
    subprocess.run([sys.executable, "-m", *args], cwd=Path(__file__).resolve().parents[1], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.WINDOW_DAYS)
    ap.add_argument("--no-pull", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--full", action="store_true", help="recalcular todos los embeddings")
    args = ap.parse_args()

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not args.no_pull and config.ARTIFACTS_URL and not config.DB_PATH.exists():
        try:
            pull_into(config.ARTIFACTS_URL, config.DATA_DIR)
        except Exception as e:  # primera vez: aún no hay nada publicado
            log(f"No se pudo traer el índice publicado ({e}); se construye desde cero")

    step("scripts.download", "--days", str(args.days))
    step("scripts.ingest", "--days", str(args.days), *(["--full"] if args.full else []))

    target = os.getenv("GC_PUBLISH_TARGET")
    if not args.no_publish and target:
        step("scripts.publish", "--to", target)
    elif not args.no_publish:
        log("Sin GC_PUBLISH_TARGET: el índice queda solo en " + str(config.DATA_DIR))


if __name__ == "__main__":
    main()
