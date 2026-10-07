"""Ask a question from the terminal and get a cited, verified answer.

Usage:
    python -m app.generation.ask_cli "Why did Apple's Services net sales increase?" --tickers AAPL --years 2025
    python -m app.generation.ask_cli "Compare Azure and AWS growth" --tickers MSFT AMZN --years 2025
"""

import argparse
import logging

from app.config import get_settings
from app.generation.answer import Answerer
from app.generation.llm import build_llm
from app.retrieval.factory import build_retriever
from app.retrieval.types import SearchFilters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--years", type=int, nargs="+")
    parser.add_argument("--sections", nargs="+")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    settings = get_settings()
    answerer = Answerer(build_retriever(settings), build_llm(settings), token_budget=settings.context_token_budget)
    filters = SearchFilters(tuple(args.tickers) if args.tickers else None,
                            tuple(args.years) if args.years else None,
                            tuple(args.sections) if args.sections else None)
    r = answerer.answer(args.question, filters)

    print(f"\n{'ABSTAINED: ' + r.abstain_reason if r.abstained else r.answer}\n")
    print(f"confidence: {r.confidence} | {r.provider} {r.model}{' (cached)' if r.cached else ''} | "
          f"tokens {r.usage} | {r.timings_ms}")
    for c in r.claims:
        mark = "✓" if c.supported else "✗"
        extra = f" (not in source: {', '.join(c.unsupported_numbers)})" if c.unsupported_numbers else ""
        print(f"  {mark} {c.text} {c.source_ids} {c.status}{extra}")
    print("sources:", ", ".join(f"{s.id}={s.citation}" for s in r.sources))


if __name__ == "__main__":
    main()
