"""Cada prueba arranca la API con su propia configuración (variables de entorno) y sin índice:
config se lee al importar, así que los módulos se recargan."""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    def _make(**env):
        base = {"GC_DATA_DIR": str(tmp_path), "GC_EMBEDDER": "hash", "GC_ARTIFACTS_URL": ""}
        for k, v in {**base, **env}.items():
            monkeypatch.setenv(k, v)
        from app import auth, config, main
        importlib.reload(config)
        importlib.reload(auth)
        importlib.reload(main)
        return TestClient(main.app), auth
    return _make
