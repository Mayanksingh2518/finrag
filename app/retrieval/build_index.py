"""Embed all chunks into the on-disk cache (resumable, incremental).

Usage:
    python -m app.retrieval.build_index
"""

import logging
import time

from app.config import get_settings
from app.retrieval.embedder import EmbeddingCache, SentenceTransformerEmbedder, embed_chunks
from app.retrieval.store import ChunkStore


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()

    store = ChunkStore.from_jsonl(settings.processed_dir / "chunks.jsonl")
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    start = time.perf_counter()
    vectors = embed_chunks(store.chunks, embedder, EmbeddingCache(settings.index_dir, settings.embedding_model))
    logging.info(
        "Done: %d x %d vectors (%.1f MB) in %.0f s",
        *vectors.shape, vectors.nbytes / 1e6, time.perf_counter() - start,
    )


if __name__ == "__main__":
    main()
