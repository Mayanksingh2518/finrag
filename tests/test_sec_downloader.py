from app.ingestion.companies import COMPANIES, get_company
from app.ingestion.sec_downloader import (
    _columnar_to_rows,
    build_filing_ref,
    select_annual_filings,
)


def _filing(form, report_date, accession="0000320193-25-000079", doc="aapl-20250927.htm"):
    return {
        "form": form,
        "reportDate": report_date,
        "filingDate": "2025-10-31",
        "accessionNumber": accession,
        "primaryDocument": doc,
    }


def test_registry_has_ten_unique_companies():
    assert len(COMPANIES) == 10
    assert len({c.cik for c in COMPANIES.values()}) == 10


def test_columnar_to_rows():
    block = {"form": ["10-K", "8-K"], "reportDate": ["2025-09-27", "2025-08-01"]}
    assert list(_columnar_to_rows(block)) == [
        {"form": "10-K", "reportDate": "2025-09-27"},
        {"form": "8-K", "reportDate": "2025-08-01"},
    ]


def test_select_skips_amendments_and_other_forms():
    filings = [
        _filing("10-K/A", "2025-09-27"),
        _filing("8-K", "2025-09-27"),
        _filing("10-K", "2025-09-27"),
        _filing("10-K", "2024-09-28"),
    ]
    selected = select_annual_filings(filings, [2025])
    assert selected[2025]["form"] == "10-K"
    assert list(selected) == [2025]


def test_select_uses_period_end_year_as_fiscal_year():
    # NVIDIA FY2025 ended 2025-01-26 and was filed in Feb 2025.
    filings = [_filing("10-K", "2025-01-26"), _filing("10-K", "2024-01-28")]
    assert set(select_annual_filings(filings, [2024, 2025])) == {2024, 2025}


def test_select_stops_once_all_years_found():
    def gen():
        yield _filing("10-K", "2025-12-31")
        raise AssertionError("should not page further")

    assert list(select_annual_filings(gen(), [2025])) == [2025]


def test_build_filing_ref_urls():
    ref = build_filing_ref(get_company("aapl"), 2025, _filing("10-K", "2025-09-27"))
    assert ref.source_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"
    )
    assert ref.filing_index_url.endswith("/320193/000032019325000079/")
