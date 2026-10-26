"""Generación de embeddings 100% local, sin PyTorch.

Por defecto usa la versión ONNX cuantizada (int8, 118 MB) de intfloat/multilingual-e5-small
con onnxruntime + tokenizers. Pesa ~10 veces menos en memoria que sentence-transformers/PyTorch
y es la MISMA implementación en el pipeline (documentos) y en la API (consultas), así los
vectores son comparables.

Opcionales:
  GC_EMBEDDER=st    sentence-transformers (requiere instalar torch y sentence-transformers)
  GC_EMBEDDER=hash  vectorizador por n-gramas sin modelo (solo pruebas sin internet)
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

import numpy as np

from . import config


class Embedder:
    name: str
    dim: int

    def encode_passages(self, texts: list[str], batch_size: int = 32, progress: bool = False) -> np.ndarray:
        raise NotImplementedError

    def encode_query(self, text: str) -> np.ndarray:
        raise NotImplementedError


# --------------------------------------------------------------------------- ONNX
def _download(repo: str, filename: str) -> Path:
    """Descarga un archivo de Hugging Face Hub a la caché local (solo la primera vez)."""
    dest = config.CACHE_DIR / "models" / repo.replace("/", "__") / filename
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{config.HF_ENDPOINT}/{repo}/resolve/main/{filename}"
    headers = {"Authorization": f"Bearer {config.HF_TOKEN}"} if config.HF_TOKEN else {}
    print(f"Descargando modelo {repo}/{filename} …", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers=headers, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return dest


def model_files() -> tuple[Path, Path]:
    """Rutas a (modelo .onnx, tokenizer.json): de GC_MODEL_DIR si existe, si no de HF Hub."""
    if config.MODEL_DIR:
        d = Path(config.MODEL_DIR)
        onnx = d / Path(config.ONNX_FILE).name
        if not onnx.exists():
            onnx = next(iter(sorted(d.glob("*.onnx"))), onnx)
        return onnx, d / "tokenizer.json"
    return _download(config.ONNX_REPO, config.ONNX_FILE), _download(config.ONNX_REPO, "tokenizer.json")


class OnnxEmbedder(Embedder):
    def __init__(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path, tok_path = model_files()
        self.tok = Tokenizer.from_file(str(tok_path))
        self.tok.enable_truncation(max_length=config.MAX_TOKENS)
        pad_id = self.tok.token_to_id("<pad>")
        self.tok.enable_padding(pad_id=1 if pad_id is None else pad_id, pad_token="<pad>")

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        threads = config.THREADS or os.cpu_count() or 1
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(model_path), so, providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.sess.get_inputs()}
        # El nombre identifica el modelo: si cambia, el pipeline recalcula todos los embeddings
        self.name = f"onnx:{config.ONNX_REPO}/{config.ONNX_FILE}" if not config.MODEL_DIR \
            else f"onnx:{model_path.name}"
        self.dim = int(self._run(["query: hola"]).shape[1])

    def _run(self, texts: list[str]) -> np.ndarray:
        enc = self.tok.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self.sess.run(None, feed)[0]                       # (B, T, D)
        m = mask[..., None].astype(np.float32)
        pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)  # mean pooling (e5)
        return (pooled / np.linalg.norm(pooled, axis=1, keepdims=True)).astype(np.float32)

    def encode_passages(self, texts, batch_size=32, progress=False):
        if not texts:
            return np.zeros((0, self.dim), np.float32)
        out = np.zeros((len(texts), self.dim), np.float32)
        order = np.argsort([len(t) for t in texts])   # agrupar por longitud = menos padding
        for i in range(0, len(texts), batch_size):
            idx = order[i:i + batch_size]
            out[idx] = self._run([f"passage: {texts[j]}" for j in idx])
        return out

    def encode_query(self, text):
        return self._run([f"query: {text}"])[0]


# --------------------------------------------------------------------------- sentence-transformers (opcional)
class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # requiere torch

        device = os.getenv("GC_DEVICE")
        if not device:
            try:
                import torch

                device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else None
            except Exception:
                device = None
        self.model = SentenceTransformer(model_name, device=device)
        self.name = model_name
        self.dim = self.model.get_sentence_embedding_dimension()
        self.is_e5 = "e5" in model_name.lower()

    def _p(self, prefix, texts):
        return [f"{prefix}: {t}" for t in texts] if self.is_e5 else texts

    def encode_passages(self, texts, batch_size=64, progress=False):
        return self.model.encode(self._p("passage", texts), batch_size=batch_size, normalize_embeddings=True,
                                 show_progress_bar=progress, convert_to_numpy=True).astype(np.float32)

    def encode_query(self, text):
        return self.model.encode(self._p("query", [text]), normalize_embeddings=True)[0].astype(np.float32)


# --------------------------------------------------------------------------- hash (pruebas)
def _norm_text(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", t)


class HashEmbedder(Embedder):
    """Vectorizador de n-gramas con hashing. NO es semántico; solo para pruebas sin modelo."""

    def __init__(self, dim: int = 384):
        self.name, self.dim = "hash-ngrams", dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for w in _norm_text(text).split():
            w = f" {w} "
            for n in (3, 4):
                for i in range(len(w) - n + 1):
                    v[int(hashlib.md5(w[i:i + n].encode()).hexdigest()[:8], 16) % self.dim] += 1.0
        norm = np.linalg.norm(v)
        return v / norm if norm else v

    def encode_passages(self, texts, batch_size=64, progress=False):
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def encode_query(self, text):
        return self._vec(text)


_instance: Embedder | None = None


def get_embedder() -> Embedder:
    global _instance
    if _instance is None:
        _instance = {"hash": HashEmbedder, "st": lambda: SentenceTransformerEmbedder(config.EMBED_MODEL)}.get(
            config.EMBEDDER, OnnxEmbedder)()
    return _instance
