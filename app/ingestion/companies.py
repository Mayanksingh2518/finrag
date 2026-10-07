"""Registry of the companies in the FinRAG corpus.

CIK (Central Index Key) is the SEC's stable company identifier; tickers and
names can change, CIKs do not.

Fiscal years are labelled the way each company labels them. EDGAR's
``reportDate`` (period end) year matches that label for all ten companies,
e.g. NVIDIA's FY2025 ended 2025-01-26 and Microsoft's FY2025 ended 2025-06-30.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Company:
    ticker: str
    name: str
    cik: int
    sector: str
    fiscal_year_end: str  # human-readable, informational only


COMPANIES: dict[str, Company] = {
    c.ticker: c
    for c in [
        Company("AAPL", "Apple Inc.", 320193, "Technology", "last Saturday of September"),
        Company("MSFT", "Microsoft Corporation", 789019, "Technology", "June 30"),
        Company("NVDA", "NVIDIA Corporation", 1045810, "Semiconductors", "last Sunday of January"),
        Company("AMZN", "Amazon.com, Inc.", 1018724, "Consumer / Cloud", "December 31"),
        Company("GOOGL", "Alphabet Inc.", 1652044, "Technology", "December 31"),
        Company("META", "Meta Platforms, Inc.", 1326801, "Technology", "December 31"),
        Company("TSLA", "Tesla, Inc.", 1318605, "Automotive / Energy", "December 31"),
        Company("JPM", "JPMorgan Chase & Co.", 19617, "Banking", "December 31"),
        Company("V", "Visa Inc.", 1403161, "Payments", "September 30"),
        Company("MA", "Mastercard Incorporated", 1141391, "Payments", "December 31"),
    ]
}


def get_company(ticker: str) -> Company:
    try:
        return COMPANIES[ticker.upper()]
    except KeyError:
        raise KeyError(f"Unknown ticker {ticker!r}; known: {sorted(COMPANIES)}") from None
