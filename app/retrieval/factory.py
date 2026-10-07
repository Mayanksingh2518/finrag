"""Build a Retriever from the processed chunks and cached embeddings."""

import logging
import time

from app.config import Settings, get_settings
from app.retrieval.bm25 import BM25Index
from app.retrieval.dense import DenseIndex
from app.retrieval.embedder import EmbeddingCache, SentenceTransformerEmbedder, embed_chunks
from app.retrieval.retriever import Retriever
from app.retrieval.store import ChunkStore

logger = logging.getLogger(__name__)


def build_retriever(settings: Settings | None = None, with_reranker: bool = True) -> Retriever:
    settings = settings or get_settings()
    start = time.perf_counter()

    store = ChunkStore.from_jsonl(settings.processed_dir / "chunks.jsonl")
    embedder = SentenceTransformerEmbedder(settings.embedding_model, device=settings.device)
    vectors = embed_chunks(store.chunks, embedder, EmbeddingCache(settings.index_dir, settings.embedding_model))
    dense = DenseIndex(vectors)
    bm25 = BM25Index([c.embed_text for c in store.chunks])

    reranker = None
    if with_reranker:
        from app.reranking.cross_encoder import CrossEncoderReranker

        reranker = CrossEncoderReranker(settings.reranker_model, device=settings.device)

    logger.info("Retriever ready: %d chunks in %.1f s", len(store), time.perf_counter() - start)
    return Retriever(store, bm25, dense, embedder, reranker)
