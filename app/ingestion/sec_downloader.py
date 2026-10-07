"""Download annual reports (Form 10-K) from SEC EDGAR.

EDGAR is the canonical, stable source for US annual reports. Investor-relations
PDF links move around between years; EDGAR URLs never do. Filings are fetched
as the original HTML, which keeps tables and page breaks intact for parsing.

Usage:
    python -m app.ingestion.sec_downloader --years 2025
    python -m app.ingestion.sec_downloader --years 2022 2023 2024 2025 --tickers AAPL MSFT
"""

import argparse
import json
import logging
import time
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.ingestion.companies import COMPANIES, Company, get_company

logger = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"

ANNUAL_FORMS = frozenset({"10-K"})  # amendments (10-K/A) are deliberately excluded


@dataclass
class FilingRef:
    ticker: str
    company: str
    cik: int
    form: str
    fiscal_year: int
    accession_number: str
    filing_date: str
    report_date: str
    primary_document: str
    source_url: str
    filing_index_url: str
    local_path: str = ""
    size_bytes: int = 0


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return isinstance(exc, httpx.TransportError)


class SecClient:
    """Thin HTTP client honouring SEC fair-access rules (UA header, <=10 req/s)."""

    def __init__(self, user_agent: str, min_interval_s: float = 0.15):
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=60.0,
            follow_redirects=True,
        )
        self._min_interval_s = min_interval_s
        self._last_request = 0.0

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, max=30),
        reraise=True,
    )
    def get(self, url: str) -> httpx.Response:
        wait = self._min_interval_s - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        response = self._client.get(url)
        response.raise_for_status()
        return response

    def close(self) -> None:
        self._client.close()


def _columnar_to_rows(block: dict) -> Iterator[dict]:
    """EDGAR returns filings column-wise ({"form": [...], "reportDate": [...]})."""
    keys = list(block)
    for values in zip(*(block[k] for k in keys)):
        yield dict(zip(keys, values))


def iter_filings(client: SecClient, cik: int) -> Iterator[dict]:
    """Yield all filings for a company, newest first.

    ``filings.recent`` holds only the latest ~1000 filings. Prolific filers
    (JPMorgan files thousands of structured-note prospectuses) push older
    10-Ks into the paginated ``filings.files`` archives, so we walk those too.
    """
    data = client.get(SUBMISSIONS_URL.format(cik=cik)).json()
    yield from _columnar_to_rows(data["filings"]["recent"])
    for page in data["filings"].get("files", []):
        yield from _columnar_to_rows(client.get(SUBMISSIONS_PAGE_URL.format(name=page["name"])).json())


def select_annual_filings(
    filings: Iterable[dict], years: Iterable[int], forms: frozenset[str] = ANNUAL_FORMS
) -> dict[int, dict]:
    """Pick the newest original annual filing per fiscal year.

    Stops consuming ``filings`` as soon as every requested year is found, so we
    avoid paging through archives we don't need.
    """
    wanted = set(years)
    selected: dict[int, dict] = {}
    for filing in filings:
        if filing.get("form") not in forms or not filing.get("reportDate"):
            continue
        fiscal_year = int(filing["reportDate"][:4])
        if fiscal_year in wanted and fiscal_year not in selected:
            selected[fiscal_year] = filing
            if selected.keys() == wanted:
                break
    return selected


def build_filing_ref(company: Company, fiscal_year: int, filing: dict) -> FilingRef:
    accession = filing["accessionNumber"].replace("-", "")
    return FilingRef(
        ticker=company.ticker,
        company=company.name,
        cik=company.cik,
        form=filing["form"],
        fiscal_year=fiscal_year,
        accession_number=filing["accessionNumber"],
        filing_date=filing["filingDate"],
        report_date=filing["reportDate"],
        primary_document=filing["primaryDocument"],
        source_url=ARCHIVE_URL.format(
            cik=company.cik, accession=accession, document=filing["primaryDocument"]
        ),
        filing_index_url=FILING_INDEX_URL.format(cik=company.cik, accession=accession),
    )


def download_company(
    client: SecClient, company: Company, years: list[int], out_dir: Path, force: bool = False
) -> list[FilingRef]:
    selected = select_annual_filings(iter_filings(client, company.cik), years)
    missing = sorted(set(years) - selected.keys())
    if missing:
        logger.warning("%s: no 10-K found for fiscal year(s) %s", company.ticker, missing)

    refs = []
    for fiscal_year, filing in sorted(selected.items()):
        ref = build_filing_ref(company, fiscal_year, filing)
        path = out_dir / company.ticker / f"FY{fiscal_year}_10-K.htm"
        if force or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(client.get(ref.source_url).content)
            logger.info("%s FY%s: downloaded %s", company.ticker, fiscal_year, ref.source_url)
        else:
            logger.info("%s FY%s: cached at %s", company.ticker, fiscal_year, path)
        ref.local_path = path.relative_to(out_dir).as_posix()
        ref.size_bytes = path.stat().st_size
        refs.append(ref)
    return refs


def update_manifest(manifest_path: Path, refs: list[FilingRef]) -> None:
    """Merge refs into the manifest, keyed by (ticker, form, fiscal_year)."""
    existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    merged = {(r["ticker"], r["form"], r["fiscal_year"]): r for r in existing}
    merged.update({(r.ticker, r.form, r.fiscal_year): asdict(r) for r in refs})
    rows = sorted(merged.values(), key=lambda r: (r["ticker"], r["fiscal_year"]))
    manifest_path.write_text(json.dumps(rows, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", default=[2025])
    parser.add_argument("--tickers", nargs="+", default=list(COMPANIES))
    parser.add_argument("--force", action="store_true", help="re-download cached files")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    out_dir = settings.raw_sec_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    client = SecClient(settings.sec_user_agent)
    all_refs: list[FilingRef] = []
    try:
        for ticker in args.tickers:
            all_refs.extend(download_company(client, get_company(ticker), args.years, out_dir, args.force))
    finally:
        client.close()

    update_manifest(out_dir / "manifest.json", all_refs)
    logger.info("Done: %d filings. Manifest: %s", len(all_refs), out_dir / "manifest.json")


if __name__ == "__main__":
    main()
