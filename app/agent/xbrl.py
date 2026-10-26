"""XBRL company-facts tool: exact reported figures from SEC's structured financial data.

Retrieval struggles most with trend and comparison questions about headline figures (revenue,
net income for 4 years): the figure sits in a different note or table each year and a reranker
can rank an Item 8 note or a business overview above it. Every 10-K also tags those figures in
XBRL, and SEC serves them per company as one JSON
(`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`, free, same User-Agent rules).

Fact selection. A concept lists every value ever filed for it, by every filing, including prior
years shown as comparatives and later restatements. A fact is used only when it comes from the
fiscal year's own 10-K (`accn` from the manifest) and covers that fiscal year: period end within
a week of the filing's period end, duration ~1 year for flow metrics (income statement, cash
flow) or an instant for balance-sheet metrics. The `fy` field of a fact is not used: it is the
fiscal year of the filing, so a 2023 10-K labels its 2021 comparatives fy=2023 too.
The same filing's prior-year value gives the year-over-year change.

When the filing has no fact for any of the metric's concepts (NVIDIA tagged FY2022-23 capex with
a company-specific concept, which companyfacts omits), the value is taken from the next 10-K
that shows that period as a comparative, and the fact is marked `comparative`.

Each metric maps to a list of us-gaap concepts in priority order (companies tag the same line
differently: Apple "RevenueFromContractWithCustomer...", NVIDIA "Revenues", Mastercard's net
income "ProfitLoss"). The figure is the GAAP line item; it can differ from a company's own
narrative definition (Amazon's "cash capex" is net of incentives, Meta's capex includes finance
lease principal), so XBRL facts are an extra source next to the filing text, not a replacement.

Usage:
    python -m app.agent.xbrl --download          # fetch companyfacts for the 10 companies
    python -m app.agent.xbrl                     # coverage table: metric x company x year
    python -m app.agent.xbrl --ticker NVDA --metric revenue
"""

import argparse
import json
import logging
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cached_property
from pathlib import Path

from app.config import get_settings
from app.ingestion.companies import COMPANIES, get_company
from app.ingestion.models import Chunk

logger = logging.getLogger(__name__)

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

PERIOD_END_TOLERANCE_DAYS = 7  # 52/53-week years end on a weekday near the manifest's report date
YEAR_DAYS = (340, 380)


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    concepts: tuple[str, ...]  # us-gaap concepts, first match wins
    unit: str = "USD"
    instant: bool = False  # balance-sheet item (point in time) vs. flow over the fiscal year


METRICS: dict[str, Metric] = {m.key: m for m in [
    Metric("revenue", "Total revenue", ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                        "RevenuesNetOfInterestExpense", "SalesRevenueNet")),
    Metric("net_income", "Net income", ("NetIncomeLoss", "ProfitLoss")),
    Metric("operating_income", "Operating income", ("OperatingIncomeLoss",)),
    Metric("gross_profit", "Gross profit", ("GrossProfit",)),
    Metric("rnd", "Research and development expense", ("ResearchAndDevelopmentExpense",
                                                       "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost")),
    Metric("capex", "Purchases of property and equipment", ("PaymentsToAcquirePropertyPlantAndEquipment",
                                                            "PaymentsToAcquireProductiveAssets")),
    Metric("operating_cash_flow", "Net cash from operating activities", ("NetCashProvidedByUsedInOperatingActivities",)),
    Metric("buybacks", "Repurchases of common stock", ("PaymentsForRepurchaseOfCommonStock",)),
    Metric("eps_diluted", "Diluted earnings per share", ("EarningsPerShareDiluted",), unit="USD/shares"),
    Metric("total_assets", "Total assets", ("Assets",), instant=True),
    Metric("total_liabilities", "Total liabilities", ("Liabilities",), instant=True),
    Metric("stockholders_equity", "Stockholders' equity", (
        "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"), instant=True),
    Metric("cash", "Cash and cash equivalents", ("CashAndCashEquivalentsAtCarryingValue", "CashAndDueFromBanks"),
           instant=True),
]}


@dataclass(frozen=True)
class FilingPeriod:
    """The 10-K a fiscal year's facts must come from (a row of the downloader's manifest)."""
    ticker: str
    fiscal_year: int
    accession_number: str
    period_end: str  # ISO date
    filing_date: str
    source_url: str = ""


@dataclass(frozen=True)
class XbrlFact:
    ticker: str
    company: str
    fiscal_year: int
    metric: Metric
    concept: str
    concept_label: str  # SEC's label for the concept, e.g. "Revenues"
    value: float
    unit: str
    start: str | None
    end: str
    accession_number: str  # filing the value was taken from
    filed: str
    prior_value: float | None = None  # same filing's prior-year comparative
    comparative: bool = False  # True when taken from a later 10-K (own filing lacks the concept)
    source_url: str = ""

    @property
    def change_pct(self) -> float | None:
        if self.prior_value in (None, 0):
            return None
        return (self.value - self.prior_value) / abs(self.prior_value) * 100

    @property
    def citation(self) -> str:
        return f"[XBRL {self.ticker} FY{self.fiscal_year} {self.metric.label}]"

    def text(self) -> str:
        """One-line statement of the fact, worded like the filing (figures in millions, as tables are).

        The accession number stays in `to_chunk().metadata`: its digits would be noise for the verifier.
        """
        period = f"as of {self.end}" if self.metric.instant else f"fiscal year {self.fiscal_year} ({self.start} to {self.end})"
        line = f"{self.metric.label}, {period}: {format_value(self.value, self.unit)}"
        if self.prior_value is not None:
            line += f"; prior year: {format_value(self.prior_value, self.unit)}"
            if self.change_pct is not None:
                line += f"; change: {self.change_pct:+.1f}%"
        line += f". Source: XBRL us-gaap:{self.concept} ({self.concept_label})"
        line += (f", comparative in the next 10-K (filed {self.filed}); the fiscal {self.fiscal_year} 10-K does not tag it"
                 if self.comparative else f", Form 10-K for fiscal {self.fiscal_year}")
        return line + "."

    def to_chunk(self) -> Chunk:
        """Wrap the fact as a chunk so context building, the verifier and the UI handle it unchanged."""
        context = f"{self.company} ({self.ticker}) XBRL financial data, fiscal year {self.fiscal_year}"
        text = self.text()
        return Chunk(
            chunk_id=f"xbrl:{self.ticker}:{self.fiscal_year}:{self.metric.key}",
            doc_id=f"{self.ticker}_FY{self.fiscal_year}_10-K",
            ticker=self.ticker, company=self.company, fiscal_year=self.fiscal_year, form="10-K",
            filing_date=self.filed, period_end=self.end, part=None,
            section="XBRL", section_title=f"Company facts: {self.metric.label}", subsection=None,
            page_start=0, page_end=0, page_label_start=None, page_label_end=None,
            chunk_type="text", context=context, text=text,
            token_count=len(text.split()) * 2,  # rough; facts are tiny next to the context budget
            source_url=self.source_url,
            metadata={"concept": self.concept, "accession_number": self.accession_number,
                      "value": self.value, "unit": self.unit, "comparative": self.comparative},
        )


def direction(change_pct: float | None) -> str:
    """In words, computed here so the generator doesn't have to (a 3B model flips directions)."""
    if change_pct is None:
        return "-"
    return "up" if change_pct >= 1 else "down" if change_pct <= -1 else "flat"


def series_chunk(facts: Sequence[XbrlFact]) -> Chunk:
    """One table for a company's metric over several fiscal years: value, YoY change, direction.

    For trend questions the separate per-year facts left the model to line years up and work out
    directions; it dropped years and said "decreased from $37.7B to $57.0B" (reports/judge_v0.md).
    """
    facts = sorted(facts, key=lambda f: f.fiscal_year)
    first, last = facts[0], facts[-1]
    m = first.metric
    years = f"FY{first.fiscal_year}-FY{last.fiscal_year}"
    rows = [f"| Fiscal year | Period | {m.label} | Change vs prior year | Direction |", "|---|---|---|---|---|"]
    for f in facts:
        period = f"as of {f.end}" if m.instant else f"{f.start} to {f.end}"
        change = "-" if f.change_pct is None else f"{f.change_pct:+.1f}%"
        rows.append(f"| FY{f.fiscal_year} | {period} | {format_value(f.value, f.unit)} | {change} | {direction(f.change_pct)} |")
    overall = (last.value - first.value) / abs(first.value) * 100 if first.value else None
    concepts = ", ".join(dict.fromkeys(f"us-gaap:{f.concept}" for f in facts))
    text = (f"{m.label} by fiscal year, {years} (each year from its own Form 10-K; changes are year over year):\n"
            + "\n".join(rows)
            + f"\nFrom FY{first.fiscal_year} to FY{last.fiscal_year}: {format_value(first.value, m.unit)} to "
            f"{format_value(last.value, m.unit)} ({direction(overall)}). Source: XBRL {concepts}.")
    if any(f.comparative for f in facts):
        text += " Years marked comparative come from the next 10-K: " + ", ".join(
            f"FY{f.fiscal_year}" for f in facts if f.comparative) + "."
    return Chunk(
        chunk_id=f"xbrl:{first.ticker}:{years}:{m.key}",
        doc_id=f"{first.ticker}_{years}_10-K",
        ticker=first.ticker, company=first.company, fiscal_year=last.fiscal_year, form="10-K",
        filing_date=last.filed, period_end=last.end, part=None,
        section="XBRL", section_title=f"Company facts: {m.label} {years}", subsection=None,
        page_start=0, page_end=0, page_label_start=None, page_label_end=None,
        chunk_type="table", context=f"{first.company} ({first.ticker}) XBRL financial data, {years}", text=text,
        token_count=len(text.split()) * 2, source_url=last.source_url,
        metadata={"series": True, "years": [f.fiscal_year for f in facts], "metric": m.key},
    )


def fact_chunks(facts: Sequence[XbrlFact], series: bool) -> list[Chunk]:
    """Facts as chunks; with `series`, a company's metric over 2+ years becomes one table."""
    if not series:
        return [f.to_chunk() for f in facts]
    groups: dict[tuple[str, str], list[XbrlFact]] = {}
    for f in facts:
        groups.setdefault((f.ticker, f.metric.key), []).append(f)
    return [series_chunk(g) if len(g) > 1 else g[0].to_chunk() for g in groups.values()]


def format_value(value: float, unit: str) -> str:
    if unit == "USD":
        return f"${value / 1e6:,.0f} million"
    if unit == "USD/shares":
        return f"${value:,.2f} per share"
    return f"{value:,.0f} {unit}"


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _near(a: str, b: str) -> bool:
    return abs(_days(a, b)) <= PERIOD_END_TOLERANCE_DAYS


def _covers_year(fact: dict, period_end: str, instant: bool) -> bool:
    if not _near(fact["end"], period_end):
        return False
    if instant:
        return "start" not in fact
    return "start" in fact and YEAR_DAYS[0] <= _days(fact["start"], fact["end"]) <= YEAR_DAYS[1]


def _prior_end(period_end: str) -> str:
    return (date.fromisoformat(period_end) - timedelta(days=365)).isoformat()  # +-7 days covers 52/53 weeks


class CompanyFacts:
    """One company's companyfacts JSON with fiscal-year lookups against its 10-K filings."""

    def __init__(self, data: dict, filings: Iterable[FilingPeriod]):
        self.data = data
        self.company = data.get("entityName", "")
        self.filings = {f.fiscal_year: f for f in filings}
        self.ticker = next(iter(self.filings.values())).ticker if self.filings else ""

    @cached_property
    def _gaap(self) -> dict:
        return self.data.get("facts", {}).get("us-gaap", {})

    def _facts(self, concept: str, unit: str) -> list[dict]:
        return self._gaap.get(concept, {}).get("units", {}).get(unit, [])

    def lookup(self, metric: str | Metric, fiscal_year: int) -> XbrlFact | None:
        m = METRICS[metric] if isinstance(metric, str) else metric
        filing = self.filings.get(fiscal_year)
        if filing is None:
            return None
        for concept in m.concepts:  # the filing's own facts, any concept, before any fallback
            if fact := self._from_filing(m, concept, filing):
                return fact
        for concept in m.concepts:
            if fact := self._from_later_filing(m, concept, filing):
                return fact
        return None

    def _make(self, m: Metric, concept: str, fact: dict, filing: FilingPeriod, prior: float | None,
              comparative: bool = False) -> XbrlFact:
        return XbrlFact(
            ticker=filing.ticker, company=self.company, fiscal_year=filing.fiscal_year, metric=m,
            concept=concept, concept_label=self._gaap[concept].get("label") or concept,
            value=fact["val"], unit=m.unit, start=fact.get("start"), end=fact["end"],
            accession_number=fact["accn"], filed=fact.get("filed", ""), prior_value=prior,
            comparative=comparative, source_url=filing.source_url,
        )

    def _from_filing(self, m: Metric, concept: str, filing: FilingPeriod) -> XbrlFact | None:
        own = [f for f in self._facts(concept, m.unit) if f.get("accn") == filing.accession_number]
        current = [f for f in own if _covers_year(f, filing.period_end, m.instant)]
        if not current:
            return None
        if len({f["val"] for f in current}) > 1:
            logger.warning("%s FY%s %s: conflicting values %s", filing.ticker, filing.fiscal_year, concept,
                           sorted({f["val"] for f in current}))
        prior_end = _prior_end(current[0]["end"])
        prior = next((f["val"] for f in own if _covers_year(f, prior_end, m.instant)), None)
        return self._make(m, concept, current[0], filing, prior)

    def _from_later_filing(self, m: Metric, concept: str, filing: FilingPeriod) -> XbrlFact | None:
        later = sorted(
            (f for f in self._facts(concept, m.unit)
             if f.get("form") == "10-K" and f.get("filed", "") > filing.filing_date
             and _covers_year(f, filing.period_end, m.instant)),
            key=lambda f: f.get("filed", ""),
        )
        if not later:
            return None
        fact = later[0]
        prior = next((f["val"] for f in self._facts(concept, m.unit)
                      if f.get("accn") == fact["accn"] and _covers_year(f, _prior_end(fact["end"]), m.instant)), None)
        return self._make(m, concept, fact, filing, prior, comparative=True)


class XbrlStore:
    """Company facts for the corpus, loaded lazily from `data/raw/xbrl/{TICKER}.json`."""

    def __init__(self, xbrl_dir: Path, filings: Iterable[FilingPeriod]):
        self.xbrl_dir = xbrl_dir
        self._filings: dict[str, list[FilingPeriod]] = {}
        for f in filings:
            self._filings.setdefault(f.ticker, []).append(f)
        self._companies: dict[str, CompanyFacts | None] = {}

    @classmethod
    def from_settings(cls) -> "XbrlStore":
        settings = get_settings()
        return cls(xbrl_dir(), load_filing_periods(settings.raw_sec_dir / "manifest.json"))

    def company(self, ticker: str) -> CompanyFacts | None:
        if ticker not in self._companies:
            path = self.xbrl_dir / f"{ticker}.json"
            if not path.exists():
                logger.warning("No companyfacts for %s at %s (run python -m app.agent.xbrl --download)", ticker, path)
                self._companies[ticker] = None
            else:
                self._companies[ticker] = CompanyFacts(json.loads(path.read_text()), self._filings.get(ticker, []))
        return self._companies[ticker]

    def lookup(self, ticker: str, metric: str, fiscal_year: int) -> XbrlFact | None:
        facts = self.company(ticker)
        return facts.lookup(metric, fiscal_year) if facts else None

    def lookup_many(self, tickers: Iterable[str], metrics: Iterable[str], years: Iterable[int]) -> list[XbrlFact]:
        """Facts for every (ticker, year, metric) that resolves, in ticker, year, metric order."""
        metrics, years = list(metrics), list(years)
        return [fact for t in tickers for y in years for m in metrics if (fact := self.lookup(t, m, y))]


def xbrl_dir() -> Path:
    return get_settings().data_dir / "raw" / "xbrl"


def load_filing_periods(manifest_path: Path) -> list[FilingPeriod]:
    return [
        FilingPeriod(r["ticker"], r["fiscal_year"], r["accession_number"], r["report_date"], r["filing_date"],
                     r.get("source_url", ""))
        for r in json.loads(manifest_path.read_text()) if r["form"] == "10-K"
    ]


# --- metric detection (for the agent: which facts does a question need?) ---------------------

_METRIC_PATTERNS: dict[str, re.Pattern] = {key: re.compile(p, re.IGNORECASE) for key, p in {
    "revenue": r"\b(?:total |net |consolidated )*(?:revenues?|net sales|sales)\b",
    "net_income": r"\bnet (?:income|earnings|profit)\b|\bearned\b",
    "operating_income": r"\boperating (?:income|profit)\b",
    "gross_profit": r"\bgross (?:profit|margin)\b",
    "rnd": r"\bresearch and development\b|\bR&D\b",
    "capex": r"\bcapital expenditures?\b|\bcapex\b",
    "operating_cash_flow": r"\b(?:operating cash flows?|cash (?:flows? )?from operations|cash provided by operating)\b",
    "buybacks": r"\b(?:repurchase[sd]?|buybacks?)\b",
    "eps_diluted": r"\b(?:diluted )?(?:EPS|earnings per share)\b",
    "total_assets": r"\btotal assets\b",
    "total_liabilities": r"\btotal liabilities\b",
    "stockholders_equity": r"\b(?:stockholders'?|shareholders'?) equity\b",
}.items()}

# A metric qualified by a segment, product or geography ("Data Center revenue", "AWS sales",
# "Services net sales") is not the company total that XBRL reports, so no fact is attached.
_SEGMENT = re.compile(
    r"\b(?:segments?|services|cloud|azure|aws|data center|gaming|search|youtube|advertising|ads|iphone|ipad|mac|"
    r"wearables|automotive|energy|regulatory credits|reality labs|family of apps|international|cross-border|"
    r"china|greater china|americas|europe|subscriptions?|devices|interest income|deliver(?:y|ies|ed)|employees|customers?)\b",
    re.IGNORECASE,
)


def detect_metrics(question: str) -> tuple[str, ...]:
    """Company-level metrics a question asks about (empty when none, or when it's segment-level)."""
    if _SEGMENT.search(question):
        return ()
    found = [key for key, pattern in _METRIC_PATTERNS.items() if pattern.search(question)]
    if "net_income" in found and "eps_diluted" in found and not re.search(r"\bper share\b|\bEPS\b", question, re.I):
        found.remove("eps_diluted")  # "earnings" alone
    return tuple(found)


# --- CLI ----------------------------------------------------------------------------------------

def download(tickers: Iterable[str], force: bool = False) -> Iterator[Path]:
    from app.ingestion.sec_downloader import SecClient  # network only here

    out = xbrl_dir()
    out.mkdir(parents=True, exist_ok=True)
    client = SecClient(get_settings().sec_user_agent)
    try:
        for ticker in tickers:
            path = out / f"{ticker}.json"
            if force or not path.exists():
                path.write_bytes(client.get(COMPANYFACTS_URL.format(cik=get_company(ticker).cik)).content)
                logger.info("%s: downloaded companyfacts (%d KB)", ticker, path.stat().st_size // 1024)
            yield path
    finally:
        client.close()


def coverage(store: XbrlStore, tickers: Iterable[str], years: Iterable[int]) -> str:
    """Markdown table: per metric and company, the years that resolve (c = from a later 10-K)."""
    years = list(years)
    tickers = list(tickers)
    lines = ["| Metric | " + " | ".join(tickers) + " |", "|---|" + "---|" * len(tickers)]
    total = resolved = 0
    for metric in METRICS:
        cells = []
        for t in tickers:
            marks = []
            for y in years:
                fact = store.lookup(t, metric, y)
                total += 1
                resolved += fact is not None
                marks.append("-" if fact is None else ("c" if fact.comparative else "✓"))
            cells.append("".join(marks))
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    lines.append(f"\nResolved {resolved}/{total} (company, year, metric) cells; years {years[0]}-{years[-1]} left to right.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download", action="store_true", help="fetch companyfacts JSON (cached)")
    parser.add_argument("--force", action="store_true", help="re-download cached files")
    parser.add_argument("--tickers", nargs="+", default=list(COMPANIES))
    parser.add_argument("--years", type=int, nargs="+", default=[2022, 2023, 2024, 2025])
    parser.add_argument("--ticker", help="print facts for one company")
    parser.add_argument("--metric", nargs="+", default=list(METRICS))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.download:
        for _ in download(args.tickers, args.force):
            pass
    store = XbrlStore.from_settings()
    if args.ticker:
        for fact in store.lookup_many([args.ticker.upper()], args.metric, args.years):
            print(f"{fact.citation} {fact.text()}")
    else:
        print(coverage(store, args.tickers, args.years))


if __name__ == "__main__":
    main()
