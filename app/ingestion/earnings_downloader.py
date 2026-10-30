"""Download quarterly earnings releases (8-K Item 2.02, Exhibit 99.1) from SEC EDGAR.

Companies furnish their earnings press release as Exhibit 99.1 to an 8-K under Item 2.02 ("Results of
Operations"). The 8-K's `reportDate` is the announcement date, not the period, so each release is
mapped to the period it reports from the company's own 10-Q/10-K period ends in the same submissions
feed: the latest period end before the filing date. Fiscal years follow the 10-K corpus rule (the year
the fiscal year ends: NVIDIA's Q3 FY2025 ended 2024-10-27), and the quarter is the period's distance
from the previous fiscal-year end in ~91-day steps.

Item 2.02 isn't only earnings: Tesla files its quarterly deliveries report under 2.02 days after quarter
end, NVIDIA pre-announced Q2 FY2023 revenue under 2.02, and Alphabet once filed a blog post under 2.02.
When a period has several Item 2.02 8-Ks, candidates are tried in order (no items beyond 2.02 and 9.01
first, then earliest) and the first whose exhibit has an income statement (net income and diluted EPS)
is the release.

Uses `SecClient` and `iter_filings` from `sec_downloader` (same User-Agent and rate limit).

Usage:
    python -m app.ingestion.earnings_downloader --years 2022 2023 2024 2025
    python -m app.ingestion.earnings_downloader --years 2025 --tickers NVDA AAPL
"""

import argparse
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from app.config import get_settings
from app.ingestion.companies import COMPANIES, Company, get_company
from app.ingestion.sec_downloader import ARCHIVE_URL, FILING_INDEX_URL, FilingRef, SecClient, iter_filings

logger = logging.getLogger(__name__)

RELEASE_ITEM = "2.02"
MAX_LAG_DAYS = 120  # a release comes within weeks of its quarter's end; older 2.02 8-Ks report something else
EXHIBIT_TYPE = "EX-99.1"


@dataclass
class EarningsReleaseRef(FilingRef):
    """A FilingRef whose `report_date` is the period end and `primary_document` the exhibit."""

    fiscal_quarter: int = 0  # 1-4


def _d(s: str) -> date:
    return date.fromisoformat(s)


def period_ends(filings: Iterable[dict]) -> tuple[list[date], list[date]]:
    """Fiscal-year ends (10-K report dates) and all period ends (10-K and 10-Q), sorted."""
    fy_ends, periods = set(), set()
    for f in filings:
        if f.get("form") in ("10-K", "10-Q") and f.get("reportDate"):
            periods.add(_d(f["reportDate"]))
            if f["form"] == "10-K":
                fy_ends.add(_d(f["reportDate"]))
    return sorted(fy_ends), sorted(periods)


def fiscal_period(period_end: date, fy_ends: list[date]) -> tuple[int, int] | None:
    """(fiscal year, quarter) of a period end, or None without an earlier fiscal-year end to count from."""
    if period_end in fy_ends:
        return period_end.year, 4
    previous = [d for d in fy_ends if d < period_end]
    if not previous:
        return None
    start = previous[-1]
    quarter = round((period_end - start).days / 91.3)
    if not 1 <= quarter <= 3:
        return None
    return (start + timedelta(days=365)).year, quarter  # the year the current fiscal year ends


def _extra_items(filing: dict) -> set[str]:
    return set((filing.get("items") or "").split(",")) - {RELEASE_ITEM, "9.01"}


def release_candidates(filings: Iterable[dict], years: Iterable[int]) -> dict[tuple[int, int], list[tuple[dict, date]]]:
    """Item 2.02 8-Ks per (fiscal year, quarter) in `years`, with the period end they report, best first.

    A candidate is filed within MAX_LAG_DAYS of a period end. Order: no items beyond 2.02 and 9.01
    first (deliveries reports and blog posts often add 7.01 / 8.01), then by filing date.
    """
    rows = list(filings)
    fy_ends, periods = period_ends(rows)
    wanted = set(years)
    candidates: dict[tuple[int, int], list[tuple[dict, date]]] = {}
    for f in rows:
        if f.get("form") != "8-K" or RELEASE_ITEM not in (f.get("items") or "").split(","):
            continue
        filed = _d(f["filingDate"])
        before = [p for p in periods if p < filed]
        if not before or (filed - before[-1]).days > MAX_LAG_DAYS:
            continue
        period = fiscal_period(before[-1], fy_ends)
        if period and period[0] in wanted:
            candidates.setdefault(period, []).append((f, before[-1]))
    return {period: sorted(options, key=lambda o: (bool(_extra_items(o[0])), o[0]["filingDate"]))
            for period, options in candidates.items()}


def looks_like_release(html: str) -> bool:
    """An earnings release carries an income statement: net income (or earnings / loss) and diluted EPS."""
    text = re.sub(r"<[^>]+>", " ", html).lower()
    return "diluted" in text and any(term in text for term in ("net income", "net earnings", "net loss"))


def exhibit_document(index_html: str, exhibit_type: str = EXHIBIT_TYPE) -> str | None:
    """Document name of the exhibit in a filing's -index.htm table (columns: seq, description, document, type)."""
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", index_html, re.S | re.I):
        cells = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
        if len(cells) >= 4 and cells[3].upper() == exhibit_type:
            return cells[2].split()[0]  # "q2fy27pr.htm  iXBRL" -> "q2fy27pr.htm"
    return None


def build_release_ref(company: Company, fiscal_year: int, quarter: int, filing: dict, period_end: date,
                      document: str) -> EarningsReleaseRef:
    accession = filing["accessionNumber"].replace("-", "")
    return EarningsReleaseRef(
        ticker=company.ticker, company=company.name, cik=company.cik, form="8-K EX-99.1", fiscal_year=fiscal_year,
        accession_number=filing["accessionNumber"], filing_date=filing["filingDate"],
        report_date=period_end.isoformat(), primary_document=document,
        source_url=ARCHIVE_URL.format(cik=company.cik, accession=accession, document=document),
        filing_index_url=FILING_INDEX_URL.format(cik=company.cik, accession=accession),
        fiscal_quarter=quarter,
    )


def _filings_since(client: SecClient, cik: int, since: date) -> list[dict]:
    """Filings newest first, stopping once past `since` (JPM's archive pages go back decades)."""
    out = []
    for f in iter_filings(client, cik):
        if f.get("filingDate") and _d(f["filingDate"]) < since:
            break
        out.append(f)
    return out


def _exhibit(client: SecClient, company: Company, filing: dict) -> tuple[str, bytes] | None:
    """(document name, content) of the filing's Exhibit 99.1, or None if it has none."""
    accession = filing["accessionNumber"]
    index_url = FILING_INDEX_URL.format(cik=company.cik, accession=accession.replace("-", "")) + f"{accession}-index.htm"
    document = exhibit_document(client.get(index_url).text)
    if document is None:
        return None
    url = ARCHIVE_URL.format(cik=company.cik, accession=accession.replace("-", ""), document=document)
    return document, client.get(url).content


def choose_release(company: Company, period: tuple[int, int], options: list[tuple[dict, date]],
                   fetch) -> tuple[dict, date, str, bytes] | None:
    """The first candidate whose Exhibit 99.1 looks like an earnings release (only checked if there's a choice)."""
    fetched = []
    for filing, period_end in options:
        exhibit = fetch(filing)
        if exhibit is None:
            continue
        fetched.append((filing, period_end, *exhibit))
        if len(options) == 1 or looks_like_release(exhibit[1].decode("utf-8", "replace")):
            break
    else:
        if fetched:
            logger.warning("%s Q%s FY%s: no candidate looks like an earnings release; using %s", company.ticker,
                           period[1], period[0], fetched[0][0]["filingDate"])
            return fetched[0]
        return None
    chosen = fetched[-1]
    if len(options) > 1:
        logger.info("%s Q%s FY%s: %d Item 2.02 8-Ks (%s), chose %s", company.ticker, period[1], period[0], len(options),
                    ", ".join(f"{f['filingDate']} items {f['items']}" for f, _ in options), chosen[0]["filingDate"])
    return chosen


def download_company(client: SecClient, company: Company, years: list[int], out_dir: Path,
                     force: bool = False) -> list[EarningsReleaseRef]:
    # The fiscal year before the first wanted one must be in range: its end anchors quarter counting.
    filings = _filings_since(client, company.cik, date(min(years) - 2, 1, 1))
    candidates = release_candidates(filings, years)
    missing = sorted({(y, q) for y in years for q in range(1, 5)} - candidates.keys())
    if missing:
        logger.warning("%s: no Item 2.02 8-K for %s", company.ticker, ", ".join(f"Q{q} FY{y}" for y, q in missing))
    refs = []
    for (fiscal_year, quarter), options in sorted(candidates.items()):
        path = out_dir / company.ticker / "8-K" / f"FY{fiscal_year}_Q{quarter}_EX-99.1.htm"
        ref = None if force else _cached_ref(out_dir, company.ticker, fiscal_year, quarter)
        if ref is None or not path.exists():
            chosen = choose_release(company, (fiscal_year, quarter), options, lambda f: _exhibit(client, company, f))
            if chosen is None:
                logger.warning("%s Q%s FY%s: no %s found", company.ticker, quarter, fiscal_year, EXHIBIT_TYPE)
                continue
            filing, period_end, document, content = chosen
            ref = build_release_ref(company, fiscal_year, quarter, filing, period_end, document)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        ref.local_path = path.relative_to(out_dir).as_posix()
        ref.size_bytes = path.stat().st_size
        refs.append(ref)
    logger.info("%s: %d earnings releases", company.ticker, len(refs))
    return refs


def manifest_path(out_dir: Path) -> Path:
    return out_dir / "manifest_earnings.json"  # separate from manifest.json, which the 10-K pipeline reads


def _cached_ref(out_dir: Path, ticker: str, fiscal_year: int, quarter: int) -> EarningsReleaseRef | None:
    path = manifest_path(out_dir)
    if not path.exists():
        return None
    for row in json.loads(path.read_text()):
        if (row["ticker"], row["fiscal_year"], row["fiscal_quarter"]) == (ticker, fiscal_year, quarter):
            return EarningsReleaseRef(**row)
    return None


def update_manifest(path: Path, refs: list[EarningsReleaseRef]) -> None:
    """Merge refs into the manifest, keyed by (ticker, fiscal_year, fiscal_quarter)."""
    existing = json.loads(path.read_text()) if path.exists() else []
    merged = {(r["ticker"], r["fiscal_year"], r["fiscal_quarter"]): r for r in existing}
    merged.update({(r.ticker, r.fiscal_year, r.fiscal_quarter): asdict(r) for r in refs})
    rows = sorted(merged.values(), key=lambda r: (r["ticker"], r["fiscal_year"], r["fiscal_quarter"]))
    path.write_text(json.dumps(rows, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", default=[2025])
    parser.add_argument("--tickers", nargs="+", default=list(COMPANIES))
    parser.add_argument("--force", action="store_true", help="re-download cached files")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    out_dir = settings.raw_sec_dir
    client = SecClient(settings.sec_user_agent)
    refs: list[EarningsReleaseRef] = []
    try:
        for ticker in args.tickers:
            refs.extend(download_company(client, get_company(ticker), args.years, out_dir, args.force))
    finally:
        client.close()
    update_manifest(manifest_path(out_dir), refs)
    logger.info("Done: %d earnings releases. Manifest: %s", len(refs), manifest_path(out_dir))


if __name__ == "__main__":
    main()
