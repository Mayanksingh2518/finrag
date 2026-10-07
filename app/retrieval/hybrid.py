"""Reciprocal Rank Fusion.

BM25 scores (unbounded) and cosine similarities (-1..1) are not comparable,
so instead of normalising scores we fuse ranks: score(d) = sum 1 / (k + rank).
k=60 is the value from the original RRF paper (Cormack et al., 2009) and
damps the influence of any single list's top positions.
"""

from collections import defaultdict

RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: list[list[int]], k: int = RRF_K, weights: list[float] | None = None
) -> list[tuple[int, float]]:
    """Fuse ranked lists of row ids; returns (row, fused score) best-first."""
    weights = weights or [1.0] * len(ranked_lists)
    scores: dict[int, float] = defaultdict(float)
    for ranking, weight in zip(ranked_lists, weights):
        for rank, row in enumerate(ranking, start=1):
            scores[row] += weight / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
