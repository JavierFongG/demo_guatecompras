"""Descarga los archivos mensuales OCDS (JSON zip) de Guatecompras.

Uso (desde la carpeta backend/):
    python -m scripts.download              # meses que cubren la ventana configurada (18 meses)
    python -m scripts.download --days 90
    python -m scripts.download --months 2026-07 2026-08
    python -m scripts.download --force      # vuelve a descargar aunque ya exista

Solo vuelve a bajar un mes si el portal reporta una versión más nueva que la local.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402

HEADERS = {"User-Agent": "guatecompras-buscador-local/1.0"}


def months_for_window(days: int) -> list[tuple[int, int]]:
    today = date.today()
    start = today - timedelta(days=days)
    y, m, out = start.year, start.month, []
    while (y, m) <= (today.year, today.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def list_remote() -> dict[tuple[int, int], dict]:
    r = requests.get(f"{config.API_BASE}/files", headers=HEADERS, timeout=60)
    r.raise_for_status()
    return {(int(x["year"]), int(x["month"])): x for x in r.json()["result"]}


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(".part")
    with requests.get(url, headers=HEADERS, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()
    tmp.replace(dest)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.WINDOW_DAYS)
    ap.add_argument("--months", nargs="*", help="YYYY-MM explícitos")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    wanted = ([tuple(int(p) for p in s.split("-")) for s in args.months]
              if args.months else months_for_window(args.days))
    remote = list_remote()
    changed = 0

    for i, (y, m) in enumerate(wanted, 1):
        print(f"[{i}/{len(wanted)}] ", end="")
        info = remote.get((y, m))
        if not info:
            print(f"{y}-{m:02d}: no disponible en el portal, se omite")
            continue
        dest = config.RAW_DIR / f"{y}-{m:02d}_Guatecompras_json.zip"
        meta = dest.with_suffix(".meta.json")
        remote_ts = info.get("timestamp", "")
        local_ts = json.loads(meta.read_text()).get("timestamp", "") if meta.exists() else ""
        if dest.exists() and not args.force and local_ts == remote_ts:
            print(f"{y}-{m:02d}: al día ({remote_ts}), se omite")
            continue
        print(f"{y}-{m:02d}: descargando {info['files']['json']}")
        for attempt in range(3):
            try:
                download(info["files"]["json"], dest)
                break
            except requests.RequestException as e:
                if attempt == 2:
                    raise
                print(f"\n  error ({e}); reintentando…")
        meta.write_text(json.dumps({"timestamp": remote_ts, "url": info["files"]["json"]}))
        changed += 1
    print(f"Listo. {changed} mes(es) actualizado(s). Archivos en {config.RAW_DIR}")


if __name__ == "__main__":
    main()
