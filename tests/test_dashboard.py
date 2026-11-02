"""The dashboard reads plain files: fixtures are a small LLM cache, a trace file and logs."""

import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.dashboard import Call, Ledger, call_kind, create_app, log_files, recent_turns, series_order, tail_lines, usage_summary

NOW = time.time()


def cache_entry(directory, name, provider, model, text, prompt, completion, age_s=0.0):
    path = directory / name[:2] / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"text": text, "provider": provider, "model": model, "latency_ms": 1000.0,
                                "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "reasoning_tokens": 0}}))
    os.utime(path, (NOW - age_s, NOW - age_s))


@pytest.fixture
def dirs(tmp_path):
    cache, traces, logs = tmp_path / "cache", tmp_path / "traces", tmp_path / "logs"
    traces.mkdir()
    logs.mkdir()
    cache_entry(cache, "aa1", "groq", "openai/gpt-oss-120b", '{"answer": "x"}', 100, 20, age_s=3 * 86_400)
    cache_entry(cache, "bb2", "ollama", "granite4.1:3b", '{"answer": "y"}', 200, 30, age_s=60)
    cache_entry(cache, "cc3", "groq", "qwen/qwen3.8-27b", '{"correctness": "correct"}', 50, 5, age_s=30)
    (logs / "evals.log").write_text("first\nsecond\n")
    (traces / "a.jsonl").write_text(
        json.dumps({"input": "old", "start": NOW - 100, "ms": 10.0}) + "\n"
        + json.dumps({"input": "new", "start": NOW - 10, "ms": 20.0, "metadata": {"model": "m", "abstained": False},
                      "spans": [{"name": "generate", "start": 1.0, "end": 2.5}],
                      "generations": [{"prompt_tokens": 7, "completion_tokens": 3, "cached": True}]}) + "\n"
        + "{partial line")
    return cache, traces, logs


def test_call_kind_reads_the_structured_output():
    assert call_kind('{"answer": "x", "claims": []}') == "Answer"
    assert call_kind('{"correctness": "correct", "claims": []}') == "Judge"
    assert call_kind('{"standalone_question": "q"}') == "Follow-up rewrite"
    assert call_kind('{"statements": []}') == "RAGAS metric"
    assert call_kind("not json") == "Other" and call_kind("[1]") == "Other"


def test_ledger_reads_each_entry_with_its_time_and_skips_broken_files(dirs):
    cache, _, _ = dirs
    (cache / "aa" / "broken.json").write_text("{not json")
    ledger = Ledger(cache)
    calls = ledger.calls()
    assert [c.model for c in calls] == ["openai/gpt-oss-120b", "granite4.1:3b", "qwen/qwen3.8-27b"]  # oldest first
    assert calls[0].tokens == 120 and calls[0].kind == "Answer" and abs(calls[0].ts - (NOW - 3 * 86_400)) < 2
    cache_entry(cache, "dd4", "groq", "openai/gpt-oss-120b", "{}", 1, 1)  # a new call shows up on the next read
    assert len(ledger.calls()) == 4


def test_summary_splits_hosted_from_local_and_counts_the_last_24_hours(dirs):
    u = usage_summary(Ledger(dirs[0]).calls(), NOW, days=0)
    assert u["hosted"]["tokens"] == 175 and u["hosted"]["tokens_24h"] == 55 and u["hosted"]["calls_24h"] == 1
    assert u["local"]["tokens"] == 230 and u["local"]["tokens_24h"] == 230
    assert {k["kind"]: k["calls"] for k in u["kinds"]} == {"Answer": 2, "Judge": 1}
    gpt = next(m for m in u["models"] if m["model"] == "openai/gpt-oss-120b")
    assert gpt["limit"] == 200_000 and next(m for m in u["models"] if m["provider"] == "ollama")["limit"] is None
    assert u["recent"][0]["model"] == "qwen/qwen3.8-27b"  # newest first


def test_chart_days_are_continuous_and_the_range_keeps_model_colors(dirs):
    calls = Ledger(dirs[0]).calls()
    whole = usage_summary(calls, NOW, days=0)
    assert len(whole["days"]) >= 4 and sum(sum(d["tokens"].values()) for d in whole["days"]) == 405
    recent = usage_summary(calls, NOW, days=1)
    assert len(recent["days"]) == 1
    assert recent["series"] == whole["series"]  # a model filtered out of the range doesn't repaint the others
    assert recent["hosted"]["tokens"] == 175  # the range only narrows the chart


def test_series_past_the_palette_fold_into_other():
    calls = [Call(NOW + i, "groq", f"m{i}", "Answer", 1, 1, 1.0) for i in range(10)]
    series = series_order(calls)
    assert len(series) == 8 and series[-1] == "Other" and series[0] == "m0"
    day = usage_summary(calls, NOW + 10, days=1)["days"][-1]["tokens"]
    assert day["Other"] == 2 * 3


def test_no_calls_at_all_still_renders(tmp_path):
    u = usage_summary(Ledger(tmp_path / "nothing").calls(), NOW)
    assert u["total"]["calls"] == 0 and u["models"] == [] and len(u["days"]) == 1


def test_tail_lines_keeps_the_end(tmp_path):
    path = tmp_path / "x.log"
    path.write_text("\n".join(map(str, range(10))) + "\n")
    assert tail_lines(path, 2) == ["8", "9"]


def test_recent_turns_are_newest_first_and_skip_partial_lines(dirs):
    turns = recent_turns(dirs[1])
    assert [t["question"] for t in turns] == ["new", "old"]
    assert turns[0]["nodes"] == [{"name": "generate", "ms": 1500.0}] and turns[0]["tokens"] == 10 and turns[0]["cached"]
    assert turns[1]["tokens"] == 0 and not turns[1]["cached"]


def test_api_serves_the_page_data_and_only_listed_logs(dirs, tmp_path):
    cache, traces, logs = dirs
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    extra = tmp_path / "extra.log"
    extra.write_text("hello\n")
    client = TestClient(create_app(cache, traces, logs, [extra]))
    assert "FinRAG dashboard" in client.get("/").text
    data = client.get("/api/data", params={"days": 7}).json()
    assert data["usage"]["total"]["calls"] == 3 and data["turns"][0]["question"] == "new"
    assert data["logs"] == ["evals.log", "extra.log"]
    assert client.get("/api/log", params={"name": "extra.log"}).json()["lines"] == ["hello"]
    for name in ("secret.txt", "../secret.txt", str(secret), "../../.env"):
        assert client.get("/api/log", params={"name": name}).status_code == 404
    assert client.get("/api/data", params={"days": -1}).status_code == 422


def test_log_list_ignores_a_missing_extra_file(tmp_path):
    assert log_files([tmp_path / "gone.log"], tmp_path) == {}


def test_page_never_inserts_file_text_as_html():
    """Logs, questions and answers are data: the page must not build markup from them."""
    from app.dashboard import PAGE

    assert "innerHTML" not in PAGE.read_text(encoding="utf-8") and "insertAdjacentHTML" not in PAGE.read_text(encoding="utf-8")


def test_import_loads_no_models():
    code = ("import sys, app.dashboard; bad = {'torch', 'sentence_transformers', 'faiss', 'langgraph'} & set(sys.modules); "
            "sys.exit(1 if bad else 0)")
    assert subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0
