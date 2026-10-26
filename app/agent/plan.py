"""Retrieval plan: intent, one sub-query per (company, fiscal year), per-entity quotas, section prior.

Phase 4 measured that one search over several filings lets the best-matching filing crowd
out the others, and that a global top-k can't hold a 4-year trend at k=5. The plan therefore
searches each (ticker, year) separately, keeps the top `quota` hits of each, and interleaves
them (every entity's best hit first). All sub-queries are reranked in one batched call.

Section prior: on questions about a reported financial metric (revenue, net income, capex,
deliveries...), the figure's home is MD&A (Item 7). The cross-encoder often prefers an Item 8
note, the Item 1 business overview or the Item 5 buyback table that mentions the same metric,
so MD&A chunks get a small additive bonus on the reranker's 0-1 score. It is a prior, not a
filter: a clearly better chunk elsewhere still wins (risk-factor and employee questions are
answered outside Item 7).

Latency: batching the sub-queries' reranking saves only ~7% (the cross-encoder is compute-bound
on pairs x tokens, not call overhead). The real knob is `rerank_candidates` per sub-query: 15
instead of 30 halves multi-entity latency for ~0.03 context recall (reports/plan_v0.md).
"""

import math
import re
from dataclasses import dataclass, field, replace
from typing import Literal

from app.retrieval.decompose import interleave, split_filters
from app.retrieval.types import ScoredChunk, SearchFilters, SearchMode, SearchResult

Intent = Literal["lookup", "numeric", "trend", "comparison"]

DEFAULT_SECTION_BONUS = 0.05  # on the reranker's sigmoid score; see "Retrieval plan v0" in progress.md

_COMPARE = re.compile(r"\bcompare|\bcompared?\b|\bversus\b|\bvs\.?\b|\bwhich\b.*\b(?:more|less|faster|slower|higher|lower)\b",
                      re.IGNORECASE)
_TREND = re.compile(r"\btrend|\bover time\b|\beach (?:fiscal )?year\b|\bevolve|\bchanged?\b.*\bfrom\b", re.IGNORECASE)
_HOW_MUCH = re.compile(r"\bhow (?:much|many)\b", re.IGNORECASE)
# Reported financial metrics: their figures live in MD&A (and Item 8), not in Item 1/1A/5.
_METRIC = re.compile(
    r"\b(?:revenues?|net sales|sales|net income|earn(?:ed|ings)?|profit|operating (?:income|loss)|margin|"
    r"capital expenditures?|capex|cash flows?|expenses?|interest income|deliver(?:ed|ies|y)|repurchase[sd]?|"
    r"buybacks?|growth|grew|grow)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SubQuery:
    query: str
    filters: SearchFilters


@dataclass(frozen=True)
class RetrievalPlan:
    query: str
    filters: SearchFilters
    intent: Intent
    sub_queries: tuple[SubQuery, ...]
    quota: int  # hits kept per sub-query
    section_bonus: dict[str, float] = field(default_factory=dict)  # added to reranker scores by section
    rerank_candidates: int | None = None  # per sub-query; None = the retriever's default (30)

    @property
    def decomposed(self) -> bool:
        return len(self.sub_queries) > 1


def classify_intent(question: str, filters: SearchFilters) -> Intent:
    if len(filters.tickers or ()) > 1 or _COMPARE.search(question):
        return "comparison"
    if len(filters.fiscal_years or ()) > 1 or _TREND.search(question):
        return "trend"
    if _HOW_MUCH.search(question) or _METRIC.search(question):
        return "numeric"
    return "lookup"


def section_prior(question: str, bonus: float = DEFAULT_SECTION_BONUS) -> dict[str, float]:
    """MD&A bonus for questions about a reported metric; none otherwise."""
    return {"Item 7": bonus} if bonus and _METRIC.search(question) else {}


def make_plan(query: str, filters: SearchFilters, k: int = 10, min_quota: int = 2,
              section_bonus: float = DEFAULT_SECTION_BONUS, rerank_candidates: int | None = None) -> RetrievalPlan:
    """k is the total the caller wants; each sub-query gets ceil(k / n), at least `min_quota`.

    With many sub-queries the plan may return more than k hits; the interleaved order puts
    every entity's best hit first, so a downstream token budget cuts the tails evenly.
    """
    parts = split_filters(filters)
    quota = k if len(parts) == 1 else max(min_quota, math.ceil(k / len(parts)))
    return RetrievalPlan(
        query=query,
        filters=filters,
        intent=classify_intent(query, filters),
        sub_queries=tuple(SubQuery(query, f) for f in parts),
        quota=quota,
        section_bonus=section_prior(query, section_bonus),
        rerank_candidates=rerank_candidates,
    )


def apply_prior(hits: list[ScoredChunk], bonus: dict[str, float]) -> list[ScoredChunk]:
    if not bonus:
        return hits
    out = []
    for h in hits:
        b = bonus.get(h.chunk.section, 0.0)
        out.append(replace(h, score=h.score + b, stages={**h.stages, "section_prior": b}) if b else h)
    return sorted(out, key=lambda h: -h.score)


def execute_plan(retriever, plan: RetrievalPlan, mode: SearchMode = "hybrid_rerank") -> SearchResult:
    """Run every sub-query (one batched rerank), apply the prior, keep `quota` each, interleave.

    The prior needs the whole reranked pool (a chunk ranked below the quota may move up),
    so sub-searches return all rerank candidates and are cut after the prior.
    """
    rerank = mode == "hybrid_rerank" and getattr(retriever, "reranker", None) is not None
    rerank_n = plan.rerank_candidates or retriever.rerank_candidates
    pool = max(plan.quota, rerank_n) if rerank and plan.section_bonus else plan.quota
    results = retriever.search_many([(s.query, s.filters) for s in plan.sub_queries], k=pool, mode=mode,
                                    rerank_candidates=rerank_n)
    bonus = plan.section_bonus if rerank else {}
    hit_lists = [apply_prior(r.hits, bonus)[: plan.quota] for r in results]
    timings: dict[str, float] = {}
    for r in results:
        for stage, ms in r.timings_ms.items():
            timings[stage] = round(timings.get(stage, 0.0) + ms, 1)
    hits = interleave(hit_lists, k=sum(map(len, hit_lists)))
    return SearchResult(plan.query, mode, plan.filters, hits, timings)
