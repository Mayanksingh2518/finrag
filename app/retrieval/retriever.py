"""Retrieval orchestration: BM25 / dense / hybrid (RRF) / hybrid + cross-encoder rerank.

Every mode goes through the same filters and returns per-stage scores and
timings, so the Phase 4 ablation compares modes on identical inputs.
"""

import time

from app.reranking.cross_encoder import Reranker
from app.retrieval.bm25 import BM25Index
from app.retrieval.dense import DenseIndex
from app.retrieval.embedder import Embedder
from app.retrieval.hybrid import reciprocal_rank_fusion
from app.retrieval.store import ChunkStore
from app.retrieval.types import ScoredChunk, SearchFilters, SearchMode, SearchResult


class Retriever:
    def __init__(
        self,
        store: ChunkStore,
        bm25: BM25Index,
        dense: DenseIndex,
        embedder: Embedder,
        reranker: Reranker | None = None,
        candidates_per_retriever: int = 50,
        rerank_candidates: int = 30,
    ):
        self.store = store
        self.bm25 = bm25
        self.dense = dense
        self.embedder = embedder
        self.reranker = reranker
        self.candidates_per_retriever = candidates_per_retriever
        self.rerank_candidates = rerank_candidates

    def search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        k: int = 8,
        mode: SearchMode = "hybrid_rerank",
    ) -> SearchResult:
        filters = filters or SearchFilters()
        timings: dict[str, float] = {}
        result = SearchResult(query=query, mode=mode, filters=filters, hits=[], timings_ms=timings)
        total_start = time.perf_counter()

        mask = self.store.mask(filters)
        if mask is not None and not mask.any():
            return result
        n = max(k, self.candidates_per_retriever)
        stages: dict[int, dict[str, float]] = {}

        bm25_rows: list[int] = []
        if mode != "dense":
            start = time.perf_counter()
            hits = self.bm25.search(query, n, mask)
            timings["bm25"] = _ms(start)
            bm25_rows = [row for row, _ in hits]
            for rank, (row, score) in enumerate(hits, start=1):
                stages.setdefault(row, {}).update(bm25_rank=rank, bm25_score=score)

        dense_rows: list[int] = []
        if mode != "bm25":
            start = time.perf_counter()
            query_vector = self.embedder.embed_query(query)
            timings["embed_query"] = _ms(start)
            start = time.perf_counter()
            hits = self.dense.search(query_vector, n, mask)
            timings["dense"] = _ms(start)
            dense_rows = [row for row, _ in hits]
            for rank, (row, score) in enumerate(hits, start=1):
                stages.setdefault(row, {}).update(dense_rank=rank, dense_score=score)

        if mode == "bm25":
            ranked = [(row, stages[row]["bm25_score"]) for row in bm25_rows]
        elif mode == "dense":
            ranked = [(row, stages[row]["dense_score"]) for row in dense_rows]
        else:
            ranked = reciprocal_rank_fusion([bm25_rows, dense_rows])
            for row, score in ranked:
                stages[row]["rrf"] = score

        if mode == "hybrid_rerank" and self.reranker is not None:
            candidates = ranked[: self.rerank_candidates]
            start = time.perf_counter()
            scores = self.reranker.score(query, [self.store.chunks[row].embed_text for row, _ in candidates])
            timings["rerank"] = _ms(start)
            ranked = sorted(zip((row for row, _ in candidates), scores), key=lambda x: -x[1])
            for row, score in ranked:
                stages[row]["rerank"] = score

        result.hits = [
            ScoredChunk(chunk=self.store.chunks[row], score=score, stages=stages.get(row, {}))
            for row, score in ranked[:k]
        ]
        timings["total"] = _ms(total_start)
        return result


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)
