"""Earnings releases: fiscal quarter mapping, choosing the release among Item 2.02 8-Ks, exhibit lookup.

Rows mimic EDGAR's submissions feed with the real dates of the cases that shaped the rules
(NVIDIA's January fiscal year end, Tesla's deliveries reports, NVIDIA's preliminary Q2 FY2023 revenue).
"""

import json
import logging
from datetime import date

from app.ingestion.companies import get_company
from app.ingestion.earnings_downloader import (EarningsReleaseRef, choose_release, exhibit_document, fiscal_period,
                                               looks_like_release, period_ends, release_candidates, update_manifest)


def row(form, filed, report="", items="", accession=None):
    return {"form": form, "filingDate": filed, "reportDate": report, "items": items,
            "accessionNumber": accession or f"0000000000-{filed[2:4]}-{filed[5:7]}{filed[8:]}", "primaryDocument": "x.htm"}


# NVIDIA: fiscal year ends the last Sunday of January; FY2023 = Feb 2022 - Jan 2023.
NVDA = [
    row("10-K", "2022-03-18", "2022-01-30"), row("10-Q", "2022-05-27", "2022-05-01"),
    row("10-Q", "2022-08-31", "2022-07-31"), row("10-Q", "2022-11-18", "2022-10-30"),
    row("10-K", "2023-02-24", "2023-01-29"),
    row("8-K", "2022-05-25", "2022-05-25", "2.02,9.01"),
    row("8-K", "2022-08-08", "2022-08-08", "2.02,9.01"),  # preliminary Q2 revenue
    row("8-K", "2022-08-24", "2022-08-24", "2.02,9.01"),  # the release
    row("8-K", "2022-11-16", "2022-11-16", "2.02,9.01"),
    row("8-K", "2023-02-22", "2023-02-22", "2.02,9.01"),
    row("8-K", "2022-06-10", "2022-06-10", "5.07"),  # shareholder vote: not 2.02
]


def test_fiscal_period_follows_the_companys_calendar():
    fy_ends, periods = period_ends(NVDA)
    assert fy_ends == [date(2022, 1, 30), date(2023, 1, 29)] and len(periods) == 5
    assert fiscal_period(date(2022, 5, 1), fy_ends) == (2023, 1)  # NVIDIA labels by the year the fiscal year ends
    assert fiscal_period(date(2022, 10, 30), fy_ends) == (2023, 3)
    assert fiscal_period(date(2023, 1, 29), fy_ends) == (2023, 4)
    assert fiscal_period(date(2021, 10, 31), fy_ends) is None  # no earlier fiscal-year end to count from
    # Apple (late September year end): Q1 FY2025 ended 2024-12-28
    assert fiscal_period(date(2024, 12, 28), [date(2023, 9, 30), date(2024, 9, 28)]) == (2025, 1)


def test_candidates_per_quarter_ranked_and_filtered():
    c = release_candidates(NVDA, [2023])
    assert sorted(c) == [(2023, 1), (2023, 2), (2023, 3), (2023, 4)]
    assert [f["filingDate"] for f, _ in c[(2023, 2)]] == ["2022-08-08", "2022-08-24"]  # both pure: by date
    assert c[(2023, 2)][0][1] == date(2022, 7, 31)  # the period end it reports
    assert release_candidates(NVDA, [2022]) == {}  # FY2022's quarters aren't anchored in these rows
    tesla = [row("10-K", "2022-02-07", "2021-12-31"), row("10-Q", "2022-04-25", "2022-03-31"),
             row("8-K", "2022-04-04", "2022-04-02", "2.02,7.01,9.01"),  # deliveries report
             row("8-K", "2022-04-20", "2022-04-20", "2.02,9.01"),
             row("8-K", "2022-09-15", "2022-09-15", "2.02,9.01")]  # >120 days after Q1 end, before Q2's 10-Q row
    ranked = release_candidates(tesla, [2022])[(2022, 1)]
    assert [f["filingDate"] for f, _ in ranked] == ["2022-04-20", "2022-04-04"]  # extra items rank last


RELEASE = b"<p>Net income</p><td>Diluted</td> per share"
PRELIMINARY = b"<p>NVIDIA Announces Preliminary Second Quarter Revenue of approximately $6.70 billion</p>"


def test_choose_release_checks_content_only_when_there_is_a_choice(caplog):
    caplog.set_level(logging.INFO, logger="app.ingestion.earnings_downloader")
    nvda, period = get_company("NVDA"), (2023, 2)
    options = release_candidates(NVDA, [2023])[period]
    exhibits = {"2022-08-08": ("prelim.htm", PRELIMINARY), "2022-08-24": ("q2fy23pr.htm", RELEASE)}
    fetched = []

    def fetch(f):
        fetched.append(f["filingDate"])
        return exhibits[f["filingDate"]]

    filing, period_end, document, content = choose_release(nvda, period, options, fetch)
    assert filing["filingDate"] == "2022-08-24" and document == "q2fy23pr.htm" and period_end == date(2022, 7, 31)
    assert fetched == ["2022-08-08", "2022-08-24"] and "chose 2022-08-24" in caplog.text

    single = choose_release(nvda, (2023, 1), options[:1], lambda f: ("only.htm", PRELIMINARY))
    assert single[2] == "only.htm"  # one candidate: taken without a content check
    fallback = choose_release(nvda, period, options, lambda f: ("x.htm", PRELIMINARY))
    assert fallback[0]["filingDate"] == "2022-08-08" and "no candidate looks like" in caplog.text
    assert choose_release(nvda, period, options, lambda f: None) is None  # no Exhibit 99.1 at all


def test_looks_like_release_and_exhibit_lookup():
    assert looks_like_release(RELEASE.decode()) and not looks_like_release(PRELIMINARY.decode())
    assert looks_like_release("Net loss ... Diluted")
    index = """<table><tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th></tr>
      <tr><td>1</td><td>8-K</td><td><a href="x">nvda-20260826.htm</a> &nbsp;&nbsp;iXBRL</td><td>8-K</td><td>26457</td></tr>
      <tr><td>2</td><td>EX-99.1</td><td><a href="y">q2fy27pr.htm</a></td><td>EX-99.1</td><td>341113</td></tr>
      <tr><td>3</td><td>EX-99.2</td><td><a href="z">q2fy27cfo.htm</a></td><td>EX-99.2</td><td>256881</td></tr></table>"""
    assert exhibit_document(index) == "q2fy27pr.htm"
    assert exhibit_document(index, "EX-99.2") == "q2fy27cfo.htm" and exhibit_document(index, "EX-99.9") is None


def test_manifest_merges_by_ticker_year_and_quarter(tmp_path):
    def ref(q, doc):
        return EarningsReleaseRef("NVDA", "NVIDIA Corporation", 1045810, "8-K EX-99.1", 2025, "a", "2025-02-26",
                                  "2025-01-26", doc, "u", "i", fiscal_quarter=q)
    path = tmp_path / "manifest_earnings.json"
    update_manifest(path, [ref(4, "old.htm"), ref(1, "q1.htm")])
    update_manifest(path, [ref(4, "q4fy25pr.htm")])
    rows = json.loads(path.read_text())
    assert [(r["fiscal_quarter"], r["primary_document"]) for r in rows] == [(1, "q1.htm"), (4, "q4fy25pr.htm")]
