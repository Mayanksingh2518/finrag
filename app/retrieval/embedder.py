"""Local sentence embeddings with an on-disk cache.

Embedding 17k chunks on a laptop CPU takes minutes, so vectors are cached in
``data/indexes/`` keyed by chunk_id + content hash: re-running the ingestion
pipeline only re-embeds chunks whose text actually changed. The cache is also
written in slices so an interrupted build resumes where it stopped.
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Protocol

import numpy as np

from app.ingestion.models import Chunk

logger = logging.getLogger(__name__)

# bge v1.5 models are trained with this instruction on the query side only.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, device: str = "auto", batch_size: int = 32, max_seq_length: int = 512):
        from sentence_transformers import SentenceTransformer

        from app.devices import resolve_device

        self.model_name = model_name
        self.device = resolve_device(device)
        self.model = SentenceTransformer(model_name, device=self.device)
        self.model.max_seq_length = max_seq_length
        self.dim = self.model.get_sentence_embedding_dimension()
        self.batch_size = batch_size
        self.query_instruction = BGE_QUERY_INSTRUCTION if "bge" in model_name.lower() else ""

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(
            texts, batch_size=self.batch_size, normalize_embeddings=True, convert_to_numpy=True
        ).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([self.query_instruction + text])[0]


def content_hash(chunk: Chunk) -> str:
    return hashlib.sha1(chunk.embed_text.encode("utf-8")).hexdigest()[:16]


class EmbeddingCache:
    def __init__(self, index_dir: Path, model_name: str):
        safe = model_name.replace("/", "__")
        self.vectors_path = index_dir / f"embeddings__{safe}.npy"
        self.meta_path = index_dir / f"embeddings__{safe}.json"
        self.model_name = model_name

    def load(self) -> dict[str, np.ndarray]:
        """Return {f"{chunk_id}:{hash}": vector} for everything cached."""
        if not (self.vectors_path.exists() and self.meta_path.exists()):
            return {}
        meta = json.loads(self.meta_path.read_text())
        vectors = np.load(self.vectors_path)
        return dict(zip(meta["keys"], vectors))

    def save(self, cache: dict[str, np.ndarray]) -> None:
        self.vectors_path.parent.mkdir(parents=True, exist_ok=True)
        keys = list(cache)
        np.save(self.vectors_path, np.stack([cache[k] for k in keys]) if keys else np.zeros((0, 0)))
        self.meta_path.write_text(json.dumps({"model": self.model_name, "keys": keys}))


def embed_chunks(
    chunks: list[Chunk], embedder: Embedder, cache: EmbeddingCache, slice_size: int = 1024
) -> np.ndarray:
    """Embeddings for ``chunks`` in order, computing only what the cache lacks."""
    stored = cache.load()
    keys = [f"{c.chunk_id}:{content_hash(c)}" for c in chunks]
    missing = [i for i, k in enumerate(keys) if k not in stored]
    logger.info("Embeddings: %d cached, %d to compute", len(chunks) - len(missing), len(missing))

    start = time.perf_counter()
    for offset in range(0, len(missing), slice_size):
        idxs = missing[offset : offset + slice_size]
        vectors = embedder.embed_documents([chunks[i].embed_text for i in idxs])
        stored.update({keys[i]: v for i, v in zip(idxs, vectors)})
        cache.save({k: stored[k] for k in keys if k in stored})  # checkpoint; drops stale entries
        done = offset + len(idxs)
        rate = done / (time.perf_counter() - start)
        logger.info(
            "  embedded %d/%d (%.1f chunks/s, ~%.0f s left)", done, len(missing), rate, (len(missing) - done) / rate
        )

    if not missing:
        cache.save({k: stored[k] for k in keys})  # prune entries for chunks that no longer exist
    return np.stack([stored[k] for k in keys]).astype(np.float32)
