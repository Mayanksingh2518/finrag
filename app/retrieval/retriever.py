"""Retrieval orchestration: BM25 / dense / hybrid (RRF) / hybrid + cross-encoder rerank.

Every mode goes through the same filters and returns per-stage scores and
timings, so the Phase 4 ablation compares modes on identical inputs.
"""

import time
from collections.abc import Sequence

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
        return self.search_many([(query, filters)], k=k, mode=mode)[0]

    def search_many(
        self,
        requests: Sequence[tuple[str, SearchFilters | None]],
        k: int = 8,
        mode: SearchMode = "hybrid_rerank",
        rerank_candidates: int | None = None,
    ) -> list[SearchResult]:
        """Several searches whose cross-encoder passes run as one batched model call.

        Candidate generation (BM25, dense, RRF) is per request and cheap; reranking is the
        cost, and one call over all (query, passage) pairs keeps the device busy instead of
        paying per-call overhead per sub-query. Each result's rerank time is its share of the
        batch by pair count, so summing timings over results still gives wall time.
        """
        rerank_n = rerank_candidates or self.rerank_candidates
        pending = []  # (result, ranked, stages, start)
        for query, filters in requests:
            filters = filters or SearchFilters()
            start = time.perf_counter()
            result = SearchResult(query=query, mode=mode, filters=filters, hits=[], timings_ms={})
            ranked, stages = self._candidates(query, filters, max(k, self.candidates_per_retriever), mode,
                                              result.timings_ms)
            if mode == "hybrid_rerank" and self.reranker is not None:
                ranked = ranked[:rerank_n]
            result.timings_ms["total"] = _ms(start)
            pending.append((result, ranked, stages))

        if mode == "hybrid_rerank" and self.reranker is not None:
            pairs = [(r.query, self.store.chunks[row].embed_text) for r, ranked, _ in pending for row, _ in ranked]
            start = time.perf_counter()
            scores = iter(self._score_pairs(pairs))
            rerank_ms = (time.perf_counter() - start) * 1000
            for i, (result, ranked, stages) in enumerate(pending):
                rows = [row for row, _ in ranked]
                reranked = sorted(zip(rows, (next(scores) for _ in rows)), key=lambda x: -x[1])
                for row, score in reranked:
                    stages[row]["rerank"] = score
                share = round(rerank_ms * len(rows) / max(len(pairs), 1), 1)
                result.timings_ms["rerank"] = share
                result.timings_ms["total"] = round(result.timings_ms["total"] + share, 1)
                pending[i] = (result, reranked, stages)

        for result, ranked, stages in pending:
            result.hits = [
                ScoredChunk(chunk=self.store.chunks[row], score=score, stages=stages.get(row, {}))
                for row, score in ranked[:k]
            ]
        return [result for result, _, _ in pending]

    def _candidates(
        self, query: str, filters: SearchFilters, n: int, mode: SearchMode, timings: dict[str, float]
    ) -> tuple[list[tuple[int, float]], dict[int, dict[str, float]]]:
        """First-stage ranking (BM25, dense or their RRF fusion) as (row, score), best first."""
        mask = self.store.mask(filters)
        if mask is not None and not mask.any():
            return [], {}
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
            hits = self.dense.search(query_vector, n, mask, filters)
            timings["dense"] = _ms(start)
            dense_rows = [row for row, _ in hits]
            for rank, (row, score) in enumerate(hits, start=1):
                stages.setdefault(row, {}).update(dense_rank=rank, dense_score=score)

        if mode == "bm25":
            return [(row, stages[row]["bm25_score"]) for row in bm25_rows], stages
        if mode == "dense":
            return [(row, stages[row]["dense_score"]) for row in dense_rows], stages
        ranked = reciprocal_rank_fusion([bm25_rows, dense_rows])
        for row, score in ranked:
            stages[row]["rrf"] = score
        return ranked, stages

    def _score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        """One model call when the reranker takes pairs; otherwise one call per distinct query."""
        if not pairs:
            return []
        assert self.reranker is not None
        if hasattr(self.reranker, "score_pairs"):
            return self.reranker.score_pairs(pairs)
        by_query: dict[str, list[int]] = {}
        for i, (query, _) in enumerate(pairs):
            by_query.setdefault(query, []).append(i)
        scores = [0.0] * len(pairs)
        for query, idx in by_query.items():
            for i, s in zip(idx, self.reranker.score(query, [pairs[i][1] for i in idx])):
                scores[i] = s
        return scores


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)
