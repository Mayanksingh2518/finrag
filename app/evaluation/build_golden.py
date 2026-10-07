"""Resolve gold pages from quotes, validate the golden set and rewrite it in place.

Authors write evidence as (ticker, fiscal_year, quotes); this fills `pages` with every
page of that filing containing a quote, so labels never depend on the retriever.
Fails when a quote matches no page, and warns when it matches many (not distinctive).

Usage:
    python -m app.evaluation.build_golden                # fill missing pages, validate
    python -m app.evaluation.build_golden --refresh      # re-resolve all pages (after re-ingestion)
"""

import argparse
import collections
import json
import sys
from pathlib import Path

from app.config import PROJECT_ROOT, get_settings
from app.evaluation.golden import load_golden, load_pages, resolve_pages, validate

DEFAULT_PATH = PROJECT_ROOT / "data" / "eval" / "golden_v0.jsonl"
MAX_PAGES = 6  # more matches than this suggests the quote is not distinctive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--refresh", action="store_true", help="re-resolve pages that are already filled")
    args = parser.parse_args()

    pages = load_pages(get_settings().processed_dir / "pages.jsonl")
    rows = [json.loads(line) for line in args.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors: list[str] = []
    for row in rows:
        for e in row.get("evidence", []):
            if e.get("pages") and not args.refresh:
                continue
            found = resolve_pages(e["ticker"], int(e["fiscal_year"]), e["quotes"], pages)
            if not found:
                errors.append(f"{row['id']}: no page of {e['ticker']} FY{e['fiscal_year']} contains {e['quotes']}")
            elif len(found) > MAX_PAGES:
                print(f"warning {row['id']}: {e['quotes'][0][:40]!r} matches {len(found)} pages", file=sys.stderr)
            e["pages"] = list(found)

    args.path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    questions = load_golden(args.path)
    errors += validate(questions, pages)
    counts = collections.Counter(q.category for q in questions)
    print(f"{len(questions)} questions: " + ", ".join(f"{c} {n}" for c, n in sorted(counts.items())))
    print(f"{sum(len(q.evidence) for q in questions)} evidence items, "
          f"{len({t for q in questions for t in (e.ticker for e in q.evidence)})} companies, "
          f"years {sorted({e.fiscal_year for q in questions for e in q.evidence})}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)
    print("OK: every quote found on every listed page")


if __name__ == "__main__":
    main()
