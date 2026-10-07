"""Page-level retrieval metrics against gold evidence.

A retrieved chunk *covers* a gold evidence item when it is from the same filing
(ticker, fiscal year) and its page range overlaps one of the item's pages.

- recall@k: fraction of gold evidence items covered by the top-k chunks
  (multi-evidence questions, e.g. one item per year in a trend, get partial credit).
- hit@k: 1 if any gold item is covered in the top k.
- mrr: 1 / rank of the first chunk covering any gold item (0 if none).
- ndcg@k: a chunk gains 1 only if it covers an item not covered by a higher-ranked
  chunk, so ten chunks from the same gold page don't count ten times; the ideal
  ranking covers min(#items, k) items in the first positions.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.evaluation.golden import GoldEvidence


@dataclass(frozen=True)
class RetrievedPage:
    """The bits of a retrieved chunk that relevance depends on."""

    ticker: str
    fiscal_year: int
    page_start: int
    page_end: int


def covered_items(hit: RetrievedPage, evidence: Sequence[GoldEvidence]) -> set[int]:
    return {
        i
        for i, e in enumerate(evidence)
        if e.ticker == hit.ticker
        and e.fiscal_year == hit.fiscal_year
        and any(hit.page_start <= p <= hit.page_end for p in e.pages)
    }


def score_ranking(ranking: Sequence[RetrievedPage], evidence: Sequence[GoldEvidence], ks: Sequence[int]) -> dict[str, float]:
    """All metrics for one question. `evidence` must be non-empty."""
    if not evidence:
        raise ValueError("retrieval metrics are undefined for questions without evidence")
    per_rank = [covered_items(h, evidence) for h in ranking]

    metrics: dict[str, float] = {}
    first = next((rank for rank, items in enumerate(per_rank, 1) if items), None)
    metrics["mrr"] = 1.0 / first if first else 0.0
    for k in ks:
        top = set().union(*per_rank[:k]) if per_rank[:k] else set()
        metrics[f"recall@{k}"] = len(top) / len(evidence)
        metrics[f"hit@{k}"] = float(bool(top))

    k = max(ks)
    seen: set[int] = set()
    dcg = 0.0
    for rank, items in enumerate(per_rank[:k], 1):
        if items - seen:
            dcg += 1.0 / math.log2(rank + 1)
            seen |= items
    ideal = sum(1.0 / math.log2(r + 1) for r in range(1, min(len(evidence), k) + 1))
    metrics[f"ndcg@{k}"] = dcg / ideal
    return metrics
