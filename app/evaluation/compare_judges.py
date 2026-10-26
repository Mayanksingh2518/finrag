"""Compare two judges on the same answers (two `run_judge_eval` reports).

A judge from the same model family as the generator may favour its answers, so routed answers
(trend/comparison by Groq gpt-oss-120b) are also judged by a second model (qwen on Groq, separate
per-model quota). This shows how far the two judges agree, so a metric is only trusted where they do.

Usage:
    python -m app.evaluation.compare_judges reports/judge_v1.json reports/judge_v1_qwen.json
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from app.config import PROJECT_ROOT

GRADES = ("correct", "partially_correct", "incorrect")


def load(path: Path) -> dict[str, dict]:
    return {r["id"]: r for r in json.loads(path.read_text())["records"]}


def compare(a: dict[str, dict], b: dict[str, dict]) -> dict:
    both = [i for i in a if i in b and a[i]["judged"] and b[i]["judged"] and a[i]["answer"] == b[i]["answer"]]
    by_cat: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for i in a:
        if i in b and a[i]["answerable"] and not a[i]["error"] and not b[i]["error"]:
            by_cat[a[i]["category"]].append((a[i]["correctness_score"], b[i]["correctness_score"]))
    return {
        "judged_by_both": len(both),
        "exact": sum(a[i]["correctness"] == b[i]["correctness"] for i in both) / len(both) if both else float("nan"),
        "binary": (sum((a[i]["correctness"] == "correct") == (b[i]["correctness"] == "correct") for i in both) / len(both)
                   if both else float("nan")),
        "confusion": {g: {h: sum(a[i]["correctness"] == g and b[i]["correctness"] == h for i in both) for h in GRADES}
                      for g in GRADES},
        "by_category": {c: (sum(x for x, _ in v) / len(v), sum(y for _, y in v) / len(v), len(v))
                        for c, v in sorted(by_cat.items())},
        "disagreements": [(i, a[i]["correctness"], b[i]["correctness"], b[i]["reason"]) for i in both
                          if a[i]["correctness"] != b[i]["correctness"]],
    }


def render(c: dict, name_a: str, name_b: str) -> str:
    lines = [f"# Judge agreement: {name_a} vs {name_b}", "",
             f"Same answers judged by both: {c['judged_by_both']}. Exact agreement **{c['exact']:.2f}**, "
             f"correct vs not-correct **{c['binary']:.2f}**.", "",
             f"| {name_a} \\ {name_b} | " + " | ".join(GRADES) + " |", "|---|---|---|---|"]
    lines += [f"| {g} | " + " | ".join(str(c["confusion"][g][h]) for h in GRADES) + " |" for g in GRADES]
    lines += ["", "| Category | n | " + f"{name_a} | {name_b} |", "|---|---|---|---|"]
    lines += [f"| {cat} | {n} | {x:.3f} | {y:.3f} |" for cat, (x, y, n) in c["by_category"].items()]
    lines += ["", "Disagreements:", ""]
    lines += [f"- {i}: {x} vs {y}: {reason[:220]}" for i, x, y, reason in c["disagreements"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    parser.add_argument("--out", type=Path, help="markdown report (default: print only)")
    args = parser.parse_args()
    report = render(compare(load(args.a), load(args.b)), args.a.stem, args.b.stem)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
