"""Eval regression gate: fail when a headline metric in the committed reports falls below its threshold.

CI can't regenerate the evaluation (it needs the filings, local models and LLM quota), but every result
is a committed report. This checks those reports against `reports/gate.json`, so a change that
regenerates a report with worse numbers, or deletes one, fails the build. Standard library only: the CI
job installs nothing.

Metric references in gate.json:
    retrieval:<run name>:<gold|none>:<metric>   mean over the run's questions in retrieval_v1.json
    plan:<config>:<key>                         a config summary in plan_v0.json
    summary:<report>:<dotted.path>              a value in <report>.json's "summary"

Usage:
    python -m app.evaluation.check_gate          # exit 1 on any failure; markdown table on stdout
"""

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[2] / "reports"
RETRIEVAL_REPORT = "retrieval_v1"  # current gold labels (v0 predates the Phase 5 gold review)


class MetricError(Exception):
    """The report or the metric a check refers to doesn't exist."""


@dataclass
class Result:
    label: str
    metric: str
    value: float | None
    bound: str  # ">= 0.87" or "<= 0.06"
    passed: bool
    error: str = ""


def _report(directory: Path, name: str) -> dict:
    path = directory / f"{name}.json"
    if not path.exists():
        raise MetricError(f"missing report {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(metric: str, directory: Path = REPORTS) -> float:
    kind, _, rest = metric.partition(":")
    if kind == "retrieval":
        run_name, filters, key = rest.split(":")
        runs = [r for r in _report(directory, RETRIEVAL_REPORT)["runs"]
                if r["name"] == run_name and r["filtered"] == (filters == "gold")]
        if not runs or not runs[0]["questions"]:
            raise MetricError(f"no retrieval run {run_name!r} with filters={filters}")
        try:
            return statistics.fmean(q["metrics"][key] for q in runs[0]["questions"])
        except KeyError:
            raise MetricError(f"retrieval metric {key!r} not found") from None
    if kind == "plan":
        config, _, key = rest.rpartition(":")
        try:
            return float(_report(directory, "plan_v0")[config]["summary"][key])
        except KeyError:
            raise MetricError(f"plan config {config!r} or key {key!r} not found") from None
    if kind == "summary":
        name, _, path = rest.partition(":")
        value = _report(directory, name).get("summary", {})
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                raise MetricError(f"{name}.json has no summary.{path}")
            value = value[part]
        if not isinstance(value, (int, float)) or value != value:  # NaN fails too
            raise MetricError(f"{name}.json summary.{path} is not a number: {value!r}")
        return float(value)
    raise MetricError(f"unknown metric kind {kind!r}")


def check(gate: dict, directory: Path = REPORTS) -> list[Result]:
    results = []
    for c in gate["checks"]:
        bound = f">= {c['min']}" if "min" in c else f"<= {c['max']}"
        try:
            value = resolve(c["metric"], directory)
        except MetricError as e:
            results.append(Result(c["label"], c["metric"], None, bound, False, str(e)))
            continue
        passed = (value >= c["min"] if "min" in c else True) and (value <= c["max"] if "max" in c else True)
        results.append(Result(c["label"], c["metric"], value, bound, passed))
    return results


def render(results: list[Result]) -> str:
    failed = sum(not r.passed for r in results)
    lines = [f"## Eval gate: {'FAILED' if failed else 'passed'} ({len(results) - failed}/{len(results)})", "",
             "| | Check | Value | Threshold |", "|---|---|---|---|"]
    for r in results:
        value = r.error if r.error else f"{r.value:.3f}"
        lines.append(f"| {'✅' if r.passed else '❌'} | {r.label} | {value} | {r.bound} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gate", type=Path, default=REPORTS / "gate.json")
    parser.add_argument("--reports", type=Path, default=REPORTS)
    args = parser.parse_args()
    results = check(json.loads(args.gate.read_text(encoding="utf-8")), args.reports)
    table = render(results)
    print(table, end="")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):  # shown on the workflow run page
        with open(summary, "a", encoding="utf-8") as f:
            f.write(table)
    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
