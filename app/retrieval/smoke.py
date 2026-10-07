"""Qualitative smoke test: target questions x all retrieval modes.

Filters mimic what the Phase 6 query analyzer will produce (company, year,
section); comparisons are already decomposed into one query per company.
Each query lists keywords that a useful top-3 hit must contain. This is a
sanity check, not the evaluation (that is Phase 4's labelled golden set).

Usage:
    python -m app.retrieval.smoke
"""

import logging
import statistics
from dataclasses import dataclass

from app.retrieval.factory import build_retriever
from app.retrieval.types import SEARCH_MODES, SearchFilters


@dataclass(frozen=True)
class SmokeQuery:
    query: str
    filters: SearchFilters
    must_contain: tuple[str, ...]


QUERIES = [
    SmokeQuery("How did Apple's services revenue change?", SearchFilters(("AAPL",), (2022,)), ("services", "net sales")),
    SmokeQuery("How did Apple's services revenue change?", SearchFilters(("AAPL",), (2025,)), ("services", "net sales")),
    SmokeQuery("Microsoft cloud business revenue growth drivers", SearchFilters(("MSFT",), (2025,)), ("azure",)),
    SmokeQuery("Amazon cloud business revenue growth drivers", SearchFilters(("AMZN",), (2025,)), ("aws",)),
    SmokeQuery("What are NVIDIA's major risks?", SearchFilters(("NVDA",), (2022,), ("Item 1A",)), ("risk",)),
    SmokeQuery("NVIDIA export controls China data center", SearchFilters(("NVDA",), (2025,)), ("export",)),
    SmokeQuery("Why did Visa's international transaction revenue change?", SearchFilters(("V",), (2025,)), ("international transaction revenue", "cross-border")),
    SmokeQuery("Mastercard net revenue growth", SearchFilters(("MA",), (2025,)), ("net revenue", "increase")),
    SmokeQuery("JPMorgan net interest income", SearchFilters(("JPM",), (2025,)), ("net interest income",)),
    SmokeQuery("Tesla automotive gross margin", SearchFilters(("TSLA",), (2024,)), ("gross margin", "automotive")),
    # Unfiltered: the retriever must find the right company on its own.
    SmokeQuery("Which company's data center GPU sales are restricted by US export controls?", SearchFilters(), ("export",)),
    SmokeQuery("Meta Reality Labs operating loss", SearchFilters(), ("reality labs",)),
]


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    retriever = build_retriever(with_reranker=True)
    retriever.search("warm up", k=1)  # load model weights / caches before timing

    passed = {m: 0 for m in SEARCH_MODES}
    latency = {m: [] for m in SEARCH_MODES}
    for q in QUERIES:
        f = q.filters
        print(f"\n=== {q.query}  [{','.join(f.tickers or ['*'])} {','.join(map(str, f.fiscal_years or ['*']))} "
              f"{','.join(f.sections or [])}]  must contain: {q.must_contain}")
        for mode in SEARCH_MODES:
            result = retriever.search(q.query, f, k=3, mode=mode)
            ok = any(all(kw in h.chunk.embed_text.lower() for kw in q.must_contain) for h in result.hits)
            passed[mode] += ok
            latency[mode].append(result.timings_ms["total"])
            top = result.hits[0].chunk if result.hits else None
            where = f"{top.ticker} FY{top.fiscal_year} {top.section} p.{top.page_label_start} {top.chunk_type}" if top else "-"
            print(f"  {'PASS' if ok else 'miss'} {mode:<14} {result.timings_ms['total']:>7.0f} ms | top: {where}")

    print("\nSummary (top-3 contains required evidence):")
    for mode in SEARCH_MODES:
        lat = sorted(latency[mode])
        print(f"  {mode:<14} {passed[mode]}/{len(QUERIES)} | latency p50 {statistics.median(lat):.0f} ms, max {lat[-1]:.0f} ms")


if __name__ == "__main__":
    main()
