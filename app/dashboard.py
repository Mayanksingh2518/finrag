"""Local dashboard: LLM token usage, logs and agent traces on one page. Loads no models.

A separate process from the API, so it can stay open during an eval on a 16 GB laptop. Three sources, all
plain files, read on every refresh:

- Token usage: the LLM response cache. Every provider call that returned is one file with provider, model,
  tokens and latency, and the file's modified time is when the call happened. It needs no tracing, so it
  covers every eval, judge and API call ever made. Failed calls (rate limits, timeouts) are never cached,
  so they aren't counted, and neither are cache hits, which cost nothing.
- Logs: `--log` files plus `data/logs/*.log`, only those; the page picks one by name, never by path.
- Traces: `data/traces/*.jsonl` (`TRACE_FILE`): the latest agent turns with per-node timings.

Usage:
    python -m app.dashboard                         # http://127.0.0.1:8020
    python -m app.dashboard --log <path>/evals.log  # also show this log file
"""

import argparse
import json
import re
import statistics
import subprocess
import time
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.config import PROJECT_ROOT, get_settings

DAY_S = 86_400
LOCAL_PROVIDERS = frozenset({"ollama"})  # the rest are hosted, on free-tier quotas
# Approximate free-tier tokens per day, from this project's own runs (progress.md), not read from Groq. Models
# not listed have no known limit. Groq's window may not match the rolling 24 h shown here.
DAILY_TOKEN_LIMITS = {"openai/gpt-oss-120b": 200_000, "qwen/qwen3.8-27b": 200_000}
MAX_SERIES = 8  # the chart's categorical palette has 8 validated colors; the rest fold into "Other"
LOG_TAIL_LINES = 400
TRACE_TAIL_BYTES = 4_000_000
RECENT_CALLS = 40
RECENT_TURNS = 30
PAGE = Path(__file__).with_name("dashboard.html")
_PROCESS = re.compile(r"-m\s+(app\.[\w.]+)|(uvicorn)\s+app\.")


@dataclass(frozen=True)
class Call:
    ts: float
    provider: str
    model: str
    kind: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def local(self) -> bool:
        return self.provider in LOCAL_PROVIDERS


def call_kind(text: str) -> str:
    """What the call was for, from the fields of its structured output."""
    try:
        fields = json.loads(text)
    except ValueError:
        return "Other"
    if not isinstance(fields, dict):
        return "Other"
    if "answer" in fields:
        return "Answer"
    if "correctness" in fields:
        return "Judge"
    if "standalone_question" in fields:
        return "Follow-up rewrite"
    if "statements" in fields or "claims" in fields:
        return "RAGAS metric"
    return "Other"


class Ledger:
    """The LLM cache as a list of calls. Entries never change, so each file is parsed once."""

    def __init__(self, directory: Path):
        self.directory = directory
        self._calls: dict[str, Call] = {}

    def calls(self) -> list[Call]:
        for path in self.directory.glob("*/*.json"):
            if path.name not in self._calls:
                try:
                    d = json.loads(path.read_text(encoding="utf-8"))
                    self._calls[path.name] = Call(
                        path.stat().st_mtime, d["provider"], d["model"], call_kind(d["text"]),
                        d["usage"]["prompt_tokens"], d["usage"]["completion_tokens"], d["latency_ms"])
                except (OSError, ValueError, KeyError, TypeError):
                    continue  # being written or unreadable: the next refresh tries again
        return sorted(self._calls.values(), key=lambda c: c.ts)


def _pct(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[round(q * 100) - 1]


def _rollup(calls: Iterable[Call], now: float) -> dict:
    calls = list(calls)
    return {
        "calls": len(calls),
        "prompt_tokens": sum(c.prompt_tokens for c in calls),
        "completion_tokens": sum(c.completion_tokens for c in calls),
        "tokens": sum(c.tokens for c in calls),
        "tokens_24h": sum(c.tokens for c in calls if now - c.ts < DAY_S),
        "calls_24h": sum(now - c.ts < DAY_S for c in calls),
        "latency_p50_ms": _pct([c.latency_ms for c in calls], 0.5),
        "latency_p95_ms": _pct([c.latency_ms for c in calls], 0.95),
    }


def series_order(calls: Sequence[Call]) -> list[str]:
    """Models by first use: a model keeps its color whatever range is shown. Past the palette, "Other"."""
    models = list(dict.fromkeys(c.model for c in calls))
    return models if len(models) <= MAX_SERIES else [*models[: MAX_SERIES - 1], "Other"]


def usage_summary(calls: Sequence[Call], now: float, days: int = 0) -> dict:
    """`days` limits only the per-day chart (0 = all); tiles and tables always cover everything."""
    series = series_order(calls)
    per_day: dict[str, Counter] = defaultdict(Counter)
    for c in calls:
        name = c.model if c.model in series else "Other"
        per_day[datetime.fromtimestamp(c.ts).date().isoformat()][name] += c.tokens

    today = datetime.fromtimestamp(now).date()
    first = datetime.fromtimestamp(calls[0].ts).date() if calls else today
    start = max(first, today - timedelta(days=days - 1)) if days else first
    day_list = [(start + timedelta(days=i)).isoformat() for i in range((today - start).days + 1)]

    by_model: dict[str, list[Call]] = defaultdict(list)
    by_kind: dict[str, list[Call]] = defaultdict(list)
    for c in calls:
        by_model[c.model].append(c)
        by_kind[c.kind].append(c)
    hosted = [c for c in calls if not c.local]
    local = [c for c in calls if c.local]
    return {
        "series": series,
        "days": [{"day": d, "tokens": {s: per_day[d][s] for s in series}} for d in day_list],
        "hosted": _rollup(hosted, now),
        "local": _rollup(local, now),
        "total": _rollup(calls, now),
        "models": [{"model": m, "provider": cs[0].provider, "limit": DAILY_TOKEN_LIMITS.get(m), **_rollup(cs, now)}
                   for m, cs in by_model.items()],
        "kinds": sorted(({"kind": k, **_rollup(cs, now)} for k, cs in by_kind.items()), key=lambda r: -r["tokens"]),
        "recent": [{"ts": c.ts, "provider": c.provider, "model": c.model, "kind": c.kind, "prompt_tokens": c.prompt_tokens,
                    "completion_tokens": c.completion_tokens, "latency_ms": c.latency_ms}
                   for c in reversed(calls[-RECENT_CALLS:])],
    }


def tail_lines(path: Path, n: int = LOG_TAIL_LINES) -> list[str]:
    with path.open(encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\n") for line in deque(f, maxlen=n)]


def _turn(row: dict) -> dict:
    generations = row.get("generations") or []
    spans = sorted(row.get("spans") or [], key=lambda s: s.get("start", 0))
    meta = row.get("metadata") or {}
    return {
        "ts": row.get("start"), "question": row.get("input", ""), "answer": row.get("output", ""), "ms": row.get("ms"),
        "id": meta.get("id"), "model": meta.get("model"), "abstained": meta.get("abstained"),
        "nodes": [{"name": s.get("name"), "ms": round((s.get("end", 0) - s.get("start", 0)) * 1000, 1)} for s in spans],
        "tokens": sum(g.get("prompt_tokens", 0) + g.get("completion_tokens", 0) for g in generations),
        "cached": bool(generations) and all(g.get("cached") for g in generations),
    }


def recent_turns(directory: Path, n: int = RECENT_TURNS) -> list[dict]:
    """The latest agent turns across trace files; a file is read from its end, so size doesn't matter."""
    rows: list[dict] = []
    for path in directory.glob("*.jsonl"):
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - TRACE_TAIL_BYTES))
            for line in f.read().splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue  # a partial first line, or one being written
    rows.sort(key=lambda r: r.get("start") or 0, reverse=True)
    return [_turn(r) for r in rows[:n]]


def running_processes() -> list[dict]:
    """FinRAG Python processes, so the page can say an eval is still going. Empty where `ps` doesn't exist."""
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,etime=,command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or parts[2].startswith(("/bin/", "zsh", "bash", "sh ")) or "app.dashboard" in parts[2]:
            continue
        if match := _PROCESS.search(parts[2]):
            found.append({"pid": int(parts[0]), "elapsed": parts[1], "name": match.group(1) or "API server"})
    return found


def log_files(extra: Sequence[Path], directory: Path) -> dict[str, Path]:
    """Every log the page may read, by name: requests can only choose from this list."""
    paths = [*extra, *sorted(directory.glob("*.log"))]
    return {p.name: p for p in paths if p.is_file()}


def create_app(cache_dir: Path, trace_dir: Path, log_dir: Path, extra_logs: Sequence[Path] = ()) -> FastAPI:
    app = FastAPI(title="FinRAG dashboard", docs_url=None, redoc_url=None)
    ledger = Ledger(cache_dir)

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.get("/api/data")
    def data(days: int = Query(default=30, ge=0, le=3650)) -> dict:
        now = time.time()
        return {"now": now, "usage": usage_summary(ledger.calls(), now, days), "turns": recent_turns(trace_dir),
                "running": running_processes(), "logs": sorted(log_files(extra_logs, log_dir))}

    @app.get("/api/log")
    def log(name: str) -> dict:
        path = log_files(extra_logs, log_dir).get(name)
        if path is None:
            raise HTTPException(status_code=404, detail="Unknown log")
        return {"name": name, "lines": tail_lines(path), "modified": path.stat().st_mtime}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--log", type=Path, nargs="*", default=[], help="extra log files to show")
    args = parser.parse_args()

    import uvicorn

    data_dir = PROJECT_ROOT / "data"
    get_settings()  # a broken .env should fail here, not on the first refresh
    app = create_app(data_dir / "cache" / "llm", data_dir / "traces", data_dir / "logs", args.log)
    print(f"FinRAG dashboard: http://127.0.0.1:{args.port}")
    # Localhost only: logs and traces hold questions and answers, and there is no login.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
