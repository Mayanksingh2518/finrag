"""Phase 7 summary report: tables built from small report dicts; missing values stay "-"."""

from app.evaluation.build_eval_report import (SHIPPED_PLAN, answer_rows, build, category_correctness,
                                              evaluator_rows, retrieval_rows)
from app.tracing import Generation, Span, Trace


def _q(i, cat, recall, mrr, ms):
    return {"id": i, "category": cat, "metrics": {"recall@5": recall, "recall@10": recall, "mrr": mrr, "ndcg@10": mrr},
            "timings_ms": {"total": ms}}


RETRIEVAL = {"runs": [{"name": "bm25", "filtered": True, "questions": [_q("L01", "lookup", 1.0, 1.0, 1), _q("T01", "trend", 0.5, 0.5, 3)]},
                      {"name": "hybrid_rerank", "filtered": False, "questions": [_q("L01", "lookup", 1.0, 1.0, 2000)]}],
             "ablations": []}
PLAN = {SHIPPED_PLAN: {"summary": {"recall@5": 0.921, "recall@10": 0.966, "mrr": 0.927, "p50_ms": 2699.4}}}


def _judged(i, cat, score, answerable=True, error=""):
    grade = {1.0: "correct", 0.5: "partially_correct", 0.0: "incorrect"}[score]
    return {"id": i, "category": cat, "answerable": answerable, "error": error, "judged": True, "answer": i,
            "correctness": grade, "correctness_score": score, "reason": ""}


def _judge(records, correctness, labels=(0.9, 1.0, 10)):
    return {"summary": {"correctness_all_answerable": correctness, "faithfulness": 0.9, "label_agreement": labels[0],
                        "label_agreement_lenient": labels[1], "labelled": labels[2]}, "records": records}


REPORTS = {
    "retrieval_v0": RETRIEVAL, "plan_v0": PLAN,
    "generation_v1_ollama": {"summary": {"false_abstention_rate": 0.054, "abstention_recall": 1.0, "citation_hit": 0.863,
                                         "figure_recall": 0.583, "claim_support": 0.978}},
    "agent_v2": {"summary": {"agent_routed": {"false_abstention_rate": 0.041, "abstention_recall": 1.0, "citation_hit": 0.676,
                                              "citation_hit_xbrl": 0.878, "figure_recall": 0.653, "claim_support": 0.965}}},
    "judge_v2": _judge([_judged("T01", "trend", 1.0), _judged("C01", "comparison", 0.5)], 0.75),
    "judge_v2_qwen": _judge([_judged("T01", "trend", 1.0), _judged("C01", "comparison", 1.0),
                             _judged("U01", "unanswerable", 1.0, answerable=False), _judged("L01", "lookup", 0.0, error="x")], 1.0),
}


def test_retrieval_rows_average_per_question_metrics_and_add_the_shipped_plan():
    rows = retrieval_rows(RETRIEVAL, PLAN)
    assert "| bm25 | gold | 0.750 | 0.750 | 0.750 | 0.750 | 2 |" in rows
    assert "| hybrid_rerank | none | 1.000 | 1.000 | 1.000 | 1.000 | 2,000 |" in rows
    assert any("retrieval plan" in r and "**0.966**" in r for r in rows)


def test_answer_rows_prefer_xbrl_citation_hit_and_show_missing_judges_as_dash():
    rows = answer_rows(REPORTS)
    gold = next(r for r in rows if r.startswith("| Gold filters"))
    assert "| 0.863 |" in gold and gold.endswith("| - / - | - |")
    routed = next(r for r in rows if "routing" in r)
    assert "| 0.878 |" in routed and "| 0.750 / 1.000 |" in routed  # citation hit incl. XBRL; both judges
    assert not any(r.startswith("| Agent: own filters") for r in rows)  # report not loaded: row skipped


def test_category_correctness_counts_answerable_without_errors():
    c = category_correctness(REPORTS["judge_v2_qwen"])
    assert c["trend"] == 1.0 and c["comparison"] == 1.0 and c["lookup"] is None and c["numeric"] is None


def test_evaluator_rows_compare_the_two_judges_on_identical_answers():
    rows = evaluator_rows(REPORTS)
    pair = next(r for r in rows if "gpt-oss judge vs qwen judge" in r)
    assert "| 0.50 / 0.50 | 2 |" in pair  # T01 agrees, C01 partial vs correct


def test_build_without_traces_explains_how_to_regenerate_them():
    report = build(REPORTS, None)
    assert "# FinRAG evaluation v1" in report and "No trace file" in report and "TRACE_FILE=" in report
    trace = Trace("agent", "q", 0.0, 2.0, metadata={"intent": "trend"},
                  spans=[Span("retrieve", 0.0, 1.5)],
                  generations=[Generation("GeneratedAnswer", "groq", "gpt-oss", 1.5, 2.0, 4000, 100, True, 1800.0)])
    with_traces = build(REPORTS, [trace])
    assert "| trend | 1 | 1,500 | 1,500 |" in with_traces and "| GeneratedAnswer / gpt-oss | 1 | 4,100 | 1,800 |" in with_traces
