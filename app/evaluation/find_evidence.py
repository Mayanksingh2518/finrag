"""Authoring aid for the golden set: grep filing pages, show where a phrase occurs.

Searches page text (not the retriever), so gold labels don't inherit retriever bias.

Usage:
    python -m app.evaluation.find_evidence "services net sales" --tickers AAPL --years 2025
    python -m app.evaluation.find_evidence "Azure.*grew" --regex --context 300
"""

import argparse
import re

from app.config import get_settings
from app.evaluation.golden import load_pages, normalize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pattern")
    parser.add_argument("--tickers", nargs="*")
    parser.add_argument("--years", nargs="*", type=int)
    parser.add_argument("--regex", action="store_true", help="treat pattern as a regex (default: literal)")
    parser.add_argument("--context", type=int, default=160, help="characters shown around each match")
    parser.add_argument("--max", type=int, default=20, help="maximum matches to print")
    args = parser.parse_args()

    pages = load_pages(get_settings().processed_dir / "pages.jsonl")
    pattern = args.pattern if args.regex else re.escape(normalize(args.pattern))
    rx = re.compile(pattern, re.IGNORECASE)
    shown = 0
    for (ticker, year, index), page in sorted(pages.items()):
        if args.tickers and ticker not in args.tickers or args.years and year not in args.years:
            continue
        text = normalize(page.text)
        for m in rx.finditer(text):
            lo, hi = max(0, m.start() - args.context), m.end() + args.context
            print(f"--- {ticker} FY{year} page {index} (printed {page.label}) ---\n...{text[lo:hi]}...\n")
            shown += 1
            if shown >= args.max:
                return
    print(f"{shown} match(es)")


if __name__ == "__main__":
    main()
