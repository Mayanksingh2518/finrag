"""Deterministic extraction of companies, fiscal years and sections from a question.

The corpus is closed (10 companies, FY2022-FY2025), so names, brands and year phrases are
matched with rules: instant, free, testable, and never invents a filter. The LLM is only used
for what rules can't do well (rewriting follow-ups, see `analyze.py`).

Year conventions: a year in the question is taken as the company's own fiscal-year label
("fiscal 2025", "in 2025"), matching how filings are indexed (see `companies.py`).
"""

import re
from dataclasses import dataclass

from app.ingestion.companies import COMPANIES

CORPUS_YEARS: tuple[int, ...] = (2022, 2023, 2024, 2025)

# Names, brands, products and segments that identify a company. Matched case-insensitively on
# word boundaries; longer aliases first so "Google Cloud" isn't also read as a bare "Google".
ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("apple", "iphone", "ipad", "macbook", "app store", "applecare", "aapl"),
    "MSFT": ("microsoft", "azure", "activision", "linkedin", "xbox", "microsoft cloud", "intelligent cloud",
             "github", "msft"),
    "NVDA": ("nvidia", "geforce", "blackwell", "hopper", "cuda", "nvda"),
    "AMZN": ("amazon", "aws", "amazon web services", "amzn"),
    "GOOGL": ("alphabet", "google", "youtube", "waymo", "google cloud", "googl"),
    "META": ("meta", "facebook", "instagram", "whatsapp", "reality labs", "family of apps"),
    "TSLA": ("tesla", "cybertruck", "robotaxi", "model y", "model 3", "tsla"),
    "JPM": ("jpmorgan", "jp morgan", "jpmorgan chase", "chase", "jpm"),
    "V": ("visa",),
    "MA": ("mastercard",),
}

_ALIAS_RE = [
    (ticker, re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE))
    for ticker, aliases in ALIASES.items()
    for alias in sorted(aliases, key=len, reverse=True)
]
assert set(ALIASES) == set(COMPANIES), "every corpus company needs aliases"

# Section cues strong enough to filter on (a wrong section filter hides the answer, so only
# unambiguous ones): risk questions -> Item 1A, cybersecurity governance -> Item 1C.
_SECTION_CUES = [
    ("Item 1A", re.compile(r"\brisks?\b|\brisk factors?\b", re.IGNORECASE)),
    ("Item 1C", re.compile(r"\bcybersecurity\b", re.IGNORECASE)),
]

_YEAR = re.compile(r"(?<![\d$.,])(19\d{2}|20\d{2})(?!\d|,\d|\.\d|%)")  # not 1,990 / $2025 / 2025.5 / 20%
_RANGE = re.compile(r"\b(?:from|between)\s+(?:fiscal\s+(?:year\s+)?)?(20\d{2})\s+(?:to|and|through|-)\s+"
                    r"(?:fiscal\s+(?:year\s+)?)?(20\d{2})\b", re.IGNORECASE)
_LAST_N = re.compile(r"\b(?:last|past|previous)\s+(two|three|four|2|3|4)\s+(?:fiscal\s+)?years\b", re.IGNORECASE)
_LATEST = re.compile(r"\b(?:latest|most recent|this)\s+(?:fiscal\s+)?year\b|\blatest\b", re.IGNORECASE)
_PRIOR = re.compile(r"\b(?:the\s+)?(?:year|fiscal year)\s+before\b|\bprior\s+year\b|\bprevious\s+year\b", re.IGNORECASE)
_SAME = re.compile(r"\b(?:that|the same)\s+(?:fiscal\s+)?year\b", re.IGNORECASE)
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4}


@dataclass(frozen=True)
class Entities:
    tickers: tuple[str, ...]  # in order of first mention
    fiscal_years: tuple[int, ...]  # sorted, within the corpus
    sections: tuple[str, ...]
    out_of_range_years: tuple[int, ...]  # explicit years the corpus doesn't cover, e.g. 2018, 2027
    relative_year: str | None = None  # "prior" / "same" when the year must come from the conversation


def find_tickers(text: str) -> tuple[str, ...]:
    hits: list[tuple[int, str]] = []
    for ticker, pattern in _ALIAS_RE:
        if m := pattern.search(text):
            hits.append((m.start(), ticker))
    return tuple(dict.fromkeys(t for _, t in sorted(hits)))


def find_years(text: str) -> tuple[tuple[int, ...], tuple[int, ...], str | None]:
    """(corpus years, out-of-range years, relative marker) mentioned in the text."""
    years: set[int] = set()
    for m in _RANGE.finditer(text):
        lo, hi = sorted((int(m.group(1)), int(m.group(2))))
        years.update(range(lo, hi + 1))
    years.update(int(y) for y in _YEAR.findall(text))
    if m := _LAST_N.search(text):
        n = _NUMBER_WORDS.get(m.group(1).lower()) or int(m.group(1))
        years.update(CORPUS_YEARS[-n:])
    elif _LATEST.search(text) and not years:
        years.add(CORPUS_YEARS[-1])
    relative = "prior" if _PRIOR.search(text) else "same" if _SAME.search(text) else None
    inside = tuple(sorted(y for y in years if y in CORPUS_YEARS))
    outside = tuple(sorted(y for y in years if y not in CORPUS_YEARS))
    return inside, outside, relative


def find_sections(text: str) -> tuple[str, ...]:
    return tuple(section for section, cue in _SECTION_CUES if cue.search(text))


def extract(text: str) -> Entities:
    years, outside, relative = find_years(text)
    return Entities(find_tickers(text), years, find_sections(text), outside, relative)
