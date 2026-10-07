"""Ad-hoc search from the terminal.

Usage:
    python -m app.retrieval.search_cli "How did Apple's services revenue change?" --tickers AAPL
    python -m app.retrieval.search_cli "NVIDIA supply chain risks" --tickers NVDA --years 2022 --sections "Item 1A"
    python -m app.retrieval.search_cli "cloud revenue growth" --mode bm25 -k 5
"""

import argparse
import logging

from app.retrieval.factory import build_retriever
from app.retrieval.types import SEARCH_MODES, SearchFilters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query")
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--years", type=int, nargs="+")
    parser.add_argument("--sections", nargs="+", help='e.g. "Item 7" "Item 1A"')
    parser.add_argument("--types", nargs="+", choices=["text", "table"])
    parser.add_argument("--mode", choices=SEARCH_MODES, default="hybrid_rerank")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--chars", type=int, default=300, help="characters of text to show per hit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    retriever = build_retriever(with_reranker=args.mode == "hybrid_rerank")
    filters = SearchFilters(
        tickers=tuple(args.tickers) if args.tickers else None,
        fiscal_years=tuple(args.years) if args.years else None,
        sections=tuple(args.sections) if args.sections else None,
        chunk_types=tuple(args.types) if args.types else None,
    )
    result = retriever.search(args.query, filters, k=args.k, mode=args.mode)

    print(f"\n{args.mode} | {result.timings_ms}\n")
    for i, hit in enumerate(result.hits, start=1):
        c = hit.chunk
        page = c.page_label_start or f"#{c.page_start}"
        print(f"[{i}] {c.ticker} FY{c.fiscal_year} | {c.section} | p.{page} | {c.chunk_type} | score={hit.score:.3f}")
        if c.subsection:
            print(f"    {c.subsection[:100]}")
        print("    " + c.text[: args.chars].replace("\n", "\n    ") + "\n")


if __name__ == "__main__":
    main()
