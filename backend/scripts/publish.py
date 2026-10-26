"""Publica el índice construido (data/) como artefacto versionado.

Uso (desde backend/):
    python -m scripts.publish --to dir:/ruta/compartida
    python -m scripts.publish --to s3://mi-bucket/index          # R2/B2/GCS: S3_ENDPOINT_URL + credenciales
    python -m scripts.publish --to hf://datasets/usuario/guatecompras-index/index   # HF_TOKEN

Sube primero los archivos de la versión y al final manifest.json, así la API nunca ve una
versión a medias. Conserva las últimas --keep versiones (por defecto 2).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402
from app.artifacts import log, package  # noqa: E402


def publish_dir(stage: Path, version: str, target: Path, keep: int) -> None:
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(stage / version, target / version, dirs_exist_ok=True)
    tmp = target / (config.MANIFEST_NAME + ".tmp")
    shutil.copyfile(stage / config.MANIFEST_NAME, tmp)
    tmp.replace(target / config.MANIFEST_NAME)
    versions = sorted(d.name for d in target.iterdir() if d.is_dir() and d.name[:8].isdigit())
    for old in versions[:-keep]:
        shutil.rmtree(target / old, ignore_errors=True)


def publish_s3(stage: Path, version: str, bucket: str, prefix: str, keep: int) -> None:
    import boto3  # pip install boto3

    s3 = boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT_URL") or None)
    key = lambda *p: "/".join(x.strip("/") for x in (prefix, *p) if x)  # noqa: E731
    for f in (stage / version).iterdir():
        log(f"subiendo {f.name} ({f.stat().st_size / 1e6:.0f} MB)")
        s3.upload_file(str(f), bucket, key(version, f.name))
    s3.upload_file(str(stage / config.MANIFEST_NAME), bucket, key(config.MANIFEST_NAME),
                   ExtraArgs={"CacheControl": "no-cache", "ContentType": "application/json"})
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=key("") + "/" if prefix else "",
                                                         Delimiter="/")
    versions = sorted(p["Prefix"].rstrip("/").split("/")[-1] for page in pages for p in page.get("CommonPrefixes", []))
    versions = [v for v in versions if v[:8].isdigit()]
    for old in versions[:-keep]:
        objs = s3.list_objects_v2(Bucket=bucket, Prefix=key(old) + "/").get("Contents", [])
        if objs:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in objs]})


def publish_hf(stage: Path, version: str, repo_path: str, keep: int) -> None:
    from huggingface_hub import HfApi  # pip install huggingface_hub

    kind, owner, name, *rest = repo_path.split("/")
    repo_type = {"datasets": "dataset", "models": "model", "spaces": "space"}[kind]
    repo_id, prefix = f"{owner}/{name}", "/".join(rest)
    api = HfApi(token=os.getenv("HF_TOKEN") or None)
    api.create_repo(repo_id, repo_type=repo_type, exist_ok=True, private=os.getenv("HF_PRIVATE", "0") == "1")
    join = lambda *p: "/".join(x for x in (prefix, *p) if x)  # noqa: E731
    api.upload_folder(repo_id=repo_id, repo_type=repo_type, folder_path=str(stage / version),
                      path_in_repo=join(version), commit_message=f"Índice {version}")
    api.upload_file(repo_id=repo_id, repo_type=repo_type, path_or_fileobj=str(stage / config.MANIFEST_NAME),
                    path_in_repo=join(config.MANIFEST_NAME), commit_message=f"Manifest {version}")
    entries = api.list_repo_tree(repo_id, repo_type=repo_type, path_in_repo=prefix or None)
    versions = sorted(e.path.split("/")[-1] for e in entries
                      if e.__class__.__name__ == "RepoFolder" and e.path.split("/")[-1][:8].isdigit())
    for old in versions[:-keep]:
        api.delete_folder(path_in_repo=join(old), repo_id=repo_id, repo_type=repo_type,
                          commit_message=f"Borrar versión {old}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default=os.getenv("GC_PUBLISH_TARGET"), help="dir:… | s3://… | hf://…")
    ap.add_argument("--keep", type=int, default=2)
    args = ap.parse_args()
    if not args.to:
        sys.exit("Indica el destino con --to o GC_PUBLISH_TARGET")

    with tempfile.TemporaryDirectory(dir=config.DATA_DIR) as tmp:
        stage = Path(tmp)
        m = package(config.DATA_DIR, stage)
        t = args.to
        if t.startswith("dir:"):
            publish_dir(stage, m["version"], Path(t[4:]).expanduser(), args.keep)
        elif t.startswith("s3://"):
            bucket, _, prefix = t[5:].partition("/")
            publish_s3(stage, m["version"], bucket, prefix, args.keep)
        elif t.startswith("hf://"):
            publish_hf(stage, m["version"], t[5:], args.keep)
        else:
            sys.exit(f"Destino no reconocido: {t}")
    log(f"Publicado {m['version']} en {args.to}")


if __name__ == "__main__":
    main()
