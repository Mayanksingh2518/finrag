"""Per-entity decomposition: one sub-search per (company, fiscal year), merged round-robin.

A single query over "MSFT and AMZN" or "FY2022-2025" lets the strongest-matching
filing crowd the others out of the top k (the v0 eval measured this on trend and
comparison questions). Searching each (ticker, year) separately and interleaving the
results guarantees every entity a slot near the top. The Phase 6 agent will also
rewrite the query per entity; here the same query text is reused.
"""

import itertools

from app.retrieval.types import ScoredChunk, SearchFilters, SearchMode, SearchResult


def split_filters(filters: SearchFilters) -> list[SearchFilters]:
    """One filter per (ticker, fiscal year) combination; [filters] if there is nothing to split."""
    tickers = filters.tickers or (None,)
    years = filters.fiscal_years or (None,)
    if len(tickers) * len(years) <= 1:
        return [filters]
    return [
        SearchFilters(
            tickers=(t,) if t else None,
            fiscal_years=(y,) if y else None,
            sections=filters.sections,
            chunk_types=filters.chunk_types,
        )
        for t, y in itertools.product(tickers, years)
    ]


def interleave(hit_lists: list[list[ScoredChunk]], k: int) -> list[ScoredChunk]:
    """Round-robin merge (rank 1 of every list, then rank 2, ...), skipping duplicate chunks.

    Within a tier, hits are ordered by score: every entity still gets one slot per tier,
    but the strongest match comes first. Scores are comparable across lists because every
    sub-search scores the same query with the same model (reranker or RRF).
    """
    merged: list[ScoredChunk] = []
    seen: set[str] = set()
    for tier in itertools.zip_longest(*hit_lists):
        for hit in sorted((h for h in tier if h is not None), key=lambda h: -h.score):
            if hit.chunk.chunk_id not in seen:
                seen.add(hit.chunk.chunk_id)
                merged.append(hit)
    return merged[:k]


def search_decomposed(searcher, query: str, filters: SearchFilters, k: int, mode: SearchMode) -> SearchResult:
    """Like `searcher.search`, but fans out over (ticker, year) pairs. Timings are summed over sub-searches."""
    parts = split_filters(filters)
    if len(parts) == 1:
        return searcher.search(query, filters, k=k, mode=mode)
    results = [searcher.search(query, f, k=k, mode=mode) for f in parts]
    timings: dict[str, float] = {}
    for r in results:
        for stage, ms in r.timings_ms.items():
            timings[stage] = timings.get(stage, 0.0) + ms
    return SearchResult(query, mode, filters, interleave([r.hits for r in results], k), timings)
