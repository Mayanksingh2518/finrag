"""LLM judge: prompt contents, scoring, and the eval runner's summary/label agreement."""

import json

from app.evaluation.judge import Judge, Judgment
from app.evaluation.run_judge_eval import JudgedRecord, load_labels, render_report, summarize
from app.generation.context import build_sources
from app.generation.llm import LLMResponse, Usage
from app.retrieval.types import ScoredChunk
from tests.test_retrieval import make_chunk


class ScriptedJudgeLLM:
    def __init__(self, output: dict):
        self.output = output
        self.messages = None

    def generate(self, messages, output):
        assert output is Judgment
        self.messages = messages
        return Judgment.model_validate(self.output), LLMResponse("", "groq", "gpt-oss-120b", Usage(1800, 200))


VERDICT = {
    "correctness": "incorrect", "missing_facts": ["FY2022 $26.91B"],
    "contradicted_facts": ["114% is FY2025 growth, not a CAGR"],
    "claims": [
        {"claim": "Revenue was $130.5 billion in fiscal 2025.", "verdict": "supported", "reason": "stated"},
        {"claim": "CAGR of 114.2% from fiscal 2022.", "verdict": "unsupported", "reason": "source gives one-year growth"},
    ],
    "reason": "Mislabels a one-year growth rate as a CAGR.",
}


def test_judge_sends_reference_answer_and_only_given_sources():
    sources = build_sources([ScoredChunk(make_chunk(0, "NVDA", 2025, "Item 7", "Revenue was $130.5 billion, up 114%."), 0.9)],
                            token_budget=1000)
    llm = ScriptedJudgeLLM(VERDICT)
    res = Judge(llm).judge("How did NVIDIA's revenue grow?", "$130.5B in FY2025 (+114%).",
                           "Revenue grew at a CAGR of 114.2% [NVDA FY2025 p.1].", sources)
    user = llm.messages[1]["content"]
    assert "Reference answer: $130.5B in FY2025 (+114%)." in user
    assert "[NVDA FY2025 p.1]\nRevenue was $130.5 billion, up 114%." in user
    assert "outside knowledge" in llm.messages[0]["content"]
    assert res.correctness == 0.0 and res.faithfulness == 0.5


def test_summary_scores_abstentions_by_rule_and_measures_label_agreement():
    records = [
        JudgedRecord("T06", "trend", True, False, "a", "incorrect", 0.0, 0.5, True, label="incorrect",
                     verifier_supported=1.0, provider="groq", tokens=2000),
        JudgedRecord("N04", "numeric", True, False, "a", "correct", 1.0, 1.0, True, label="partially_correct",
                     verifier_supported=1.0, provider="groq", tokens=1500),
        JudgedRecord("L21", "lookup", True, True, "", "incorrect", 0.0, reason="abstained (rule)"),
        JudgedRecord("U01", "unanswerable", False, True, "", "correct", 1.0, reason="abstained (rule)"),
    ]
    s = summarize(records)
    assert s["correctness_all_answerable"] == 1 / 3  # abstention counts as 0
    assert s["correctness_answered"] == 0.5 and s["faithfulness"] == 0.75
    assert s["label_agreement"] == 0.5 and s["label_agreement_lenient"] == 0.5
    assert s["judge_tokens"] == 3500
    report = render_report(records, s)
    assert "Passed the verifier, judged not correct (1)" in report and "| T06 | incorrect |" in report


def test_labels_file_parses(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text("\n".join(json.dumps({"id": i, "correctness": c}) for i, c in [("A", "correct"), ("B", "incorrect")]))
    assert load_labels(path) == {"A": "correct", "B": "incorrect"}
    assert load_labels(tmp_path / "missing.jsonl") == {}


def test_compare_judges_counts_agreement_on_identical_answers_only():
    from app.evaluation.compare_judges import compare

    def rec(i, grade, answer="a", cat="trend"):
        score = {"correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0}[grade]
        return {"id": i, "judged": True, "answer": answer, "answerable": True, "error": "", "category": cat,
                "correctness": grade, "correctness_score": score, "reason": "r"}

    a = {"T1": rec("T1", "correct"), "T2": rec("T2", "incorrect"), "T3": rec("T3", "correct", answer="x")}
    b = {"T1": rec("T1", "correct"), "T2": rec("T2", "partially_correct"), "T3": rec("T3", "correct", answer="y")}
    c = compare(a, b)
    assert c["judged_by_both"] == 2 and c["exact"] == 0.5 and c["binary"] == 1.0  # T3's answers differ
    assert c["confusion"]["incorrect"]["partially_correct"] == 1
    assert [d[0] for d in c["disagreements"]] == ["T2"]
