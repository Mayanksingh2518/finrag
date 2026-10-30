"""Build a Retriever from the processed chunks and cached embeddings."""

import logging
import time

from app.config import Settings, get_settings
from app.devices import check_torch_faiss_compatible, resolve_device
from app.retrieval.bm25 import BM25Index
from app.retrieval.dense import DenseIndex
from app.retrieval.embedder import EmbeddingCache, SentenceTransformerEmbedder, embed_chunks
from app.retrieval.retriever import Retriever
from app.retrieval.store import ChunkStore

logger = logging.getLogger(__name__)


def _pgvector(settings: Settings):
    from app.retrieval.pg_store import PgVectorIndex, connect, corpus_meta, load_chunks

    conn = connect(settings.database_url)
    meta = corpus_meta(conn)
    if meta.get("embedding_model") != settings.embedding_model:
        raise RuntimeError(f"Postgres holds embeddings from {meta.get('embedding_model')!r}, settings use "
                           f"{settings.embedding_model!r}: run `python -m app.retrieval.pg_store`")
    store = ChunkStore(load_chunks(conn))
    return store, PgVectorIndex(conn, len(store))


def build_retriever(settings: Settings | None = None, with_reranker: bool = True) -> Retriever:
    settings = settings or get_settings()
    check_torch_faiss_compatible(resolve_device(settings.device))
    start = time.perf_counter()

    embedder = SentenceTransformerEmbedder(settings.embedding_model, device=settings.device)
    if settings.vector_backend == "pgvector":
        store, dense = _pgvector(settings)
    else:
        store = ChunkStore.from_jsonl(settings.processed_dir / "chunks.jsonl")
        vectors = embed_chunks(store.chunks, embedder, EmbeddingCache(settings.index_dir, settings.embedding_model))
        dense = DenseIndex(vectors)
    bm25 = BM25Index([c.embed_text for c in store.chunks])

    reranker = None
    if with_reranker:
        from app.reranking.cross_encoder import CrossEncoderReranker

        reranker = CrossEncoderReranker(settings.reranker_model, device=settings.device)

    logger.info("Retriever ready (%s): %d chunks in %.1f s", settings.vector_backend, len(store),
                time.perf_counter() - start)
    return Retriever(store, bm25, dense, embedder, reranker)
