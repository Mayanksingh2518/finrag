"""Retrieval-plan evaluation: per-entity quotas, MD&A section prior and batched reranking vs v0 decomposition.

All configurations get the gold filters and gold standalone queries, so only the plan differs
(the analyzer's filters were shown to cost nothing in `reports/analyzer_v0.md`). Metrics on the
74 answerable questions:
- recall@5 / recall@10 / MRR of the interleaved ranking
- ctx_recall: recall over the chunks that actually reach the LLM (3,500-token budget, as in
  generation). Quotas only change this set: the interleaved top-k prefix is the same either way.
- ctx_coverage: fraction of the question's (company, year) sub-queries with a chunk in the context
- latency p50/p95 of the whole retrieval (hybrid_rerank on the local device)

Usage:
    python -m app.evaluation.run_plan_eval            # -> reports/plan_v0.{md,json}
"""

import argparse
import json
import logging
import statistics
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.agent.plan import execute_plan, make_plan
from app.config import PROJECT_ROOT, get_settings
from app.evaluation.build_golden import DEFAULT_PATH as GOLDEN_PATH
from app.evaluation.golden import GoldQuestion, load_golden
from app.evaluation.metrics import RetrievedPage, covered_items, score_ranking
from app.generation.context import build_sources
from app.retrieval.decompose import search_decomposed, split_filters
from app.retrieval.types import SearchResult

KS = (1, 5, 10)


class _Sequential:
    """Hides `search_many`, so decomposition reranks each sub-query in its own call (v0 behaviour)."""

    def __init__(self, retriever):
        self.search = retriever.search


@dataclass
class PlanRecord:
    id: str
    category: str
    metrics: dict[str, float]
    n_hits: int
    n_ctx: int
    latency_ms: float
    top: list[str] = field(default_factory=list)


def _page(c) -> RetrievedPage:
    return RetrievedPage(c.ticker, c.fiscal_year, c.page_start, c.page_end)


def score(q: GoldQuestion, result: SearchResult, token_budget: int) -> PlanRecord:
    ranking = [_page(h.chunk) for h in result.hits]
    metrics = score_ranking(ranking, q.evidence, KS)
    ctx = build_sources(result.hits, token_budget)
    covered = set().union(*(covered_items(_page(s.chunk), q.evidence) for s in ctx)) if ctx else set()
    metrics["ctx_recall"] = len(covered) / len(q.evidence)
    entities = {(f.tickers[0] if f.tickers else None, f.fiscal_years[0] if f.fiscal_years else None)
                for f in split_filters(q.filters)}
    in_ctx = {(s.chunk.ticker, s.chunk.fiscal_year) for s in ctx}
    metrics["ctx_coverage"] = sum(
        any((t is None or t == ct) and (y is None or y == cy) for ct, cy in in_ctx) for t, y in entities) / len(entities)
    top = [f"{h.chunk.ticker} FY{h.chunk.fiscal_year} p.{h.chunk.page_start} {h.chunk.section} {h.chunk.chunk_type}"
           for h in result.hits[:5]]
    return PlanRecord(q.id, q.category, metrics, len(result.hits), len(ctx), result.timings_ms.get("total", 0.0), top)


def configs(retriever, k: int) -> dict[str, Callable[[GoldQuestion], SearchResult]]:
    seq = _Sequential(retriever)

    def v0(searcher, kk):
        return lambda q: search_decomposed(searcher, q.retrieval_query, q.filters, k=kk, mode="hybrid_rerank")

    def plan(bonus, kk):
        return lambda q: execute_plan(retriever, make_plan(q.retrieval_query, q.filters, k=kk, section_bonus=bonus))

    return {
        f"v0 decomposition, k={k}, sequential rerank": v0(seq, k),
        f"v0 decomposition, k={k}, batched rerank": v0(retriever, k),
        f"plan quotas, k={k}, no prior": plan(0.0, k),
        f"plan quotas, k={k}, MD&A prior 0.02": plan(0.02, k),
        f"plan quotas, k={k}, MD&A prior 0.05": plan(0.05, k),
        f"plan quotas, k={k}, MD&A prior 0.10": plan(0.10, k),
        "v0 decomposition, k=5, batched rerank": v0(retriever, 5),
        "plan quotas, k=5, MD&A prior 0.05": plan(0.05, 5),
    }


def _mean(values) -> float:
    vals = list(values)
    return statistics.fmean(vals) if vals else float("nan")


def _pct(values: Sequence[float], p: float) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, int(p * len(v)))] if v else float("nan")


def summarize(records: Sequence[PlanRecord]) -> dict[str, float]:
    s = {m: _mean(r.metrics[m] for r in records) for m in ("recall@5", "recall@10", "mrr", "ctx_recall", "ctx_coverage")}
    s["n_ctx"] = _mean(r.n_ctx for r in records)
    s["p50_ms"] = _pct([r.latency_ms for r in records], 0.5)
    s["p95_ms"] = _pct([r.latency_ms for r in records], 0.95)
    multi = [r.latency_ms for r in records if r.category in ("trend", "comparison")]
    s["multi_p50_ms"] = _pct(multi, 0.5)
    s["multi_p95_ms"] = _pct(multi, 0.95)
    return s


def render_report(runs: dict[str, list[PlanRecord]]) -> str:
    f = lambda x: f"{x:.3f}"  # noqa: E731
    n = len(next(iter(runs.values())))
    lines = ["# Retrieval plan evaluation v0", "",
             f"{n} answerable questions, gold filters and gold standalone queries, hybrid_rerank "
             "(bge-reranker-base, 30 candidates per sub-query). ctx = chunks that fit the 3,500-token generation budget.",
             "", "## Configurations", "",
             "| Config | recall@5 | recall@10 | MRR | ctx recall | ctx coverage | ctx chunks | p50 ms | p95 ms | multi-entity p50 / p95 ms |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, recs in runs.items():
        s = summarize(recs)
        lines.append(f"| {name} | {f(s['recall@5'])} | {f(s['recall@10'])} | {f(s['mrr'])} | {f(s['ctx_recall'])} | "
                     f"{f(s['ctx_coverage'])} | {s['n_ctx']:.1f} | {s['p50_ms']:.0f} | {s['p95_ms']:.0f} | "
                     f"{s['multi_p50_ms']:.0f} / {s['multi_p95_ms']:.0f} |")
    cats = sorted({r.category for r in next(iter(runs.values()))})
    for metric in ("recall@5", "ctx_recall", "mrr"):
        lines += ["", f"## {metric} by category", "", "| Config | " + " | ".join(cats) + " |",
                  "|---|" + "---|" * len(cats)]
        for name, recs in runs.items():
            lines.append(f"| {name} | " + " | ".join(
                f(_mean(r.metrics[metric] for r in recs if r.category == c)) for c in cats) + " |")
    names = list(runs)
    base, best = runs[names[0]], runs[names[4]]
    lines += ["", f"## Questions that change: `{names[0]}` → `{names[4]}`", "",
              "| Id | recall@5 | ctx recall | MRR | top 5 after |", "|---|---|---|---|---|"]
    for a, b in zip(base, best):
        deltas = [b.metrics[m] - a.metrics[m] for m in ("recall@5", "ctx_recall", "mrr")]
        if any(abs(d) > 1e-9 for d in deltas):
            lines.append(f"| {a.id} | {a.metrics['recall@5']:.2f} → {b.metrics['recall@5']:.2f} | "
                         f"{a.metrics['ctx_recall']:.2f} → {b.metrics['ctx_recall']:.2f} | "
                         f"{a.metrics['mrr']:.2f} → {b.metrics['mrr']:.2f} | {'; '.join(b.top)} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports" / "plan_v0")
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    from app.retrieval.factory import build_retriever

    retriever = build_retriever()
    retriever.search("warm up", k=1)
    budget = get_settings().context_token_budget
    questions = [q for q in load_golden(args.golden) if q.answerable]
    runs: dict[str, list[PlanRecord]] = {}
    for name, run in configs(retriever, args.k).items():
        runs[name] = [score(q, run(q), budget) for q in questions]
        s = summarize(runs[name])
        print(f"{name}: r@5 {s['recall@5']:.3f} ctx {s['ctx_recall']:.3f} mrr {s['mrr']:.3f} "
              f"p50 {s['p50_ms']:.0f} multi p95 {s['multi_p95_ms']:.0f} ms", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".md").write_text(render_report(runs), encoding="utf-8")
    args.out.with_suffix(".json").write_text(json.dumps(
        {name: {"summary": summarize(recs), "records": [asdict(r) for r in recs]} for name, recs in runs.items()},
        indent=1), encoding="utf-8")
    print(f"Wrote {args.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
