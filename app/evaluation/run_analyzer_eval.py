"""Query-analyzer evaluation: filters it extracts vs the gold filters, and what that costs retrieval.

Phase 4/5 evals hand the retriever the gold filters and, for follow-ups, the gold standalone
rewrite. This eval replaces both with the analyzer's output and measures:
- filter accuracy on answerable questions: tickers/years/sections exact, and *compatible*
  (no filter, or a superset of gold: retrieval can still reach the gold pages)
- scope: unanswerable questions refused before retrieval (years outside the corpus), and
  answerable questions wrongly refused
- retrieval (hybrid_rerank, k=10, decomposition when filters span several entities) with gold
  vs analyzer filters/queries: recall@5, recall@10, MRR

Usage:
    python -m app.evaluation.run_analyzer_eval                 # rules only (no LLM)
    python -m app.evaluation.run_analyzer_eval --rewrite       # + LLM rewrite of follow-ups
    python -m app.evaluation.run_analyzer_eval --no-retrieval  # filter accuracy only (instant)
"""

import argparse
import json
import logging
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.agent.analyze import QueryAnalysis, QueryAnalyzer
from app.config import PROJECT_ROOT
from app.evaluation.build_golden import DEFAULT_PATH as GOLDEN_PATH
from app.evaluation.golden import GoldQuestion, load_golden
from app.evaluation.metrics import RetrievedPage, score_ranking
from app.retrieval.decompose import search_decomposed, split_filters
from app.retrieval.types import SearchFilters

KS = (1, 5, 10)


def _compatible(pred: tuple | None, gold: tuple | None) -> bool:
    """No predicted constraint, or one that still includes every gold value."""
    return pred is None or (gold is not None and set(gold) <= set(pred))


def _exact(pred: tuple | None, gold: tuple | None) -> bool:
    return set(pred or ()) == set(gold or ())


@dataclass
class AnalyzerRecord:
    id: str
    category: str
    answerable: bool
    question: str
    standalone_query: str
    scope: str
    reason: str
    pred: dict
    gold: dict
    checks: dict[str, bool]
    retrieval: dict[str, dict[str, float]] = field(default_factory=dict)  # "gold" / "analyzer" -> metrics


def check_filters(a: QueryAnalysis, q: GoldQuestion) -> dict[str, bool]:
    p, g = a.filters, q.filters
    checks = {
        "tickers_exact": _exact(p.tickers, g.tickers),
        "years_exact": _exact(p.fiscal_years, g.fiscal_years),
        "sections_exact": _exact(p.sections, g.sections),
        "tickers_ok": _compatible(p.tickers, g.tickers),
        "years_ok": _compatible(p.fiscal_years, g.fiscal_years),
        "sections_ok": _compatible(p.sections, g.sections),
    }
    checks["all_exact"] = checks["tickers_exact"] and checks["years_exact"] and checks["sections_exact"]
    checks["all_ok"] = checks["tickers_ok"] and checks["years_ok"] and checks["sections_ok"]
    return checks


def _as_dict(f: SearchFilters) -> dict:
    return {"tickers": list(f.tickers or []), "fiscal_years": list(f.fiscal_years or []), "sections": list(f.sections or [])}


def retrieve_metrics(retriever, query: str, filters: SearchFilters, q: GoldQuestion, k: int = 10) -> dict[str, float]:
    if len(split_filters(filters)) > 1:
        result = search_decomposed(retriever, query, filters, k=k, mode="hybrid_rerank")
    else:
        result = retriever.search(query, filters, k=k, mode="hybrid_rerank")
    ranking = [RetrievedPage(h.chunk.ticker, h.chunk.fiscal_year, h.chunk.page_start, h.chunk.page_end) for h in result.hits]
    return {**score_ranking(ranking, q.evidence, KS), "latency_ms": result.timings_ms.get("total", 0.0)}


def _mean(values) -> float:
    vals = [float(v) for v in values]
    return statistics.fmean(vals) if vals else float("nan")


def summarize(records: Sequence[AnalyzerRecord]) -> dict:
    ans = [r for r in records if r.answerable]
    una = [r for r in records if not r.answerable]
    s = {name: _mean(r.checks[name] for r in ans) for name in ans[0].checks} if ans else {}
    s["refused_unanswerable"] = sum(r.scope != "in_corpus" for r in una)
    s["unanswerable"] = len(una)
    s["refused_answerable"] = sum(r.scope != "in_corpus" for r in ans)
    for config in ("gold", "analyzer"):
        rs = [r.retrieval[config] for r in ans if config in r.retrieval]
        for m in ("recall@5", "recall@10", "mrr"):
            s[f"{config}_{m}"] = _mean(x[m] for x in rs) if rs else float("nan")
    return s


def render_report(records: Sequence[AnalyzerRecord], rewrite_model: str) -> str:
    s = summarize(records)
    f = lambda x: "n/a" if x != x else f"{x:.3f}"  # noqa: E731 (nan-safe)
    ans = [r for r in records if r.answerable]
    lines = [
        "# Query analyzer evaluation v0",
        "",
        f"Rules for companies/years/sections; follow-up rewrite: {rewrite_model}. "
        f"{len(ans)} answerable + {s['unanswerable']} unanswerable questions.",
        "",
        "## Filters vs gold (answerable questions)",
        "",
        "| Field | Exact | Compatible (none or superset of gold) |",
        "|---|---|---|",
        f"| Tickers | {f(s['tickers_exact'])} | {f(s['tickers_ok'])} |",
        f"| Fiscal years | {f(s['years_exact'])} | {f(s['years_ok'])} |",
        f"| Sections | {f(s['sections_exact'])} | {f(s['sections_ok'])} |",
        f"| All | {f(s['all_exact'])} | {f(s['all_ok'])} |",
        "",
        f"Scope: {s['refused_unanswerable']}/{s['unanswerable']} unanswerable questions refused before retrieval "
        f"(years outside the corpus); {s['refused_answerable']} answerable questions wrongly refused.",
    ]
    if any(r.retrieval for r in ans):
        lines += ["", "## Retrieval: gold vs analyzer filters and queries (hybrid_rerank, k=10)", "",
                  "| Category | n | Gold recall@5 | Analyzer recall@5 | Gold recall@10 | Analyzer recall@10 | Gold MRR | Analyzer MRR |",
                  "|---|---|---|---|---|---|---|---|"]
        for cat in [None, *sorted({r.category for r in ans})]:
            rs = [r for r in ans if cat in (None, r.category) and r.retrieval]
            m = lambda c, k: f(_mean(r.retrieval[c][k] for r in rs))  # noqa: E731
            lines.append(f"| {cat or '**all**'} | {len(rs)} | {m('gold', 'recall@5')} | {m('analyzer', 'recall@5')} | "
                         f"{m('gold', 'recall@10')} | {m('analyzer', 'recall@10')} | {m('gold', 'mrr')} | {m('analyzer', 'mrr')} |")
    lines += ["", "## Differences from gold", "", "| Id | Predicted | Gold | Question / rewrite |", "|---|---|---|---|"]
    for r in records:
        if r.answerable and r.checks["all_exact"] and r.standalone_query == r.question:
            continue
        if not r.answerable and r.scope == "in_corpus":
            continue
        pred = "refused: " + r.reason if r.scope != "in_corpus" else json.dumps(r.pred)
        text = r.question if r.standalone_query == r.question else f"{r.question} → {r.standalone_query}"
        lines.append(f"| {r.id} | {pred} | {json.dumps(r.gold)} | {text.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports" / "analyzer_v0")
    parser.add_argument("--rewrite", action="store_true", help="rewrite follow-ups with the LLM (LLM_PROVIDERS)")
    parser.add_argument("--no-retrieval", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    llm = None
    if args.rewrite:
        from app.generation.llm import build_llm
        llm = build_llm()
    analyzer = QueryAnalyzer(llm)
    retriever = None
    if not args.no_retrieval:
        from app.retrieval.factory import build_retriever
        retriever = build_retriever()

    records: list[AnalyzerRecord] = []
    models: set[str] = set()
    for q in load_golden(args.golden):
        a = analyzer.analyze(q.question, q.history)
        rec = AnalyzerRecord(q.id, q.category, q.answerable, q.question, a.standalone_query, a.scope, a.reason,
                             _as_dict(a.filters), _as_dict(q.filters), check_filters(a, q))
        if retriever and q.answerable:
            rec.retrieval["gold"] = retrieve_metrics(retriever, q.retrieval_query, q.filters, q)
            rec.retrieval["analyzer"] = (retrieve_metrics(retriever, a.standalone_query, a.filters, q) if a.answerable_scope
                                         else {"recall@1": 0.0, "recall@5": 0.0, "recall@10": 0.0, "mrr": 0.0})
        records.append(rec)
        print(f"{q.id} {'OK ' if rec.checks['all_ok'] else 'BAD'} {a.scope} {rec.pred}"
              + (f" r@5 {rec.retrieval['gold']['recall@5']:.2f}->{rec.retrieval['analyzer']['recall@5']:.2f}" if rec.retrieval else ""),
              flush=True)

    if llm:
        models = {f"{p.name} {getattr(p, 'model', '')}".strip() for p in llm.providers}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".md").write_text(render_report(records, ", ".join(sorted(models)) or "none (rules only)"),
                                           encoding="utf-8")
    args.out.with_suffix(".json").write_text(
        json.dumps({"summary": summarize(records), "records": [asdict(r) for r in records]}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(json.dumps(summarize(records), indent=1))
    print(f"Wrote {args.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
