"""Matriz de embeddings compacta.

Se guarda en int8 con una escala por fila (vector ≈ int8 × escala): 4 veces menos memoria
que float32 (≈ 210 MB para 550 mil concursos) y prácticamente el mismo ranking (98–99 de los
100 primeros resultados coinciden). El producto se hace por bloques para no crear una copia
float32 de toda la matriz.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

CHUNK = 32768


def quantize(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """float32 (N, D) → (int8 (N, D), escala float32 (N,))"""
    m = np.abs(v).max(axis=1)
    scale = np.where(m > 0, m / 127.0, 1.0).astype(np.float32)
    q = np.clip(np.rint(v / scale[:, None]), -127, 127).astype(np.int8)
    return q, scale


class Vectors:
    def __init__(self, data: np.ndarray, scale: np.ndarray | None = None):
        self.data = data          # int8 (con escala) o float32 (formato anterior)
        self.scale = scale
        self.shape = data.shape

    @classmethod
    def load(cls, folder: Path, emb_name: str, scale_name: str, legacy_name: str) -> "Vectors | None":
        e, s, legacy = folder / emb_name, folder / scale_name, folder / legacy_name
        if e.exists() and s.exists():
            return cls(np.load(e, mmap_mode="r"), np.load(s))
        if legacy.exists():
            return cls(np.load(legacy, mmap_mode="r"))
        return None

    def __len__(self) -> int:
        return self.shape[0]

    def dot(self, q: np.ndarray) -> np.ndarray:
        """Producto con un vector (D,) → (N,) o con una matriz (D, k) → (N, k)."""
        q = np.asarray(q, dtype=np.float32)
        if self.scale is None:
            return np.asarray(self.data @ q, dtype=np.float32)
        out = np.empty((len(self),) + q.shape[1:], dtype=np.float32)
        for i in range(0, len(self), CHUNK):
            block = self.data[i:i + CHUNK].astype(np.float32) @ q
            s = self.scale[i:i + CHUNK]
            out[i:i + CHUNK] = block * (s if block.ndim == 1 else s[:, None])
        return out

    def __getitem__(self, idx) -> np.ndarray:
        """Filas como float32 (acepta entero, lista o arreglo de índices)."""
        rows = np.asarray(self.data[idx], dtype=np.float32)
        if self.scale is None:
            return rows
        s = self.scale[idx]
        return rows * (s if np.ndim(s) == 0 else np.asarray(s)[:, None])
