"""XBRL company-facts tool: fact selection, fallbacks, rendering, metric detection.

Fixture: NVIDIA's companyfacts trimmed to six concepts and the facts of its FY2022-2025 10-Ks
(real SEC data, no network). NVIDIA is a good test company: 52/53-week years ending in late
January, a 10-for-1 split in FY2025 (EPS), and FY2022-23 capex tagged with a company-specific
concept that companyfacts omits.
"""

import copy
import json
from pathlib import Path

import pytest

from app.agent.xbrl import CompanyFacts, XbrlStore, detect_metrics, load_filing_periods
from app.generation.context import Source
from app.generation.verify import extract_numbers, _matches

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads((FIXTURES / "companyfacts_nvda_sample.json").read_text())


@pytest.fixture(scope="module")
def filings():
    return load_filing_periods(FIXTURES / "manifest_nvda_sample.json")


@pytest.fixture(scope="module")
def nvda(data, filings) -> CompanyFacts:
    return CompanyFacts(data, filings)


@pytest.mark.parametrize("year,value,prior", [
    (2022, 26_914e6, 16_675e6),
    (2023, 26_974e6, 26_914e6),
    (2024, 60_922e6, 26_974e6),
    (2025, 130_497e6, 60_922e6),
])
def test_revenue_comes_from_the_years_own_10k(nvda, filings, year, value, prior):
    fact = nvda.lookup("revenue", year)
    own = next(f for f in filings if f.fiscal_year == year)
    assert (fact.value, fact.prior_value) == (value, prior)
    assert fact.accession_number == own.accession_number and not fact.comparative
    assert fact.concept == "Revenues"  # first concept in priority order wins


def test_eps_change_uses_the_same_filings_split_adjusted_prior(nvda):
    fact = nvda.lookup("eps_diluted", 2025)
    assert fact.value == 2.94 and fact.prior_value == 1.19  # not FY2024's pre-split 11.93
    assert round(fact.change_pct) == 147


def test_missing_concept_falls_back_to_next_10k_comparative(nvda, filings):
    fact = nvda.lookup("capex", 2023)
    assert fact.value == 1_833e6 and fact.comparative
    assert fact.accession_number == next(f for f in filings if f.fiscal_year == 2024).accession_number
    assert "does not tag it" in fact.text()
    assert not nvda.lookup("capex", 2025).comparative


def test_instant_metric_uses_the_balance_sheet_date(nvda):
    fact = nvda.lookup("total_assets", 2024)
    assert fact.start is None and fact.end == "2024-01-28"
    assert fact.value == 65_728e6 and fact.prior_value == 41_182e6


def test_quarterly_and_other_filings_facts_are_ignored(data, filings):
    data = copy.deepcopy(data)
    own = next(f for f in filings if f.fiscal_year == 2024)
    facts = data["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    facts[:] = [f for f in facts if f["accn"] == own.accession_number]
    facts.insert(0, {"start": "2023-10-30", "end": "2024-01-28", "val": 22_103e6, "accn": own.accession_number,
                     "fy": 2024, "fp": "FY", "form": "10-K", "filed": own.filing_date})  # Q4 only
    facts.insert(0, {"start": "2023-01-30", "end": "2024-01-28", "val": 1.0, "accn": "0000000000-99-000001",
                     "fy": 2024, "fp": "FY", "form": "10-K/A", "filed": "2024-06-01"})  # another filing
    assert CompanyFacts(data, filings).lookup("revenue", 2024).value == 60_922e6


def test_concept_priority_falls_through(data, filings):
    data = copy.deepcopy(data)
    del data["facts"]["us-gaap"]["Revenues"]
    fact = CompanyFacts(data, filings).lookup("revenue", 2022)
    assert fact.concept == "RevenueFromContractWithCustomerExcludingAssessedTax" and fact.value == 26_914e6


def test_unknown_year_and_untagged_metric(nvda):
    assert nvda.lookup("revenue", 2019) is None
    assert nvda.lookup("gross_profit", 2024) is None  # concept not in the fixture


def test_store_lookup_many_and_missing_company(tmp_path, data, filings):
    (tmp_path / "NVDA.json").write_text(json.dumps(data))
    store = XbrlStore(tmp_path, filings)
    facts = store.lookup_many(["NVDA", "AAPL"], ["revenue", "net_income"], [2024, 2025])
    assert [(f.fiscal_year, f.metric.key) for f in facts] == [
        (2024, "revenue"), (2024, "net_income"), (2025, "revenue"), (2025, "net_income")]
    assert store.lookup("AAPL", "revenue", 2025) is None


def test_fact_source_verifies_answer_figures(nvda):
    fact = nvda.lookup("revenue", 2025)
    source = Source("S1", fact.to_chunk(), 1.0)
    assert source.citation == "[XBRL NVDA FY2025 Total revenue]"
    assert source.render().startswith("[S1] NVIDIA CORP (NVDA) XBRL financial data, fiscal year 2025\n")
    source_numbers = extract_numbers(source.chunk.text)
    for claim in ("$130.5 billion", "$130,497 million", "114%", "$60.9B"):
        assert any(_matches(c, s) for c in extract_numbers(claim) for s in source_numbers), claim
    assert not any(_matches(c, s) for c in extract_numbers("$131.5 billion") for s in source_numbers)


@pytest.mark.parametrize("question,metrics", [
    ("What were Tesla's total revenues in 2024?", ("revenue",)),
    ("How did JPMorgan's net income change from 2022 to 2025?", ("net_income",)),
    ("Which earned more in 2025, Meta or Alphabet?", ("net_income",)),
    ("What was Microsoft's capex in fiscal 2024?", ("capex",)),
    ("How much did Alphabet spend on R&D in 2023?", ("rnd",)),
    ("What were Apple's diluted earnings per share in fiscal 2025?", ("eps_diluted",)),
    ("How large was Visa's operating cash flow in 2024?", ("operating_cash_flow",)),
    ("What was NVIDIA's Data Center revenue in fiscal 2024?", ()),  # segment, not the total
    ("How fast did AWS sales grow?", ()),
    ("How did Apple's iPhone net sales change?", ()),
    ("Why did Tesla's automotive revenue fall?", ()),
    ("When did Tesla launch Robotaxi?", ()),
])
def test_detect_metrics(question, metrics):
    assert detect_metrics(question) == metrics
