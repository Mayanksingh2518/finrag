"""Agent-mode evaluation: the full graph on the golden set, with no gold filters and no gold rewrite.

Phase 5's generation eval hands the answerer the gold filters and, for follow-ups, the gold
standalone rewrite. Here every question goes through `FinRAGAgent.run(question, history)`: the
analyzer must find the filters, refuse out-of-range years, and rewrite follow-ups itself. Scored
with the Phase 5 `score()` plus:
- filters_ok: analyzer tickers/years/sections compatible with gold (none, or a superset)
- citation_hit_xbrl: citation hit that also counts a verified XBRL citation as covering a gold
  evidence item of the same company and year when the fact states a reference figure (XBRL
  sources have no page, so `score()` alone would penalise exact facts)
- facts / xbrl_cited, refused early (analyze node), rewrite calls, per-node latency

Configs run in one process; LLM calls are cached, so a question whose prompt is identical across
configs (no facts attached) costs one generation.

Usage:
    python -m app.evaluation.run_agent_eval                  # agent + agent without XBRL
    python -m app.evaluation.run_agent_eval --limit 5 --configs agent
    TRACE_FILE=data/traces/agent_v2.jsonl python -m app.evaluation.run_agent_eval --configs agent_routed \
        --out <dir>/agent_traced   # + per-node latency: python -m app.tracing data/traces/agent_v2.jsonl
"""

import argparse
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.agent.graph import AgentTurn, FinRAGAgent
from app.agent.xbrl import XbrlStore
from app.config import PROJECT_ROOT, get_settings
from app.evaluation.build_golden import DEFAULT_PATH as GOLDEN_PATH
from app.evaluation.golden import GoldQuestion, load_golden
from app.evaluation.metrics import RetrievedPage, covered_items
from app.evaluation.run_analyzer_eval import _compatible
from app.evaluation.run_generation_eval import GenerationRecord, _mean, _pct, score, summarize
from app.generation.llm import LLMError
from app.generation.verify import _matches, extract_numbers
from app.tracing import build_sinks, start_trace

CONFIGS = ("agent", "agent_no_xbrl", "agent_routed")  # routed: trend/comparison answered by Groq gpt-oss-120b
BASELINE = PROJECT_ROOT / "reports" / "generation_v1_ollama.json"  # gold filters, same model
# Questions whose figure the company defines differently from the GAAP line item (reports/xbrl_v0.md).
DEFINITION_MISMATCH = ("N09", "N16", "T11", "T12", "F06")


@dataclass
class AgentRecord(GenerationRecord):
    config: str = ""
    filters_ok: bool | None = None
    tickers: list[str] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    refused_early: bool = False
    rewritten: bool = False
    facts: int = 0
    xbrl_cited: bool = False
    citation_hit_xbrl: float | None = None
    steps: list[str] = field(default_factory=list)


def xbrl_covered(q: GoldQuestion, turn: AgentTurn) -> set[int]:
    """Gold evidence items covered by verified XBRL citations stating a reference figure."""
    reference = [n for n in extract_numbers(q.reference_answer) if n.percent or n.scale > 1 or n.value >= 10]
    by_id = {s.id: s for s in turn.result.sources}
    covered: set[int] = set()
    for sid in turn.result.cited_source_ids:
        s = by_id.get(sid)
        if s is None or not s.is_xbrl:
            continue
        fact_numbers = extract_numbers(s.chunk.text)
        if any(_matches(g, n) for g in reference for n in fact_numbers):
            years = s.chunk.metadata.get("years") or [s.chunk.fiscal_year]  # a series covers several
            covered |= {i for i, e in enumerate(q.evidence) if e.ticker == s.chunk.ticker and e.fiscal_year in years}
    return covered


def record(q: GoldQuestion, turn: AgentTurn, config: str) -> AgentRecord:
    base = score(q, turn.result)
    a = turn.analysis
    rec = AgentRecord(**asdict(base), config=config, tickers=list(a.filters.tickers or ()),
                      years=list(a.filters.fiscal_years or ()), refused_early="refuse" in turn.steps,
                      rewritten=a.rewritten, facts=len(turn.facts), steps=turn.steps)
    rec.latency_ms = turn.result.timings_ms
    by_id = {s.id: s for s in turn.result.sources}
    rec.xbrl_cited = any(by_id[i].is_xbrl for i in turn.result.cited_source_ids if i in by_id)
    if q.answerable:
        g = q.filters
        rec.filters_ok = (_compatible(a.filters.tickers, g.tickers) and _compatible(a.filters.fiscal_years, g.fiscal_years)
                          and _compatible(a.filters.sections, g.sections))
        if not turn.result.abstained and q.evidence:
            pages = [RetrievedPage(by_id[i].chunk.ticker, by_id[i].chunk.fiscal_year, by_id[i].chunk.page_start,
                                   by_id[i].chunk.page_end) for i in turn.result.cited_source_ids
                     if i in by_id and not by_id[i].is_xbrl]
            covered = set().union(*(covered_items(p, q.evidence) for p in pages)) if pages else set()
            rec.citation_hit_xbrl = float(bool(covered | xbrl_covered(q, turn)))
        else:
            rec.citation_hit_xbrl = 0.0
    return rec


def summarize_agent(records: list[AgentRecord]) -> dict:
    ans = [r for r in records if r.answerable]
    una = [r for r in records if not r.answerable]
    fired = [r for r in ans if r.facts]
    out = summarize(records)
    out.update({
        "filters_ok": _mean(float(r.filters_ok) for r in ans if r.filters_ok is not None),
        "citation_hit_xbrl": _mean(r.citation_hit_xbrl for r in ans),
        "refused_early_unanswerable": sum(r.refused_early for r in una),
        "refused_early_answerable": sum(r.refused_early for r in ans),
        "rewrites": sum(r.rewritten for r in records),
        "questions_with_facts": len(fired),
        "xbrl_cited": sum(r.xbrl_cited for r in fired),
        "figure_recall_with_facts": _mean(r.figure_recall for r in fired),
        # Early refusals never call the LLM, so they'd count as "uncached" at ~1 ms.
        "total_p50_ms": _pct([r.latency_ms.get("total") for r in records if not r.cached and not r.refused_early], 0.5),
        "total_p95_ms": _pct([r.latency_ms.get("total") for r in records if not r.cached and not r.refused_early], 0.95),
        "analyze_p50_ms": _pct([r.latency_ms.get("analyze") for r in records], 0.5),
    })
    return out


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "-"
    return f"{v:.3f}" if isinstance(v, float) and v <= 1.0 else f"{v:,.0f}" if isinstance(v, float) else str(v)


def render_report(results: dict[str, list[AgentRecord]], baseline: dict | None, title: str = "agent_v0") -> str:
    summaries = {c: summarize_agent(rs) for c, rs in results.items()}
    cols = (["gold filters (v1)"] if baseline else []) + list(summaries)
    rows = [
        ("False abstention (answerable)", "false_abstention_rate"),
        ("Abstention recall (unanswerable)", "abstention_recall"),
        ("Citation hit (gold page)", "citation_hit"),
        ("Citation hit incl. XBRL", "citation_hit_xbrl"),
        ("Evidence recall", "evidence_recall"),
        ("Figure recall", "figure_recall"),
        ("Claim support", "claim_support"),
        ("Filters compatible with gold", "filters_ok"),
        ("Unanswerable refused at analyze", "refused_early_unanswerable"),
        ("Answerable refused at analyze", "refused_early_answerable"),
        ("Questions with XBRL facts", "questions_with_facts"),
        ("... of which cite a fact", "xbrl_cited"),
        ("Figure recall on those questions", "figure_recall_with_facts"),
        ("LLM rewrites", "rewrites"),
        ("Errors", "errors"),
        ("LLM p50 / p95 ms", None),
        ("End-to-end p50 / p95 ms (uncached)", None),
    ]
    lines = [f"# Agent-mode evaluation: {title}", "",
             "Generated by `python -m app.evaluation.run_agent_eval`. Agent configs get **no gold filters and no",
             "gold rewrite**: `FinRAGAgent.run(question, history)`. The baseline column is",
             f"`{BASELINE.relative_to(PROJECT_ROOT)}` (gold filters and rewrite, v0 decomposition, same model).", "",
             "| Metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for label, key in rows:
        cells = []
        for c in cols:
            s = baseline if c == "gold filters (v1)" else summaries[c]
            if key is None and label.startswith("LLM"):
                cells.append(f"{_fmt(s.get('llm_p50_ms'))} / {_fmt(s.get('llm_p95_ms'))}")
            elif key is None:
                cells.append(f"{_fmt(s.get('total_p50_ms'))} / {_fmt(s.get('total_p95_ms'))}")
            else:
                cells.append(_fmt(s.get(key)))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    lines += ["", "## By category (false abstention / citation hit incl. XBRL / figure recall)", "",
              "| Category | " + " | ".join(results) + " |", "|---|" + "---|" * len(results)]
    cats = sorted({r.category for rs in results.values() for r in rs if r.answerable})
    for cat in cats:
        cells = []
        for rs in results.values():
            sub = [r for r in rs if r.answerable and r.category == cat]
            cells.append(f"{_mean(float(r.abstained) for r in sub):.2f} / {_mean(r.citation_hit_xbrl for r in sub):.2f} / "
                         f"{_fmt(_mean(r.figure_recall for r in sub))}")
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")

    first = next(iter(results.values()))
    mismatch = [r for r in first if r.id in DEFINITION_MISMATCH]
    if mismatch:
        lines += ["", "## Definition-mismatch questions (company figure differs from the XBRL line item)", "",
                  "| Id | Facts | Cites XBRL | Figure recall | Answer |", "|---|---|---|---|---|"]
        for r in mismatch:
            lines.append(f"| {r.id} | {r.facts} | {r.xbrl_cited} | {_fmt(r.figure_recall)} | "
                         f"{(r.answer or '[abstained] ' + r.abstain_reason)[:220].replace('|', '/')} |")

    lines += ["", "## Per question (first config)", "",
              "| Id | Filters ok | Steps | Facts | Abstained | Cite hit (+XBRL) | Fig recall | Total s |",
              "|---|---|---|---|---|---|---|---|"]
    for r in first:
        lines.append(f"| {r.id} | {_fmt(r.filters_ok)} | {' > '.join(r.steps)} | {r.facts} | {r.abstained} | "
                     f"{_fmt(r.citation_hit)} ({_fmt(r.citation_hit_xbrl)}) | {_fmt(r.figure_recall)} | "
                     f"{r.latency_ms.get('total', 0) / 1000:.1f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    parser.add_argument("--out", type=Path, help="default reports/agent_v0 (agent_v0_smoke with --limit)")
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--configs", nargs="+", default=["agent", "agent_no_xbrl"], choices=CONFIGS)
    args = parser.parse_args()
    # A partial run must never overwrite the full report.
    args.out = args.out or PROJECT_ROOT / "reports" / ("agent_v0_smoke" if args.limit else "agent_v0")
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app.generation.llm").setLevel(logging.INFO)

    from app.generation.llm import build_llm
    from app.retrieval.factory import build_retriever

    settings = get_settings()
    retriever, llm, xbrl = build_retriever(settings), build_llm(settings), XbrlStore.from_settings()
    sinks = build_sinks(settings)
    questions = load_golden(args.golden)[: args.limit]
    results: dict[str, list[AgentRecord]] = {}
    routed_llm = (build_llm(settings.model_copy(update={"llm_providers": "groq,ollama"}))
                  if "agent_routed" in args.configs else None)
    for config in args.configs:
        agent = FinRAGAgent(retriever, llm, xbrl=None if config == "agent_no_xbrl" else xbrl,
                            token_budget=settings.context_token_budget,
                            routed_llm=routed_llm if config == "agent_routed" else None)
        records = results[config] = []
        for i, q in enumerate(questions, 1):
            start = time.perf_counter()
            try:
                # TRACE_FILE / Langfuse keys in .env: one trace per question, tagged with id and config
                with start_trace("agent_eval", q.question, sinks, id=q.id, config=config, category=q.category):
                    turn = agent.run(q.question, q.history)
                rec = record(q, turn, config)
            except LLMError as e:
                rec = AgentRecord(q.id, q.category, q.answerable, False, "", "", "none", None, None, None, None,
                                  0, 0, [], "", False, {}, {}, error=str(e)[:300], config=config)
            records.append(rec)
            status = ("ERROR" if rec.error else "refused" if rec.refused_early else "abstain" if rec.abstained
                      else f"cite={rec.citation_hit_xbrl} fig={_fmt(rec.figure_recall)} facts={rec.facts}")
            print(f"[{config} {i}/{len(questions)}] {q.id} {status} ({time.perf_counter() - start:.1f} s"
                  f"{', cached' if rec.cached else ''})", flush=True)

    baseline = json.loads(BASELINE.read_text())["summary"] if BASELINE.exists() and not args.limit else None
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".md").write_text(render_report(results, baseline, args.out.stem), encoding="utf-8")
    args.out.with_suffix(".json").write_text(json.dumps(
        {"summary": {c: summarize_agent(rs) for c, rs in results.items()}, "baseline": baseline,
         "records": {c: [asdict(r) for r in rs] for c, rs in results.items()}}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(json.dumps({c: summarize_agent(rs) for c, rs in results.items()}, indent=1))
    print(f"Wrote {args.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
