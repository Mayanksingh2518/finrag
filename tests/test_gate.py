"""Eval regression gate: thresholds over committed reports; missing or broken reports fail."""

import json
import math

import pytest

from app.evaluation.check_gate import REPORTS, MetricError, check, render, resolve


def _write(directory, name, data):
    (directory / f"{name}.json").write_text(json.dumps(data))


@pytest.fixture
def reports(tmp_path):
    q = lambda recall: {"metrics": {"recall@5": recall, "mrr": 1.0}}  # noqa: E731
    _write(tmp_path, "retrieval_v1", {"runs": [
        {"name": "hybrid_rerank", "filtered": True, "questions": [q(1.0), q(0.5)]},
        {"name": "hybrid_rerank", "filtered": False, "questions": [q(0.0)]}]})
    _write(tmp_path, "plan_v0", {"plan quotas, k=10, MD&A prior 0.05": {"summary": {"recall@10": 0.96}}})
    _write(tmp_path, "agent_v2", {"summary": {"agent_routed": {"false_abstention_rate": 0.04, "figure_recall": math.nan}}})
    return tmp_path


def test_resolve_reads_each_metric_kind(reports):
    assert resolve("retrieval:hybrid_rerank:gold:recall@5", reports) == 0.75
    assert resolve("retrieval:hybrid_rerank:none:recall@5", reports) == 0.0
    assert resolve("plan:plan quotas, k=10, MD&A prior 0.05:recall@10", reports) == 0.96  # the config name holds spaces and a comma
    assert resolve("summary:agent_v2:agent_routed.false_abstention_rate", reports) == 0.04


@pytest.mark.parametrize("metric, message", [
    ("summary:judge_v9:correctness_all_answerable", "missing report judge_v9.json"),
    ("summary:agent_v2:agent_routed.nope", "no summary.agent_routed.nope"),
    ("summary:agent_v2:agent_routed.figure_recall", "not a number"),
    ("retrieval:bm25:gold:recall@5", "no retrieval run"),
    ("plan:other config:recall@10", "not found"),
    ("magic:x", "unknown metric kind"),
])
def test_resolve_fails_loudly_on_missing_or_broken_metrics(reports, metric, message):
    with pytest.raises(MetricError, match=message):
        resolve(metric, reports)


def test_check_passes_fails_and_reports_errors(reports):
    gate = {"checks": [
        {"label": "recall", "metric": "retrieval:hybrid_rerank:gold:recall@5", "min": 0.7},
        {"label": "abstention", "metric": "summary:agent_v2:agent_routed.false_abstention_rate", "max": 0.03},
        {"label": "judge", "metric": "summary:judge_v2:correctness_all_answerable", "min": 0.84},
    ]}
    results = check(gate, reports)
    assert [r.passed for r in results] == [True, False, False]
    assert results[1].value == 0.04 and results[1].bound == "<= 0.03"
    assert results[2].value is None and "missing report" in results[2].error
    table = render(results)
    assert "Eval gate: FAILED (1/3)" in table and "| ❌ | judge | missing report judge_v2.json | >= 0.84 |" in table


def test_committed_reports_pass_the_committed_gate():
    results = check(json.loads((REPORTS / "gate.json").read_text()))
    assert results and all(r.passed for r in results), render(results)
