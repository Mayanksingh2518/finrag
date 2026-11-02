"""Deterministic extraction of companies, fiscal years and sections from a question.

The corpus is closed (10 companies, FY2022-FY2025), so names, brands and year phrases are
matched with rules: instant, free, testable, and never invents a filter. The LLM is only used
for what rules can't do well (rewriting follow-ups, see `analyze.py`).

Year conventions: a year in the question is taken as the company's own fiscal-year label
("fiscal 2025", "in 2025"), matching how filings are indexed (see `companies.py`). The same goes for
quarters ("Q3 2025" is Q3 of fiscal 2025); only a period-end date ("three months ended October 27, 2024")
is calendar time, and it is converted with the company's fiscal calendar.
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
_SHORT_YEAR = re.compile(r"(?:(?<![A-Za-z])FY\s?'?|\bQ[1-4]\s?'|\b[1-4]Q\s?'?)(\d{2})\b", re.IGNORECASE)  # FY25, Q3'24, 3Q24

ALL_QUARTERS: tuple[int, ...] = (1, 2, 3, 4)
_QUARTER_WORDS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}
_QUARTER = re.compile(r"\bQ([1-4])(?=\b|FY)|\b([1-4])Q(?:\d{2})?\b|\b(first|second|third|fourth|1st|2nd|3rd|4th)[- ]quarter\b",
                      re.IGNORECASE)
# "quarterly dividend" is a 10-K topic: it doesn't ask for results by quarter.
_BY_QUARTER = re.compile(r"\bquarterly\b(?!\s+(?:cash\s+)?dividends?)|\b(?:each|every|by|per)\s+(?:fiscal\s+)?quarter\b|"
                         r"\bquarter[- ](?:over|by|to)[- ]quarter\b|\b(?:last|past)\s+four\s+quarters\b", re.IGNORECASE)
_RELEASE_CUE = re.compile(r"\b(?:earnings|press|results)\s+release\b|\bearnings\s+(?:report|announcement)\b|"
                          r"\bthree months ended\b|\bquarter ended\b", re.IGNORECASE)
_GUIDANCE = re.compile(r"\bguidance\b|\boutlook\b|\bguid(?:e|ed|ing)\b|\bforecast|\bexpect(?:ed|s)?\b", re.IGNORECASE)
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
_QUARTER_DATE = re.compile(rf"\b(?:three months|quarter)\s+ended\s+({'|'.join(_MONTHS)})\s+(?:(\d{{1,2}}),?\s+)?(20\d{{2}})\b",
                           re.IGNORECASE)
_FISCAL_YEAR_END_MONTH = {"AAPL": 9, "MSFT": 6, "NVDA": 1, "V": 9}  # the rest end in December


@dataclass(frozen=True)
class Entities:
    tickers: tuple[str, ...]  # in order of first mention
    fiscal_years: tuple[int, ...]  # sorted, within the corpus
    sections: tuple[str, ...]
    out_of_range_years: tuple[int, ...]  # explicit years the corpus doesn't cover, e.g. 2018, 2027
    relative_year: str | None = None  # "prior" / "same" when the year must come from the conversation
    fiscal_quarters: tuple[int, ...] = ()
    release: bool = False  # the question is about earnings releases, with or without a named quarter


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
    years.update(2000 + int(y) for y in _SHORT_YEAR.findall(text))
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


def find_quarters(text: str) -> tuple[int, ...]:
    """Quarters named in the text; all four for "quarterly revenue", "each quarter"."""
    named = {int(m.group(1) or m.group(2) or _QUARTER_WORDS[m.group(3).lower()]) for m in _QUARTER.finditer(text)}
    return tuple(sorted(named)) or (ALL_QUARTERS if _BY_QUARTER.search(text) else ())


def fiscal_period_of(ticker: str, month: int, day: int, year: int) -> tuple[int, int]:
    """(fiscal year, quarter) of a period-end date. 52/53-week years can end in the first days of the next month."""
    if day <= 7:
        month, year = (month - 1, year) if month > 1 else (12, year - 1)
    end = _FISCAL_YEAR_END_MONTH.get(ticker, 12)
    return (year if month <= end else year + 1), (month - end - 1) % 12 // 3 + 1


def _guidance_scope(quarter: int, years: tuple[int, ...], outside: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    """A quarter's outlook is in the previous quarter's release, and only there: the quarter's own release
    states the outlook for the quarter after it, a wrong figure the verifier can't catch."""
    if quarter > 1:
        return (quarter - 1,), years, outside
    previous = {y - 1 for y in (*years, *outside)}
    return (4,), tuple(sorted(y for y in previous if y in CORPUS_YEARS)), tuple(sorted(y for y in previous if y not in CORPUS_YEARS))


def extract(text: str) -> Entities:
    years, outside, relative = find_years(text)
    tickers = find_tickers(text)
    quarters = find_quarters(text)
    if (date := _QUARTER_DATE.search(text)) and len(tickers) == 1:
        month, day, year = _MONTHS.index(date.group(1).lower()) + 1, int(date.group(2) or 15), int(date.group(3))
        fiscal_year, quarter = fiscal_period_of(tickers[0], month, day, year)
        quarters = (quarter,)
        in_corpus = fiscal_year in CORPUS_YEARS
        years = tuple(sorted({y for y in years if y != year} | ({fiscal_year} if in_corpus else set())))
        outside = tuple(y for y in outside if y != year) + (() if in_corpus else (fiscal_year,))
    elif len(quarters) == 1 and _GUIDANCE.search(text) and not _RELEASE_CUE.search(text):  # "outlook in the Q3 release" means Q3's
        quarters, years, outside = _guidance_scope(quarters[0], years, outside)
    release = bool(quarters or _RELEASE_CUE.search(text))
    return Entities(tickers, years, () if release else find_sections(text), outside, relative, quarters, release)
