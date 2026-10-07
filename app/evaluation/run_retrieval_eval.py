"""Retrieval evaluation v0: every mode x {gold filters, no filters}, plus reranker ablations.

"Filtered" runs give the retriever the filters the Phase 6 query analyzer should
extract (company, fiscal year, sometimes section); "unfiltered" runs measure how well
retrieval finds the right filing on its own. Unanswerable questions have no gold
evidence and are skipped here (they are scored on abstention in Phase 5).

Usage:
    python -m app.evaluation.run_retrieval_eval                  # full run + ablations
    python -m app.evaluation.run_retrieval_eval --no-ablations   # modes only
Writes reports/retrieval_v0.md and reports/retrieval_v0.json.
"""

import argparse
import json
import logging
import statistics
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from app.config import PROJECT_ROOT, get_settings
from app.evaluation.build_golden import DEFAULT_PATH as GOLDEN_PATH
from app.evaluation.golden import GoldQuestion, load_golden
from app.evaluation.metrics import RetrievedPage, score_ranking
from app.retrieval.decompose import search_decomposed
from app.retrieval.types import SEARCH_MODES, SearchFilters, SearchMode, SearchResult

KS = (1, 3, 5, 10)
HEADLINE = ("recall@1", "recall@5", "recall@10", "hit@5", "mrr", "ndcg@10")


class Searcher(Protocol):
    def search(self, query: str, filters: SearchFilters | None = None, k: int = 8, mode: SearchMode = ...) -> SearchResult: ...


@dataclass
class QuestionResult:
    id: str
    category: str
    metrics: dict[str, float]
    timings_ms: dict[str, float]
    top: list[str]  # "TICKER FY p.N section type" of the top 5, for failure analysis


@dataclass
class RunResult:
    name: str
    mode: str
    filtered: bool
    questions: list[QuestionResult] = field(default_factory=list)

    def mean(self, metric: str, category: str | None = None) -> float:
        values = [q.metrics[metric] for q in self.questions if category in (None, q.category)]
        return statistics.fmean(values) if values else float("nan")

    def latency(self, stage: str = "total", pct: float = 0.5) -> float:
        values = sorted(q.timings_ms.get(stage, 0.0) for q in self.questions)
        return values[min(len(values) - 1, int(pct * len(values)))] if values else float("nan")


def evaluate(searcher: Searcher, questions: Sequence[GoldQuestion], mode: SearchMode, filtered: bool,
             name: str | None = None, k: int = max(KS), decompose: bool = False) -> RunResult:
    """Score one retrieval configuration; `decompose` fans out over (ticker, year) pairs of the gold filters."""
    run = RunResult(name or mode, mode, filtered)
    for q in questions:
        if not q.answerable:
            continue
        filters = q.filters if filtered else SearchFilters()
        if decompose:
            result = search_decomposed(searcher, q.retrieval_query, filters, k=k, mode=mode)
        else:
            result = searcher.search(q.retrieval_query, filters, k=k, mode=mode)
        ranking = [RetrievedPage(h.chunk.ticker, h.chunk.fiscal_year, h.chunk.page_start, h.chunk.page_end) for h in result.hits]
        top = [f"{h.chunk.ticker} FY{h.chunk.fiscal_year} p.{h.chunk.page_start} {h.chunk.section} {h.chunk.chunk_type}"
               for h in result.hits[:5]]
        run.questions.append(QuestionResult(q.id, q.category, score_ranking(ranking, q.evidence, KS), result.timings_ms, top))
    return run


def _fmt(x: float) -> str:
    return f"{x:.3f}"


def render_report(runs: Sequence[RunResult], ablations: Sequence[RunResult], questions: Sequence[GoldQuestion]) -> str:
    answerable = [q for q in questions if q.answerable]
    categories = sorted({q.category for q in answerable})
    lines = [
        "# Retrieval evaluation v0",
        "",
        f"Golden set: {len(questions)} questions ({len(answerable)} answerable, "
        f"{len(questions) - len(answerable)} unanswerable, skipped here), "
        f"{sum(len(q.evidence) for q in answerable)} gold evidence items. "
        "Relevance is page-level: a chunk counts if it is from the gold filing and its pages overlap a gold page. "
        "Recall@k is the fraction of a question's evidence items (e.g. one per year in a trend) found in the top k.",
        "",
        "## Modes",
        "",
        "`+ decomposition` runs one sub-search per (company, fiscal year) in the gold filters and "
        "merges them round-robin (a preview of the Phase 6 query decomposition).",
        "",
        "| Mode | Filters | " + " | ".join(HEADLINE) + " | p50 ms | p95 ms |",
        "|---|---|" + "---|" * (len(HEADLINE) + 2),
    ]
    for r in runs:
        lines.append(f"| {r.name} | {'gold' if r.filtered else 'none'} | "
                     + " | ".join(_fmt(r.mean(m)) for m in HEADLINE)
                     + f" | {r.latency(pct=0.5):.0f} | {r.latency(pct=0.95):.0f} |")
    for metric in ("recall@5", "mrr"):
        lines += ["", f"## {metric} by category", "",
                  "| Mode | Filters | " + " | ".join(categories) + " |", "|---|---|" + "---|" * len(categories)]
        for r in runs:
            lines.append(f"| {r.name} | {'gold' if r.filtered else 'none'} | "
                         + " | ".join(_fmt(r.mean(metric, c)) for c in categories) + " |")
    if ablations:
        lines += ["", "## Reranker ablations (hybrid candidates, gold filters)", "",
                  "| Config | " + " | ".join(HEADLINE) + " | rerank p50 ms | rerank p95 ms |",
                  "|---|" + "---|" * (len(HEADLINE) + 2)]
        for r in ablations:
            lines.append(f"| {r.name} | " + " | ".join(_fmt(r.mean(m)) for m in HEADLINE)
                         + f" | {r.latency('rerank', 0.5):.0f} | {r.latency('rerank', 0.95):.0f} |")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class RerankerConfig:
    name: str
    model: str
    max_length: int = 512
    candidates: int = 30


ABLATIONS = (
    RerankerConfig("bge-reranker-base, 30 cand, len 512 (default)", "BAAI/bge-reranker-base"),
    RerankerConfig("bge-reranker-base, 30 cand, len 384", "BAAI/bge-reranker-base", max_length=384),
    RerankerConfig("bge-reranker-base, 50 cand, len 512", "BAAI/bge-reranker-base", candidates=50),
    RerankerConfig("ms-marco-MiniLM-L-6-v2, 30 cand, len 512", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
    RerankerConfig("ms-marco-MiniLM-L-6-v2, 50 cand, len 512", "cross-encoder/ms-marco-MiniLM-L-6-v2", candidates=50),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports" / "retrieval_v0")
    parser.add_argument("--no-ablations", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    from app.reranking.cross_encoder import CrossEncoderReranker
    from app.retrieval.factory import build_retriever

    settings = get_settings()
    questions = load_golden(args.golden)
    retriever = build_retriever(settings)
    retriever.search("warm up", k=1)

    runs: list[RunResult] = []
    for filtered in (True, False):
        for mode in SEARCH_MODES:
            start = time.perf_counter()
            runs.append(evaluate(retriever, questions, mode, filtered))
            print(f"{mode:<14} filters={'gold' if filtered else 'none'}: recall@5 {runs[-1].mean('recall@5'):.3f} "
                  f"mrr {runs[-1].mean('mrr'):.3f} ({time.perf_counter() - start:.0f} s)", flush=True)
        if filtered:
            for mode in ("hybrid", "hybrid_rerank"):
                runs.append(evaluate(retriever, questions, mode, True, name=f"{mode} + decomposition", decompose=True))
                print(f"{runs[-1].name}: recall@5 {runs[-1].mean('recall@5'):.3f} mrr {runs[-1].mean('mrr'):.3f}", flush=True)

    ablations: list[RunResult] = []
    if not args.no_ablations:
        for cfg in ABLATIONS:
            current = retriever.reranker
            if (getattr(current, "model_name", None), getattr(current, "max_length", None)) != (cfg.model, cfg.max_length):
                retriever.reranker = CrossEncoderReranker(cfg.model, device=settings.device, max_length=cfg.max_length)
                retriever.search("warm up", k=1)
            retriever.rerank_candidates = cfg.candidates
            ablations.append(evaluate(retriever, questions, "hybrid_rerank", True, name=cfg.name))
            print(f"{cfg.name}: recall@5 {ablations[-1].mean('recall@5'):.3f} mrr {ablations[-1].mean('mrr'):.3f}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".md").write_text(render_report(runs, ablations, questions), encoding="utf-8")
    args.out.with_suffix(".json").write_text(
        json.dumps({"runs": [asdict(r) for r in runs], "ablations": [asdict(r) for r in ablations]}, indent=1),
        encoding="utf-8")
    print(f"Wrote {args.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
