"""Tracing: node spans and LLM calls per agent turn, the JSONL and Langfuse sinks, the latency summary."""

import json

import httpx
import pytest

from app.config import Settings
from app.generation.llm import LLM, LLMResponse, ResponseCache, Usage
from app.generation.schemas import GeneratedAnswer
from app.tracing import (JsonlSink, LangfuseSink, Trace, TraceSink, build_sinks, load_traces, record_generation,
                         render_summary, span, start_trace, summarize)
from tests.test_graph import answer, make_agent

QUESTION = "What was NVIDIA's revenue in fiscal 2025?"


class AnswerProvider:
    name, model = "groq", "openai/gpt-oss-120b"

    def __init__(self):
        self.calls = 0

    def complete(self, messages, schema, schema_name):
        self.calls += 1
        return LLMResponse(json.dumps(answer("Revenue for fiscal year 2025 was $130.5 billion", "S1")),
                           self.name, self.model, Usage(1200, 80), latency_ms=950.0)


class FailingSink(TraceSink):
    def export(self, trace):
        raise RuntimeError("down")


def test_agent_turn_traces_nodes_and_llm_calls_and_writes_jsonl(tmp_path):
    provider = AnswerProvider()
    llm = LLM([provider], ResponseCache(tmp_path / "cache"))
    agent = make_agent(llm)
    agent.trace_sinks = [JsonlSink(tmp_path / "traces.jsonl"), FailingSink()]  # a broken sink can't break a turn

    turn = agent.run(QUESTION)
    t = turn.trace
    assert not turn.result.abstained
    # retrieve and xbrl run as parallel branches (thread pool): their order varies, both land in this trace
    assert sorted(s.name for s in t.spans) == ["analyze", "generate", "retrieve", "verify", "xbrl"]
    assert t.input == QUESTION and t.output.startswith("Revenue for fiscal year 2025")
    assert t.metadata["steps"][-1] == "respond" and t.metadata["abstained"] is False
    [g] = t.generations
    assert (g.name, g.provider, g.model, g.span) == ("GeneratedAnswer", "groq", "openai/gpt-oss-120b", "generate")
    assert (g.prompt_tokens, g.completion_tokens, g.cached, g.provider_ms) == (1200, 80, False, 950.0)
    assert t.end >= t.start and all(s.end >= s.start for s in t.spans)

    again = agent.run(QUESTION).trace  # served from the LLM cache: still traced, with the original call's latency
    assert provider.calls == 1 and again.generations[0].cached and again.generations[0].provider_ms == 950.0
    assert again.id != t.id

    loaded = load_traces(tmp_path / "traces.jsonl")
    assert [x.id for x in loaded] == [t.id, again.id]
    assert loaded[0].generations[0].span == "generate"
    s = summarize(loaded)
    assert s["turns"] == 2 and s["nodes"]["retrieve"]["n"] == 2 and "total" in s["nodes"]
    row = s["llm"]["GeneratedAnswer / openai/gpt-oss-120b"]
    assert (row["calls"], row["cached"], row["prompt_tokens"], row["provider_p50"]) == (2, 1, 2400, 950.0)
    assert "| retrieve | 2 |" in render_summary(s)


def test_llm_calls_outside_a_trace_are_not_recorded_and_nested_traces_reuse_the_outer_one(tmp_path):
    LLM([AnswerProvider()], ResponseCache(tmp_path)).generate([{"role": "user", "content": "q"}], GeneratedAnswer)
    record_generation("X", "p", "m", 0.0)  # no trace open: no-op
    with start_trace("eval", "q") as outer:
        with start_trace("agent", "q") as inner, span("generate"):
            record_generation("Judgment", "groq", "qwen", 0.0, 10, 2)
    assert inner is outer and [g.span for g in outer.generations] == ["generate"]
    assert [s.name for s in outer.spans] == ["generate"]


def _trace() -> Trace:
    with start_trace("agent", QUESTION, history_turns=0) as t:
        with span("generate"):
            record_generation("GeneratedAnswer", "groq", "openai/gpt-oss-120b", t.start, 1200, 80, False, 950.0,
                              ["ollama: invalid JSON (1 errors)"])
        t.output = "Revenue was $130.5 billion."
    return t


def test_langfuse_sink_posts_one_batch_with_trace_spans_and_generations():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(207, json={"successes": [], "errors": []})

    sink = LangfuseSink("pk-lf-1", "sk-lf-1", "https://cloud.langfuse.com/",
                        client=httpx.Client(transport=httpx.MockTransport(handler)))
    t = _trace()
    sink.export(t)
    [req] = seen
    assert str(req.url) == "https://cloud.langfuse.com/api/public/ingestion"
    assert req.headers["authorization"].startswith("Basic ")
    batch = json.loads(req.content)["batch"]
    assert [e["type"] for e in batch] == ["trace-create", "span-create", "generation-create"]
    trace_body, span_body, gen = (e["body"] for e in batch)
    assert trace_body["id"] == t.id and trace_body["input"] == QUESTION and trace_body["metadata"] == {"history_turns": 0}
    assert span_body["traceId"] == t.id and span_body["startTime"].endswith("Z")
    assert gen["parentObservationId"] == span_body["id"] and gen["model"] == "openai/gpt-oss-120b"
    assert gen["usageDetails"] == {"input": 1200, "output": 80}
    assert gen["metadata"]["attempts"] == ["ollama: invalid JSON (1 errors)"]


def test_langfuse_sink_raises_on_rejected_events():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(207, json={"successes": [], "errors": [{"id": "x", "status": 400}]})))
    with pytest.raises(RuntimeError, match="rejected 1"):
        LangfuseSink("pk", "sk", client=client).export(_trace())
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key")))
    with pytest.raises(RuntimeError, match="401"):
        LangfuseSink("pk", "sk", client=client).export(_trace())


def test_build_sinks_only_with_keys_or_a_trace_file(tmp_path):
    assert build_sinks(Settings(_env_file=None)) == []
    sinks = build_sinks(Settings(_env_file=None, trace_file=tmp_path / "t.jsonl", langfuse_public_key="pk",
                                 langfuse_secret_key="sk"))
    assert [type(s) for s in sinks] == [JsonlSink, LangfuseSink]
    assert build_sinks(Settings(_env_file=None, langfuse_public_key="pk")) == []  # both keys needed
