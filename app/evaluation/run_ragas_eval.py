"""RAGAS second opinion on the judged answers: do RAGAS's metrics agree with the LLM judge?

Re-runs the agent (routed by default, the kept v2 config; generation is cached) and checks each answer
equals the judge report's (default `reports/judge_v2_qwen.json`). Every answered, answerable question
is scored by RAGAS `Faithfulness` (against the cited sources, as the judge sees them) and
`FactualCorrectness` against the reference: f1 (RAGAS's score), precision and coverage of the reference's
claims (see `ragas_metrics.py`; coverage is the judge's correctness counterpart). Abstentions and unanswerable questions are not
scored: RAGAS has no notion of a correct abstention, and the judge already scores them by rule.

The report puts RAGAS next to the judge per question and summarises their agreement: mean RAGAS
coverage and f1 per judge grade, rank correlations, and the questions where they disagree.

Zero cost: calls go through `RagasLLM` (cached, rate limited); the default model is Groq
qwen3.8-27b (not the model of any answer, and its own daily quota). A run stops cleanly at the daily
limit; rerun the same command the next day (finished questions come from the cache).

Usage:
    python -m app.evaluation.run_ragas_eval --ids L01 T06 C05     # -> reports/ragas_v0_smoke.*
    python -m app.evaluation.run_ragas_eval                       # -> reports/ragas_v0.{md,json}
"""

import argparse
import json
import logging
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from app.agent.graph import FinRAGAgent
from app.agent.xbrl import XbrlStore
from app.config import PROJECT_ROOT, get_settings
from app.evaluation.build_golden import DEFAULT_PATH as GOLDEN_PATH
from app.evaluation.golden import load_golden
from app.evaluation.run_generation_eval import _mean
from app.generation.llm import LLMError

JUDGE_REPORT = PROJECT_ROOT / "reports" / "judge_v2_qwen.json"
GRADES = ("correct", "partially_correct", "incorrect")
DISAGREE = 0.5  # |RAGAS coverage - judge correctness score| at or above this is listed


@dataclass
class RagasRecord:
    id: str
    category: str
    answer: str
    faithfulness: float | None = None  # RAGAS, vs cited sources
    factual_correctness: float | None = None  # RAGAS f1, vs reference
    fc_precision: float | None = None  # answer claims entailed by the reference
    fc_coverage: float | None = None  # reference claims entailed by the answer
    judge_correctness: str = ""
    judge_correctness_score: float | None = None
    judge_faithfulness: float | None = None
    answer_matches_judge: bool | None = None
    answer_model: str = ""
    calls: int = 0
    tokens: int = 0
    error: str = ""


def spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation with average ranks for ties (judge scores are 3-valued)."""
    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=v.__getitem__)
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    if len(xs) < 3:
        return float("nan")
    try:
        return statistics.correlation(ranks(xs), ranks(ys))
    except statistics.StatisticsError:  # a constant series
        return float("nan")


def _pairs(records: list[RagasRecord], ours: str, theirs: str) -> tuple[list[float], list[float]]:
    rs = [r for r in records if getattr(r, ours) is not None and getattr(r, theirs) is not None]
    return [getattr(r, ours) for r in rs], [getattr(r, theirs) for r in rs]


def summarize(records: list[RagasRecord]) -> dict:
    ok = [r for r in records if not r.error]
    fc = _pairs(ok, "factual_correctness", "judge_correctness_score")
    cov = _pairs(ok, "fc_coverage", "judge_correctness_score")
    fa = _pairs(ok, "faithfulness", "judge_faithfulness")
    return {
        "scored": len(ok),
        "errors": sum(bool(r.error) for r in records),
        "faithfulness": _mean(r.faithfulness for r in ok),
        "factual_correctness": _mean(r.factual_correctness for r in ok),
        "fc_precision": _mean(r.fc_precision for r in ok),
        "fc_coverage": _mean(r.fc_coverage for r in ok),
        "judge_correctness": _mean(r.judge_correctness_score for r in ok),
        "judge_faithfulness": _mean(r.judge_faithfulness for r in ok),
        "by_judge_grade": {g: (sum(r.judge_correctness == g for r in ok),
                               _mean(r.fc_coverage for r in ok if r.judge_correctness == g),
                               _mean(r.factual_correctness for r in ok if r.judge_correctness == g),
                               _mean(r.fc_precision for r in ok if r.judge_correctness == g)) for g in GRADES},
        "spearman_coverage": spearman(*cov),
        "spearman_f1": spearman(*fc),
        "spearman_faithfulness": spearman(*fa),
        "faithfulness_mae": _mean(abs(x - y) for x, y in zip(*fa)),
        "calls": sum(r.calls for r in records),
        "tokens": sum(r.tokens for r in records),
        "answer_mismatches": [r.id for r in records if r.answer_matches_judge is False],
        "answer_models": dict(Counter(r.answer_model for r in records if r.answer_model)),
    }


def _f(v: float | None) -> str:
    return "-" if v is None or v != v else f"{v:.2f}"


def render_report(records: list[RagasRecord], s: dict, title: str, judge_report: str, models: list[str]) -> str:
    lines = [
        f"# RAGAS second opinion: {title}", "",
        f"Generated by `python -m app.evaluation.run_ragas_eval`; answers re-run from cache and compared with "
        f"`{judge_report}`. RAGAS {', '.join(models) or '-'} through FinRAG's cached `LLM` layer.", "",
        f"- Answers by: {', '.join(f'{k} ({v})' for k, v in s['answer_models'].items()) or '-'}",
        f"- Scored: {s['scored']} answered, answerable questions; errors: {s['errors']}; "
        f"RAGAS calls {s['calls']}, uncached tokens {s['tokens']:,}", "",
        "## Agreement with the judge", "",
        "| | RAGAS | Judge |", "|---|---|---|",
        f"| Correctness: RAGAS reference coverage / judge grade | {s['fc_coverage']:.3f} | "
        f"{s['judge_correctness']:.3f} |",
        f"| RAGAS factual correctness f1 (precision {s['fc_precision']:.3f}) | {s['factual_correctness']:.3f} | |",
        f"| Faithfulness to cited sources | {s['faithfulness']:.3f} | {s['judge_faithfulness']:.3f} |",
        f"| Spearman vs judge correctness: coverage / f1 | {s['spearman_coverage']:.2f} / {s['spearman_f1']:.2f} | |",
        f"| Spearman vs judge faithfulness (MAE {s['faithfulness_mae']:.2f}) | {s['spearman_faithfulness']:.2f} | |", "",
        "| Judge grade | n | RAGAS coverage | RAGAS f1 | RAGAS precision |", "|---|---|---|---|---|",
    ]
    lines += [f"| {g} | {n} | {_f(c)} | {_f(f1)} | {_f(p)} |" for g, (n, c, f1, p) in s["by_judge_grade"].items()]

    lines += ["", "## By category", "", "| Category | n | RAGAS coverage | RAGAS f1 | Judge correctness | "
              "RAGAS faithfulness | Judge faithfulness |", "|---|---|---|---|---|---|---|"]
    for cat in sorted({r.category for r in records}):
        rs = [r for r in records if r.category == cat and not r.error]
        lines.append(f"| {cat} | {len(rs)} | {_f(_mean(r.fc_coverage for r in rs))} | "
                     f"{_f(_mean(r.factual_correctness for r in rs))} | "
                     f"{_f(_mean(r.judge_correctness_score for r in rs))} | {_f(_mean(r.faithfulness for r in rs))} | "
                     f"{_f(_mean(r.judge_faithfulness for r in rs))} |")

    disagree = [r for r in records if r.fc_coverage is not None and r.judge_correctness_score is not None
                and abs(r.fc_coverage - r.judge_correctness_score) >= DISAGREE]
    lines += ["", f"## Correctness disagreements (|RAGAS coverage - judge| >= {DISAGREE}): {len(disagree)}", "",
              "| Id | Judge | RAGAS coverage | Answer |", "|---|---|---|---|"]
    lines += [f"| {r.id} | {r.judge_correctness} | {_f(r.fc_coverage)} | "
              f"{r.answer[:220].replace('|', '/').replace(chr(10), ' ')} |" for r in disagree]

    lines += ["", "## Per question", "", "| Id | Category | RAGAS coverage | RAGAS f1 | RAGAS precision | Judge | "
              "RAGAS faith. | Judge faith. | Calls |", "|---|---|---|---|---|---|---|---|---|"]
    lines += [f"| {r.id} | {r.category} | {_f(r.fc_coverage)} | {_f(r.factual_correctness)} | {_f(r.fc_precision)} | "
              f"{r.judge_correctness or '-'} | "
              f"{_f(r.faithfulness)} | {_f(r.judge_faithfulness)} | {r.error[:80] or r.calls} |" for r in records]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    parser.add_argument("--ids", nargs="+", help="only these question ids")
    parser.add_argument("--out", type=Path, help="default reports/ragas_v0 (ragas_v0_smoke with --ids)")
    parser.add_argument("--judge-report", type=Path, default=JUDGE_REPORT)
    parser.add_argument("--providers", default="groq", help="RAGAS LLM providers")
    parser.add_argument("--model", default="qwen/qwen3.8-27b", help="Groq model for RAGAS (own daily quota)")
    parser.add_argument("--no-route", action="store_true", help="answers from the unrouted agent (v1 config)")
    args = parser.parse_args()
    args.out = args.out or PROJECT_ROOT / "reports" / ("ragas_v0_smoke" if args.ids else "ragas_v0")
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app.generation.llm").setLevel(logging.INFO)

    from app.evaluation.ragas_metrics import RagasScorer
    from app.generation.llm import build_llm
    from app.retrieval.factory import build_retriever

    settings = get_settings()
    routed_llm = None if args.no_route else build_llm(settings.model_copy(update={"llm_providers": "groq,ollama"}))
    agent = FinRAGAgent(build_retriever(settings), build_llm(settings), xbrl=XbrlStore.from_settings(),
                        token_budget=settings.context_token_budget, routed_llm=routed_llm)
    scorer = RagasScorer(build_llm(settings.model_copy(update={"llm_providers": args.providers,
                                                               "groq_model": args.model})))
    judged = {r["id"]: r for r in json.loads(args.judge_report.read_text())["records"]}
    questions = [q for q in load_golden(args.golden) if q.answerable and (not args.ids or q.id in args.ids)]

    records: list[RagasRecord] = []
    for i, q in enumerate(questions, 1):
        start = time.perf_counter()
        r = agent.run(q.question, q.history).result
        if r.abstained:
            print(f"[{i}/{len(questions)}] {q.id} abstained, not scored", flush=True)
            continue
        j = judged.get(q.id, {})
        rec = RagasRecord(q.id, q.category, r.answer, answer_model=r.model,
                          judge_correctness=j.get("correctness", "") if j.get("judged") else "",
                          judge_correctness_score=j.get("correctness_score") if j.get("judged") else None,
                          judge_faithfulness=j.get("faithfulness"),
                          answer_matches_judge=j.get("answer") == r.answer if j else None)
        before = (scorer.llm.stats.calls, scorer.llm.stats.tokens)
        try:
            scores = scorer.score(q.retrieval_query, r.answer, q.reference_answer,
                                  [s for s in r.sources if s.id in r.cited_source_ids])
        except LLMError as e:
            rec.error = str(e)[:300]
        else:
            rec.faithfulness, rec.factual_correctness = scores.faithfulness, scores.factual_correctness
            rec.fc_precision, rec.fc_coverage = scores.fc_precision, scores.fc_coverage
        rec.calls = scorer.llm.stats.calls - before[0]
        rec.tokens = scorer.llm.stats.tokens - before[1]
        records.append(rec)
        print(f"[{i}/{len(questions)}] {q.id} " + (f"ERROR {rec.error[:120]}" if rec.error else
              f"coverage {_f(rec.fc_coverage)} f1 {_f(rec.factual_correctness)} (judge {rec.judge_correctness or '-'}), "
              f"faith {_f(rec.faithfulness)} "
              f"(judge {_f(rec.judge_faithfulness)}), {rec.calls} calls, {rec.tokens:,} tokens") +
              f" ({time.perf_counter() - start:.1f} s)", flush=True)
        if rec.error and "daily limit" in rec.error:
            print("RAGAS provider hit its daily limit; stopping (rerun later: finished calls are cached).")
            break

    summary = summarize(records)
    models = sorted(scorer.llm.stats.models)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".md").write_text(
        render_report(records, summary, args.out.stem, args.judge_report.name, models), encoding="utf-8")
    args.out.with_suffix(".json").write_text(json.dumps({"summary": summary, "models": models,
                                                         "records": [asdict(r) for r in records]},
                                                        indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(f"Wrote {args.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
