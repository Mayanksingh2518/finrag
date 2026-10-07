"""Generation evaluation v0: grounded answers on the golden set.

Answerable questions get the gold filters (what the Phase 6 analyzer should extract) and
automatic decomposition; unanswerable ones get no filters. Metrics per question:
- abstained, and whether that was right (unanswerable) or a false abstention
- citation_hit: a verified citation lands on a gold evidence page
- evidence_recall: fraction of gold evidence items covered by verified citations
- claim_support: fraction of the answer's claims that pass the citation verifier
- figure_recall: fraction of the reference answer's figures that appear in the answer
  (same unit-aware matching as the verifier; questions without figures are skipped)

Every LLM call is cached, so reruns are free; the first run is paced by Groq's free tier.

Usage:
    python -m app.evaluation.run_generation_eval            # -> reports/generation_v0.{md,json}
    python -m app.evaluation.run_generation_eval --limit 5  # quick check
"""

import argparse
import json
import logging
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import PROJECT_ROOT, get_settings
from app.evaluation.build_golden import DEFAULT_PATH as GOLDEN_PATH
from app.evaluation.golden import GoldQuestion, load_golden
from app.evaluation.metrics import RetrievedPage, covered_items
from app.generation.answer import AnswerResult, Answerer
from app.generation.llm import LLMError
from app.generation.verify import _matches, extract_numbers
from app.retrieval.types import SearchFilters


@dataclass
class GenerationRecord:
    id: str
    category: str
    answerable: bool
    abstained: bool
    answer: str
    abstain_reason: str
    confidence: str
    citation_hit: float | None  # None for unanswerable
    evidence_recall: float | None
    claim_support: float | None  # None when there are no claims
    figure_recall: float | None  # None when the reference has no figures or the question is unanswerable
    claims: int
    sources: int
    cited: list[str]
    provider: str
    cached: bool
    latency_ms: dict[str, float]
    tokens: dict[str, int]
    error: str = ""
    model: str = ""


def figure_recall(reference: str, answer: str) -> float | None:
    ref = extract_numbers(reference)
    if not ref:
        return None
    got = extract_numbers(answer)
    return sum(any(_matches(a, r) or _matches(r, a) for a in got) for r in ref) / len(ref)


def score(q: GoldQuestion, r: AnswerResult) -> GenerationRecord:
    by_id = {s.id: s for s in r.sources}
    cited_pages = [RetrievedPage(by_id[s].chunk.ticker, by_id[s].chunk.fiscal_year, by_id[s].chunk.page_start,
                                 by_id[s].chunk.page_end) for s in r.cited_source_ids if s in by_id]
    covered = set().union(*(covered_items(p, q.evidence) for p in cited_pages)) if cited_pages and q.answerable else set()
    return GenerationRecord(
        id=q.id, category=q.category, answerable=q.answerable, abstained=r.abstained,
        answer=r.answer, abstain_reason=r.abstain_reason, confidence=r.confidence,
        citation_hit=float(bool(covered)) if q.answerable else None,
        evidence_recall=len(covered) / len(q.evidence) if q.answerable else None,
        claim_support=sum(c.supported for c in r.claims) / len(r.claims) if r.claims else None,
        figure_recall=figure_recall(q.reference_answer, r.answer) if q.answerable else None,
        claims=len(r.claims), sources=len(r.sources), cited=[by_id[s].citation for s in r.cited_source_ids if s in by_id],
        provider=r.provider, cached=r.cached, latency_ms=r.timings_ms, tokens=r.usage, model=r.model,
    )


def _mean(values) -> float:
    vals = [v for v in values if v is not None]
    return statistics.fmean(vals) if vals else float("nan")


def summarize(records: list[GenerationRecord]) -> dict:
    ans = [r for r in records if r.answerable]
    una = [r for r in records if not r.answerable]
    abstain_tp = sum(r.abstained for r in una)
    abstained_total = sum(r.abstained for r in records)
    return {
        "questions": len(records),
        "errors": sum(bool(r.error) for r in records),
        "abstention_recall": abstain_tp / len(una) if una else float("nan"),  # unanswerable correctly refused
        "abstention_precision": abstain_tp / abstained_total if abstained_total else float("nan"),
        "false_abstention_rate": _mean(float(r.abstained) for r in ans),
        "citation_hit": _mean(r.citation_hit for r in ans),
        "evidence_recall": _mean(r.evidence_recall for r in ans),
        "claim_support": _mean(r.claim_support for r in ans if not r.abstained),
        "figure_recall": _mean(r.figure_recall for r in ans),
        "confidence": dict(Counter(r.confidence for r in records)),
        "providers": dict(Counter(r.provider for r in records)),
        "models": dict(Counter(r.model for r in records if r.model)),
        "llm_p50_ms": _pct([r.latency_ms.get("llm") for r in records if not r.cached], 0.5),
        "llm_p95_ms": _pct([r.latency_ms.get("llm") for r in records if not r.cached], 0.95),
        "retrieval_p50_ms": _pct([r.latency_ms.get("retrieval") for r in records], 0.5),
        "total_tokens": sum(r.tokens.get("prompt", 0) + r.tokens.get("completion", 0) for r in records),
    }


def _pct(values, p: float) -> float:
    vals = sorted(v for v in values if v is not None)
    return vals[min(len(vals) - 1, int(p * len(vals)))] if vals else float("nan")


def render_report(records: list[GenerationRecord], budget: int) -> str:
    s = summarize(records)
    cats = sorted({r.category for r in records})
    f = lambda x: "n/a" if x != x else f"{x:.3f}"  # noqa: E731 (nan-safe)
    lines = [
        "# Generation evaluation v0",
        "",
        f"Models: {', '.join(f'`{m}` ({n})' for m, n in s['models'].items()) or 'none'} (providers: {s['providers']}). Retrieval: hybrid_rerank, k=10, gold filters, "
        f"automatic per-entity decomposition; source budget {budget} tokens. {s['questions']} questions, "
        f"{s['errors']} errors.",
        "",
        "| Metric | Value | Meaning |",
        "|---|---|---|",
        f"| Abstention recall | {f(s['abstention_recall'])} | unanswerable questions correctly refused |",
        f"| Abstention precision | {f(s['abstention_precision'])} | refusals that were on unanswerable questions |",
        f"| False abstention rate | {f(s['false_abstention_rate'])} | answerable questions refused |",
        f"| Citation hit | {f(s['citation_hit'])} | a verified citation lands on a gold page |",
        f"| Evidence recall | {f(s['evidence_recall'])} | gold evidence items covered by verified citations |",
        f"| Claim support | {f(s['claim_support'])} | claims passing the citation/number verifier |",
        f"| Figure recall | {f(s['figure_recall'])} | reference-answer figures present in the answer |",
        f"| LLM latency | p50 {s['llm_p50_ms']:.0f} ms, p95 {s['llm_p95_ms']:.0f} ms | provider call only (excludes free-tier rate-limit waits) |",
        f"| Retrieval latency | p50 {s['retrieval_p50_ms']:.0f} ms | hybrid + rerank (+ decomposition) |",
        f"| Tokens | {s['total_tokens']:,} | prompt + completion, whole run |",
        "",
        f"Confidence distribution: {s['confidence']}",
        "",
        "## By category",
        "",
        "| Category | n | Abstained | Citation hit | Evidence recall | Claim support | Figure recall |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in cats:
        rs = [r for r in records if r.category == c]
        lines.append(f"| {c} | {len(rs)} | {sum(r.abstained for r in rs)} | {f(_mean(r.citation_hit for r in rs))} | "
                     f"{f(_mean(r.evidence_recall for r in rs))} | {f(_mean(r.claim_support for r in rs if not r.abstained))} | "
                     f"{f(_mean(r.figure_recall for r in rs))} |")
    misses = [r for r in records if r.error or (r.answerable and (r.abstained or not r.citation_hit or (r.figure_recall or 1) < 1))
              or (not r.answerable and not r.abstained)]
    lines += ["", "## Questions to review", "", "| Id | Issue | Answer / reason |", "|---|---|---|"]
    for r in misses:
        issue = ("error" if r.error else "answered unanswerable" if not r.answerable else "false abstention" if r.abstained
                 else "citation miss" if not r.citation_hit else f"figures {r.figure_recall:.2f}")
        text = (r.error or r.abstain_reason or r.answer).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r.id} | {issue} | {text[:220]} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports" / "generation_v0")
    parser.add_argument("--limit", type=int, help="only the first N questions")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app.generation.llm").setLevel(logging.INFO)

    from app.generation.llm import build_llm
    from app.retrieval.factory import build_retriever

    settings = get_settings()
    answerer = Answerer(build_retriever(settings), build_llm(settings), token_budget=settings.context_token_budget)
    questions = load_golden(args.golden)[: args.limit]
    records: list[GenerationRecord] = []
    for i, q in enumerate(questions, 1):
        start = time.perf_counter()
        try:
            filters = q.filters if q.answerable else SearchFilters()
            rec = score(q, answerer.answer(q.retrieval_query, filters))
        except LLMError as e:
            rec = GenerationRecord(q.id, q.category, q.answerable, False, "", "", "none", None, None, None, None,
                                   0, 0, [], "", False, {}, {}, error=str(e)[:300])
        records.append(rec)
        status = "ERROR" if rec.error else "abstain" if rec.abstained else f"cite={rec.citation_hit} fig={rec.figure_recall}"
        print(f"[{i}/{len(questions)}] {q.id} {status} ({time.perf_counter() - start:.1f} s{', cached' if rec.cached else ''})",
              flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".md").write_text(render_report(records, settings.context_token_budget),
                                           encoding="utf-8")
    args.out.with_suffix(".json").write_text(
        json.dumps({"summary": summarize(records), "records": [asdict(r) for r in records]}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(json.dumps(summarize(records), indent=1))
    print(f"Wrote {args.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
