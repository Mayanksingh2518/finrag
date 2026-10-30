"""Per-turn traces: graph node spans and every LLM call, kept locally and optionally sent to Langfuse.

    with start_trace("agent", question) as trace:   # FinRAGAgent.run does this
        ...                                          # nodes: with span("retrieve"): ...
                                                     # LLM.generate: record_generation(...)

The current trace lives in a contextvar, so `LLM.generate` records its calls without the trace being
passed down through the answerer, analyzer and judge. LangGraph runs parallel branches (retrieve and
xbrl) in a thread pool that copies the context, so their spans land in the same trace.

Sinks, all optional:
- the trace object itself (`AgentTurn.trace`): node timings, LLM provider/model/tokens/cache hit;
- a JSONL file (`TRACE_FILE`), one trace per line: `python -m app.tracing data/traces/x.jsonl`
  prints p50/p95 per node and tokens per model;
- Langfuse Cloud (free Hobby tier) when `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are set, through
  its public ingestion API (one batched POST per trace, after the turn, never blocking the answer
  on failure). No Langfuse SDK: the HTTP API is small and stable, and the SDK would pull in
  OpenTelemetry.
"""

import contextlib
import contextvars
import json
import logging
import statistics
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Span:
    name: str
    start: float  # epoch seconds
    end: float = 0.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def ms(self) -> float:
        return round((self.end - self.start) * 1000, 1)


@dataclass
class Generation:
    """One `LLM.generate` call (after cache lookup, retries and fallback)."""

    name: str  # output schema, e.g. GeneratedAnswer, Judgment
    provider: str
    model: str
    start: float
    end: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False
    provider_ms: float = 0.0  # the provider call itself (from the cache entry when cached)
    attempts: list[str] = field(default_factory=list)  # failures before the provider that answered
    span: str = ""  # name of the node it ran in
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def ms(self) -> float:
        return round((self.end - self.start) * 1000, 1)  # incl. rate-limit waits and retries


@dataclass
class Trace:
    name: str
    input: str
    start: float = field(default_factory=_now)
    end: float = 0.0
    output: str = ""
    metadata: dict = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    generations: list[Generation] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add_span(self, s: Span) -> None:
        with self._lock:
            self.spans.append(s)

    def add_generation(self, g: Generation) -> None:
        with self._lock:
            self.generations.append(g)

    @property
    def ms(self) -> float:
        return round((self.end - self.start) * 1000, 1)

    def node_ms(self) -> dict[str, float]:
        """Total time per node name (a widened turn runs retrieve twice)."""
        out: dict[str, float] = defaultdict(float)
        for s in self.spans:
            out[s.name] += s.ms
        return dict(out)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "input": self.input, "output": self.output, "start": self.start,
                "end": self.end, "ms": self.ms, "metadata": self.metadata, "spans": [asdict(s) for s in self.spans],
                "generations": [asdict(g) for g in self.generations]}  # not asdict(self): the lock can't be copied

    @classmethod
    def from_dict(cls, d: dict) -> "Trace":
        t = cls(d["name"], d["input"], d["start"], d["end"], d.get("output", ""), d.get("metadata", {}),
                [Span(**s) for s in d.get("spans", [])], [Generation(**g) for g in d.get("generations", [])], d["id"])
        return t


_trace: contextvars.ContextVar[Trace | None] = contextvars.ContextVar("finrag_trace", default=None)
_span: contextvars.ContextVar[str] = contextvars.ContextVar("finrag_span", default="")


def current_trace() -> Trace | None:
    return _trace.get()


@contextlib.contextmanager
def start_trace(name: str, input: str, sinks: Sequence["TraceSink"] = (), **metadata) -> Iterator[Trace]:
    """Opens a trace for one turn; nested calls reuse the outer trace (an eval run inside a request)."""
    if (outer := _trace.get()) is not None:
        yield outer
        return
    trace = Trace(name, input, metadata=metadata)
    token = _trace.set(trace)
    try:
        yield trace
    finally:
        trace.end = _now()
        _trace.reset(token)
        for sink in sinks:
            try:
                sink.export(trace)
            except Exception as e:  # tracing must never break an answer
                log.warning("Trace sink %s failed: %s", type(sink).__name__, e)


@contextlib.contextmanager
def span(name: str) -> Iterator[None]:
    trace = _trace.get()
    if trace is None:
        yield
        return
    s = Span(name, _now())
    token = _span.set(name)
    try:
        yield
    finally:
        s.end = _now()
        _span.reset(token)
        trace.add_span(s)


def record_generation(name: str, provider: str, model: str, start: float, prompt_tokens: int = 0,
                      completion_tokens: int = 0, cached: bool = False, provider_ms: float = 0.0,
                      attempts: Sequence[str] = ()) -> None:
    """Called by `LLM.generate` for every call; a no-op outside a trace. `start` is epoch seconds."""
    trace = _trace.get()
    if trace is not None:
        trace.add_generation(Generation(name, provider, model, start, _now(), prompt_tokens, completion_tokens,
                                        cached, provider_ms, list(attempts), _span.get()))


# --- sinks ---------------------------------------------------------------------------------------


class TraceSink:
    def export(self, trace: Trace) -> None:
        raise NotImplementedError


class JsonlSink(TraceSink):
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def export(self, trace: Trace) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(trace.to_dict(), ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class LangfuseSink(TraceSink):
    """Langfuse public ingestion API: trace-create + span-create per node + generation-create per LLM call."""

    def __init__(self, public_key: str, secret_key: str, host: str = "https://cloud.langfuse.com",
                 client: httpx.Client | None = None, timeout_s: float = 10.0):
        self.url = host.rstrip("/") + "/api/public/ingestion"
        self._auth = (public_key, secret_key)
        self._client = client or httpx.Client(timeout=timeout_s)

    def events(self, trace: Trace) -> list[dict]:
        def event(kind: str, body: dict, ts: float) -> dict:
            return {"id": uuid.uuid4().hex, "timestamp": _iso(ts), "type": kind, "body": body}

        span_ids = {s.name: s.id for s in trace.spans}  # a generation hangs under the node it ran in
        out = [event("trace-create", {"id": trace.id, "name": trace.name, "timestamp": _iso(trace.start),
                                      "input": trace.input, "output": trace.output, "metadata": trace.metadata},
                     trace.start)]
        out += [event("span-create", {"id": s.id, "traceId": trace.id, "name": s.name, "startTime": _iso(s.start),
                                      "endTime": _iso(s.end)}, s.start) for s in trace.spans]
        for g in trace.generations:
            body = {"id": g.id, "traceId": trace.id, "name": g.name, "model": g.model,
                    "startTime": _iso(g.start), "endTime": _iso(g.end),
                    "usageDetails": {"input": g.prompt_tokens, "output": g.completion_tokens},
                    "metadata": {"provider": g.provider, "cached": g.cached, "provider_ms": g.provider_ms,
                                 "attempts": g.attempts}}
            if g.span in span_ids:
                body["parentObservationId"] = span_ids[g.span]
            out.append(event("generation-create", body, g.start))
        return out

    def export(self, trace: Trace) -> None:
        res = self._client.post(self.url, json={"batch": self.events(trace)}, auth=self._auth)
        if res.status_code not in (200, 201, 207):
            raise RuntimeError(f"langfuse HTTP {res.status_code}: {res.text[:200]}")
        errors = res.json().get("errors") if res.status_code == 207 else None
        if errors:
            raise RuntimeError(f"langfuse rejected {len(errors)} events: {str(errors)[:200]}")


def build_sinks(settings=None) -> list[TraceSink]:
    from app.config import get_settings

    settings = settings or get_settings()
    sinks: list[TraceSink] = []
    if settings.trace_file:
        sinks.append(JsonlSink(Path(settings.trace_file)))
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        sinks.append(LangfuseSink(settings.langfuse_public_key, settings.langfuse_secret_key, settings.langfuse_host))
    return sinks


# --- summary -------------------------------------------------------------------------------------


def _pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[round(q * 100) - 1]


def summarize(traces: Sequence[Trace]) -> dict:
    """p50/p95 per node over the turns that ran it, and LLM calls/tokens per (schema, model)."""
    nodes: dict[str, list[float]] = defaultdict(list)
    for t in traces:
        for name, ms in t.node_ms().items():
            nodes[name].append(ms)
        nodes["total"].append(t.ms)
    llm: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cached": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                                "provider_ms": []})
    for t in traces:
        for g in t.generations:
            row = llm[f"{g.name} / {g.model}"]
            row["calls"] += 1
            row["cached"] += g.cached
            row["prompt_tokens"] += g.prompt_tokens
            row["completion_tokens"] += g.completion_tokens
            row["provider_ms"].append(g.provider_ms)
    return {
        "turns": len(traces),
        "nodes": {k: {"n": len(v), "p50": _pct(v, 0.5), "p95": _pct(v, 0.95)} for k, v in nodes.items()},
        "llm": {k: {**{x: y for x, y in v.items() if x != "provider_ms"},
                    "provider_p50": _pct(v["provider_ms"], 0.5), "provider_p95": _pct(v["provider_ms"], 0.95)}
                for k, v in llm.items()},
    }


def render_summary(s: dict) -> str:
    lines = [f"Turns: {s['turns']}", "", "| Node | n | p50 ms | p95 ms |", "|---|---|---|---|"]
    lines += [f"| {k} | {v['n']} | {v['p50']:,.0f} | {v['p95']:,.0f} |" for k, v in s["nodes"].items()]
    lines += ["", "| LLM call / model | Calls | Cached | Prompt tok | Completion tok | Provider p50 ms | p95 ms |",
              "|---|---|---|---|---|---|---|"]
    lines += [f"| {k} | {v['calls']} | {v['cached']} | {v['prompt_tokens']:,} | {v['completion_tokens']:,} | "
              f"{v['provider_p50']:,.0f} | {v['provider_p95']:,.0f} |" for k, v in s["llm"].items()]
    return "\n".join(lines) + "\n"


def load_traces(path: Path) -> list[Trace]:
    return [Trace.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    """Summarise a JSONL trace file: python -m app.tracing data/traces/agent.jsonl"""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("path", type=Path)
    print(render_summary(summarize(load_traces(parser.parse_args().path))), end="")


if __name__ == "__main__":
    main()
