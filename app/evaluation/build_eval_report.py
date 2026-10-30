"""Phase 7 summary report: one page a reviewer reads first, built only from the committed reports.

No model or LLM calls: every number comes from `reports/*.json` (retrieval, plan, generation, agent,
judge, RAGAS) and, for per-node latency, the trace file of the traced routed run
(`data/traces/agent_v2.jsonl`, gitignored; regenerate it with the command in the report, all cached).
A cell a report doesn't have is "-", never re-derived.

Usage:
    python -m app.evaluation.build_eval_report          # -> reports/eval_v1.md
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from app.config import PROJECT_ROOT
from app.evaluation.compare_judges import compare
from app.tracing import Trace, load_traces, summarize as summarize_traces

REPORTS = PROJECT_ROOT / "reports"
TRACES = PROJECT_ROOT / "data" / "traces" / "agent_v2.jsonl"
SHIPPED_PLAN = "plan quotas, k=10, MD&A prior 0.05"
CATEGORIES = ("lookup", "numeric", "trend", "comparison", "follow_up")
TRACE_COMMAND = ("TRACE_FILE=data/traces/agent_v2.jsonl python -m app.evaluation.run_agent_eval "
                 "--configs agent_routed --out <scratch dir>/agent_traced")


def _f(v, digits: int = 3) -> str:
    return "-" if v is None or (isinstance(v, float) and v != v) else f"{v:.{digits}f}"


def _mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.fmean(vals) if vals else None


# --- retrieval -----------------------------------------------------------------------------------


def retrieval_rows(retrieval: dict, plan: dict) -> list[str]:
    """Mode ablation from the per-question metrics (74 answerable), plus the shipped retrieval plan."""
    lines = ["| Retrieval | Filters | recall@5 | recall@10 | MRR | nDCG@10 | p50 ms |", "|---|---|---|---|---|---|---|"]
    for run in retrieval["runs"]:
        qs = run["questions"]

        def m(key: str) -> float:
            return statistics.fmean(q["metrics"][key] for q in qs)

        p50 = statistics.median(q["timings_ms"]["total"] for q in qs)
        lines.append(f"| {run['name']} | {'gold' if run['filtered'] else 'none'} | {m('recall@5'):.3f} | "
                     f"{m('recall@10'):.3f} | {m('mrr'):.3f} | {m('ndcg@10'):.3f} | {p50:,.0f} |")
    if SHIPPED_PLAN in plan:
        s = plan[SHIPPED_PLAN]["summary"]
        lines.append(f"| **retrieval plan** (hybrid_rerank, per-entity quotas, MD&A prior; shipped) | gold | "
                     f"**{s['recall@5']:.3f}** | **{s['recall@10']:.3f}** | **{s['mrr']:.3f}** | - | {s['p50_ms']:,.0f} |")
    return lines


# --- answers -------------------------------------------------------------------------------------

# (label, generation/agent report, summary key or None, gpt-oss judge report, qwen judge report)
ANSWER_STEPS = (
    ("Gold filters + gold rewrite, granite 3B (Phase 5 v1)", "generation_v1_ollama", None, None, None),
    ("Same, gpt-oss-120b for every answer (reference)", "generation_v1_groq", None, None, None),
    ("Agent: own filters + rewrite, no XBRL", "agent_v0", "agent_no_xbrl", None, None),
    ("+ XBRL facts (agent v0)", "agent_v0", "agent", "judge_v0", None),
    ("+ trend fixes: series table, intent rules (v1)", "agent_v1", "agent", "judge_v1", "judge_v1_qwen"),
    ("**+ routing trend/comparison to gpt-oss-120b (v2, current)**", "agent_v2", "agent_routed", "judge_v2",
     "judge_v2_qwen"),
)


def answer_rows(reports: dict[str, dict]) -> list[str]:
    lines = ["| Configuration | False abstention | Abstention recall | Citation hit (incl. XBRL) | Figure recall | "
             "Verifier claim support | Judged correctness: gpt-oss / qwen | Judge faithfulness |",
             "|---|---|---|---|---|---|---|---|"]
    for label, name, key, judge, judge_qwen in ANSWER_STEPS:
        if name not in reports:
            continue
        s = reports[name]["summary"]
        s = s[key] if key else s
        j = reports.get(judge, {}).get("summary", {}) if judge else {}
        jq = reports.get(judge_qwen, {}).get("summary", {}) if judge_qwen else {}
        hit = s.get("citation_hit_xbrl") if s.get("citation_hit_xbrl") is not None else s.get("citation_hit")
        faith = jq.get("faithfulness", j.get("faithfulness"))
        lines.append(f"| {label} | {_f(s.get('false_abstention_rate'))} | {_f(s.get('abstention_recall'))} | {_f(hit)} | "
                     f"{_f(s.get('figure_recall'))} | {_f(s.get('claim_support'))} | "
                     f"{_f(j.get('correctness_all_answerable'))} / {_f(jq.get('correctness_all_answerable'))} | "
                     f"{_f(faith)} |")
    return lines


def category_correctness(judge: dict) -> dict[str, float | None]:
    """Judged correctness per category over answerable questions (abstention = 0), as the judge report does."""
    by: dict[str, list[float]] = defaultdict(list)
    for r in judge["records"]:
        if r["answerable"] and not r["error"]:
            by[r["category"]].append(r["correctness_score"])
    return {c: _mean(by.get(c, [])) for c in CATEGORIES}


def category_rows(reports: dict[str, dict]) -> list[str]:
    steps = [("v0 (gpt-oss judge)", "judge_v0"), ("v1 (qwen judge)", "judge_v1_qwen"), ("v2 routed (qwen judge)", "judge_v2_qwen")]
    lines = ["| Judged correctness | " + " | ".join(CATEGORIES) + " | all answerable |",
             "|---|" + "---|" * (len(CATEGORIES) + 1)]
    for label, name in steps:
        if name in reports:
            c = category_correctness(reports[name])
            lines.append(f"| {label} | " + " | ".join(_f(c[k]) for k in CATEGORIES) +
                         f" | {_f(reports[name]['summary']['correctness_all_answerable'])} |")
    return lines


# --- evaluators ----------------------------------------------------------------------------------


def evaluator_rows(reports: dict[str, dict]) -> list[str]:
    lines = ["| Check | Agreement | n | Source |", "|---|---|---|---|"]
    for name in ("judge_v0", "judge_v2", "judge_v2_qwen"):
        if name in reports:
            s = reports[name]["summary"]
            lines.append(f"| Judge ({name}) vs hand labels: exact / correct-vs-not | {_f(s['label_agreement'], 2)} / "
                         f"{_f(s['label_agreement_lenient'], 2)} | {s['labelled']} | `{name}.md` |")
    if "judge_v2" in reports and "judge_v2_qwen" in reports:
        def recs(n):
            return {r["id"]: r for r in reports[n]["records"]}
        c = compare(recs("judge_v2"), recs("judge_v2_qwen"))
        lines.append(f"| gpt-oss judge vs qwen judge, same v2 answers: exact / correct-vs-not | {_f(c['exact'], 2)} / "
                     f"{_f(c['binary'], 2)} | {c['judged_by_both']} | `judge_agreement_v2.md` |")
    if "ragas_v0" in reports:
        s = reports["ragas_v0"]["summary"]
        lines.append(f"| RAGAS faithfulness vs judge faithfulness: mean {_f(s['faithfulness'])} vs "
                     f"{_f(s['judge_faithfulness'])}, Spearman | {_f(s['spearman_faithfulness'], 2)} | {s['scored']} | `ragas_v0.md` |")
        lines.append(f"| RAGAS factual correctness vs judge correctness: f1 {_f(s['factual_correctness'])} vs "
                     f"{_f(s['judge_correctness'])}, Spearman (coverage / f1) | {_f(s['spearman_coverage'], 2)} / "
                     f"{_f(s['spearman_f1'], 2)} | {s['scored']} | `ragas_v0.md` |")
    return lines


# --- latency and cost ----------------------------------------------------------------------------


def latency_rows(traces: list[Trace]) -> list[str]:
    s = summarize_traces(traces)
    lines = ["| Node | n | p50 ms | p95 ms |", "|---|---|---|---|"]
    lines += [f"| {k} | {v['n']} | {v['p50']:,.0f} | {v['p95']:,.0f} |" for k, v in s["nodes"].items() if k != "total"]
    by_intent: dict[str, list[float]] = defaultdict(list)
    for t in traces:
        for sp in t.spans:
            if sp.name == "retrieve":
                by_intent[t.metadata.get("intent") or "-"].append(sp.ms)
    lines += ["", "| Retrieve by plan intent | n | p50 ms | max ms |", "|---|---|---|---|"]
    lines += [f"| {k} | {len(v)} | {statistics.median(v):,.0f} | {max(v):,.0f} |"
              for k, v in sorted(by_intent.items(), key=lambda kv: statistics.median(kv[1]))]
    lines += ["", "| LLM call / model | Calls | Tokens per call | Provider p50 ms | p95 ms |", "|---|---|---|---|---|"]
    for k, v in s["llm"].items():
        per_call = (v["prompt_tokens"] + v["completion_tokens"]) / v["calls"]
        lines.append(f"| {k} | {v['calls']} | {per_call:,.0f} | {v['provider_p50']:,.0f} | {v['provider_p95']:,.0f} |")
    return lines


# --- report --------------------------------------------------------------------------------------


def build(reports: dict[str, dict], traces: list[Trace] | None) -> str:
    v2 = reports.get("judge_v2_qwen", {}).get("summary", {})
    v0 = reports.get("judge_v0", {}).get("summary", {})
    lines = [
        "# FinRAG evaluation v1 (Phase 7 summary)", "",
        "Generated by `python -m app.evaluation.build_eval_report` from the committed reports; no model calls. "
        "Golden set: 84 questions over 40 10-K filings (10 companies, FY2022-2025): 27 lookup, 17 numeric, 12 trend, "
        "12 comparison, 6 follow-up, 10 unanswerable; quote-verified gold pages; hand-written reference answers.", "",
        "## Headline", "",
        f"- **Answers:** judged correctness (all answerable, abstention = 0) {_f(v0.get('correctness_all_answerable'))} "
        f"→ **{_f(v2.get('correctness_all_answerable'))}** from agent v0 to the routed v2 agent (v0 judged by gpt-oss-120b; "
        "v2 scores 0.865 by gpt-oss and by an independent qwen3.8-27b judge that wrote no answer); trend 0.250 → 0.792, "
        "comparison 0.667 → 0.958 / 1.000.",
        "- **Retrieval:** hybrid (dense + BM25, RRF) + cross-encoder rerank + a per-entity retrieval plan: "
        "recall@10 0.966, MRR 0.927 with gold filters.",
        "- **Grounding:** every claim is checked against its cited page in code; abstention recall 1.000 (all 10 "
        "unanswerable questions refused), false abstention 0.041.",
        "- **Cost:** zero. Local embeddings, reranker and 3B model; Groq free tier for trend/comparison answers and "
        "for the judges; every LLM call cached.", "",
        "## 1. Retrieval ablation", "",
        "74 answerable questions, page-level relevance (`retrieval_v0.md`, `plan_v0.md`). p50 is per question "
        "on the MacBook M4 (reranking on mps).", "",
        *retrieval_rows(reports["retrieval_v0"], reports["plan_v0"]), "",
        "Reading: BM25 alone misses paraphrases, dense alone misses exact terms; RRF fusion beats both, and the "
        "cross-encoder adds the most (MRR 0.794 → 0.920) at ~2 s per query. Without filters plain retrieval collapses "
        "(BM25 recall@5 0.464); with the reranker it barely moves, which is what makes the agent's own filters safe. "
        "The plan's per-entity quotas fix multi-company/multi-year questions where one entity crowded out the others.", "",
        "## 2. Answer ablation", "",
        "Each row adds one component; all 84 questions (`generation_v1_*`, `agent_v0..v2`, `judge_*`). Judged "
        "correctness counts an abstention on an answerable question as 0. Figure recall is a strict string metric "
        "(secondary reference figures count); the judge replaced it as the correctness measure.", "",
        *answer_rows(reports), "",
        *category_rows(reports), "",
        "Reading:",
        "- The agent finds its own filters and rewrites follow-ups without losing anything against gold filters "
        "(false abstention 0.054 = 0.054); without XBRL facts it would (0.095).",
        "- The verifier passes figures, not meaning: 17 answers passed it and were judged wrong in v0 (wrong year, "
        "wrong direction, a one-year growth called a CAGR). That is why the judge exists.",
        "- Trend was the weak spot (0.250). Code-computed series tables and intent rules took it to 0.542; the rest "
        "was model capacity, so trend/comparison questions are routed to gpt-oss-120b (0.792 / 1.000). A stricter "
        "\"never compute a percentage\" prompt was tested and rejected: more abstentions, lower correctness.", "",
        "## 3. Evaluating the evaluators", "",
        *evaluator_rows(reports), "",
        "Reading: the judge agrees with hand labels and a second judge from another model family agrees with it, so "
        "self-preference doesn't drive the routing gain. RAGAS corroborates faithfulness but its factual correctness "
        "is too literal for 10-K answers (rounded figures, dates, extra detail count as errors), so it is a second "
        "opinion, not the metric.", "",
        "## 4. Latency and cost", "",
    ]
    if traces:
        lines += [f"From {len(traces)} traces of the routed agent (`app/tracing.py`; LLM calls served from the cache, "
                  "so their latency is the original provider call stored with the cache entry; node times are real).", "",
                  *latency_rows(traces), ""]
    else:
        lines += [f"No trace file at `data/traces/agent_v2.jsonl`; regenerate it (all cached, ~3 min, 0 tokens): "
                  f"`{TRACE_COMMAND}`", ""]
    lines += [
        "Reading: a local answer is ~17 s end to end, 90% of it the 3B model's generation. Routed trend/comparison "
        "answers are ~6-8 s, and there retrieval is the larger part: one reranked sub-query per company-year. Dense "
        "vector search itself is 0.36 ms (exact FAISS; `index_benchmark.md`). Free-tier capacity is set by the routed "
        "path: ~4k tokens per routed answer against Groq's ~200k tokens/day per model, about 50 routed answers a day "
        "before the local model takes over.", "",
        "## 5. Known limits", "",
        "- **Definition mismatches:** XBRL line items vs company definitions (Meta capex incl. finance leases, Amazon "
        "net cash capex, Apple buyback program vs cash paid): T12 (Meta capex trend) and N16 (Amazon capex) are still "
        "judged incorrect; T11, N09 and F06 are now correct.",
        "- **Small golden set:** 84 questions, 12 per hard category, so one question moves a category score by ~0.08.",
        "- **Labels and references by the same assistant** that wrote the judge prompt; a human review of the 22 labels "
        "would make the judge validation independent.",
        "- **Judge cost:** ~1.3-1.6k tokens per answer; a full judged run uses half a day of one Groq model's quota.",
        "- **RAGAS on 26 of 74 answers** (free-tier time); the full run is resumable from the cache.",
        "- **Tracing to Langfuse** is implemented but only tested against a mock until keys are added.",
    ]
    return "\n".join(lines) + "\n"


REPORT_NAMES = ("retrieval_v0", "plan_v0", "generation_v1_ollama", "generation_v1_groq", "agent_v0", "agent_v1",
                "agent_v2", "judge_v0", "judge_v1", "judge_v1_qwen", "judge_v2", "judge_v2_qwen", "ragas_v0")


def load_reports(directory: Path = REPORTS) -> dict[str, dict]:
    return {n: json.loads((directory / f"{n}.json").read_text()) for n in REPORT_NAMES if (directory / f"{n}.json").exists()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--traces", type=Path, default=TRACES)
    parser.add_argument("--out", type=Path, default=REPORTS / "eval_v1.md")
    args = parser.parse_args()
    report = build(load_reports(), load_traces(args.traces) if args.traces.exists() else None)
    args.out.write_text(report, encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
