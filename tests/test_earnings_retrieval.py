"""Quarter detection, the 10-K default and the separate release search."""

import json

import numpy as np
import pytest

from app.agent.analyze import QueryAnalyzer
from app.agent.entities import extract, fiscal_period_of
from app.agent.graph import merge_filters
from app.agent.plan import MANY_SUB_QUERIES_CANDIDATES, make_plan
from app.config import PROJECT_ROOT
from app.generation.answer import RELEASE_RULE, SYSTEM_PROMPT, build_messages, render_citations
from app.generation.columns import known_periods, parse_label
from app.generation.context import Source
from app.generation.schemas import Claim
from app.generation.verify import verify_claims
from app.ingestion.models import Chunk
from app.retrieval.bm25 import BM25Index, PartitionedBM25
from app.retrieval.decompose import split_filters
from app.retrieval.pg_store import filter_sql
from app.retrieval.store import ChunkStore
from app.retrieval.types import FORM_10K, FORM_RELEASE, SearchFilters
from tests.test_retrieval import make_chunk


def release_chunk(i: int, ticker: str, year: int, quarter: int, text: str) -> Chunk:
    c = make_chunk(i, ticker, year, "Earnings release", text)
    c.chunk_id, c.form, c.fiscal_quarter = f"{ticker}-FY{year}-Q{quarter}-{i}", FORM_RELEASE, quarter
    c.page_start = c.page_end = 0
    return c


TEN_K = [make_chunk(0, "NVDA", 2025, "Item 7", "Data center revenue grew strongly in fiscal 2025."),
         make_chunk(1, "NVDA", 2024, "Item 7", "Gaming revenue increased in fiscal 2024.")]
RELEASES = [release_chunk(2, "NVDA", 2025, 3, "Third-quarter data center revenue was a record $30.8 billion."),
            release_chunk(3, "NVDA", 2025, 2, "Second-quarter data center revenue was $26.3 billion.")]
STORE = ChunkStore(TEN_K + RELEASES)


@pytest.mark.parametrize("question, quarters, years", [
    ("What did NVIDIA report for Q3 FY2025 data center revenue?", (3,), (2025,)),
    ("NVIDIA third quarter fiscal 2025 revenue", (3,), (2025,)),
    ("NVIDIA's third-quarter 2025 revenue", (3,), (2025,)),
    ("NVDA revenue in Q3 FY25", (3,), (2025,)),
    ("JPMorgan net income 3Q24", (3,), (2024,)),
    ("JPMorgan net income in Q4'23", (4,), (2023,)),
    ("Compare Apple's Q1 and Q2 2025 revenue", (1, 2), (2025,)),
    ("How did Apple's quarterly revenue trend in fiscal 2025?", (1, 2, 3, 4), (2025,)),
    ("Tesla deliveries each quarter of 2024", (1, 2, 3, 4), (2024,)),
])
def test_quarter_detection(question, quarters, years):
    own = extract(question)
    assert own.fiscal_quarters == quarters and own.fiscal_years == years and own.release


@pytest.mark.parametrize("question", [
    "What was NVIDIA's revenue in fiscal 2025?",
    "Did Apple raise its quarterly dividend in 2024?",
    "What are Tesla's risk factors in 2024?",
    "How did Microsoft's revenue change from 2022 to 2025?",
])
def test_annual_questions_stay_on_the_10k(question):
    own = extract(question)
    assert not own.fiscal_quarters and not own.release
    filters = QueryAnalyzer().analyze(question).filters
    assert filters.forms is None and filters.fiscal_quarters is None and filters.effective_forms() == (FORM_10K,)


def test_golden_questions_are_all_read_as_annual():
    rows = [json.loads(line) for line in (PROJECT_ROOT / "data/eval/golden_v0.jsonl").open(encoding="utf-8")] \
        if (PROJECT_ROOT / "data/eval/golden_v0.jsonl").exists() else []
    assert not [r["question"] for r in rows if extract(r["question"]).release]


@pytest.mark.parametrize("ticker, month, day, year, expected", [
    ("NVDA", 10, 27, 2024, (2025, 3)),
    ("NVDA", 1, 26, 2025, (2025, 4)),
    ("NVDA", 5, 1, 2022, (2023, 1)),  # the 52/53-week quarter that ends in the next month's first days
    ("AAPL", 12, 28, 2024, (2025, 1)),
    ("AAPL", 7, 1, 2023, (2023, 3)),
    ("MSFT", 3, 31, 2025, (2025, 3)),
    ("JPM", 12, 31, 2024, (2024, 4)),
])
def test_period_end_date_uses_the_fiscal_calendar(ticker, month, day, year, expected):
    assert fiscal_period_of(ticker, month, day, year) == expected


def test_three_months_ended_converts_the_calendar_year():
    own = extract("NVIDIA's revenue for the three months ended October 27, 2024")
    assert own.fiscal_years == (2025,) and own.fiscal_quarters == (3,) and not own.out_of_range_years


def test_guidance_searches_only_the_release_that_states_it():
    own = extract("What was NVIDIA's revenue outlook for Q4 FY2025?")
    assert own.fiscal_quarters == (3,) and own.fiscal_years == (2025,)
    own = extract("What was NVIDIA's guidance for Q1 FY2025?")
    assert own.fiscal_quarters == (4,) and own.fiscal_years == (2024,)
    own = extract("What was NVIDIA's guidance for Q1 FY2026?")  # stated in the last release of the corpus
    assert own.fiscal_quarters == (4,) and own.fiscal_years == (2025,) and not own.out_of_range_years
    assert QueryAnalyzer().analyze("What was NVIDIA's guidance for Q1 FY2026?").scope == "in_corpus"
    assert QueryAnalyzer().analyze("What was NVIDIA's guidance for Q1 FY2022?").scope == "out_of_range"  # FY2021 Q4
    assert extract("What outlook did NVIDIA give in its Q3 FY2025 earnings release?").fiscal_quarters == (3,)


def test_quarter_after_the_corpus_is_refused():
    assert QueryAnalyzer().analyze("What was NVIDIA's revenue in Q2 FY2026?").scope == "out_of_range"
    assert QueryAnalyzer().analyze("What was NVIDIA's guidance for Q2 FY2026?").scope == "out_of_range"


def test_release_questions_drop_10k_sections():
    filters = QueryAnalyzer().analyze("What risk did Tesla mention in Q2 2024?").filters
    assert filters.sections is None and filters.forms == (FORM_RELEASE,)


def test_follow_up_stays_on_the_quarter():
    a = QueryAnalyzer().analyze("And its net income?", ["NVIDIA revenue in Q3 FY2025?", "It was $35,082 million."])
    assert a.filters.fiscal_quarters == (3,) and a.filters.forms == (FORM_RELEASE,) and "fiscal_quarters" in a.carried_over
    a = QueryAnalyzer().analyze("And in Q4?", ["NVIDIA revenue in Q3 FY2025?", "It was $35,082 million."])
    assert a.filters.fiscal_quarters == (4,) and a.filters.fiscal_years == (2025,)


def test_store_defaults_to_10k_and_filters_releases():
    rows = lambda f: np.flatnonzero(STORE.mask(f)).tolist()  # noqa: E731
    assert rows(None) == [0, 1] and rows(SearchFilters()) == [0, 1]
    assert rows(SearchFilters(tickers=("NVDA",))) == [0, 1]
    assert rows(SearchFilters(fiscal_quarters=(3,))) == [2]
    assert rows(SearchFilters(forms=(FORM_RELEASE,))) == [2, 3]
    assert rows(SearchFilters(forms=(FORM_10K, FORM_RELEASE))) == [0, 1, 2, 3]
    assert ChunkStore(TEN_K).mask(None) is None  # nothing to exclude: no mask


def test_sql_filters_match_the_store():
    assert filter_sql(None) == ("", [])
    assert filter_sql(SearchFilters()) == ("WHERE form = ANY(%s)", [[FORM_10K]])
    where, params = filter_sql(SearchFilters(tickers=("nvda",), fiscal_quarters=(3,)))
    assert where == "WHERE form = ANY(%s) AND ticker = ANY(%s) AND fiscal_quarter = ANY(%s)"
    assert params == [[FORM_RELEASE], ["NVDA"], [3]]


def test_release_terms_do_not_change_10k_bm25_scores():
    """The property the separate indexes exist for: 10-K scores are those of a 10-K-only index."""
    texts = [c.embed_text for c in STORE.chunks]
    forms = [c.form for c in STORE.chunks]
    alone = BM25Index(texts[:2]).search("data center revenue", 5)
    together = PartitionedBM25(texts, forms).search("data center revenue", 5, STORE.mask(None))
    assert together == alone
    release_only = PartitionedBM25(texts, forms).search("data center revenue", 5, STORE.mask(SearchFilters(fiscal_quarters=(3,))))
    assert [r for r, _ in release_only] == [2]


def test_split_keeps_quarter_and_form():
    parts = split_filters(SearchFilters(tickers=("AAPL",), fiscal_years=(2025,), fiscal_quarters=(1, 2), forms=(FORM_RELEASE,)))
    assert [p.fiscal_quarters for p in parts] == [(1,), (2,)] and all(p.forms == (FORM_RELEASE,) for p in parts)


def test_plan_for_quarters():
    q = SearchFilters(tickers=("AAPL",), fiscal_years=(2025,), fiscal_quarters=(1, 2, 3, 4), forms=(FORM_RELEASE,))
    plan = make_plan("Apple's quarterly revenue in fiscal 2025", q)
    assert plan.intent == "trend" and len(plan.sub_queries) == 4 and plan.quota == 3 and plan.rerank_candidates is None
    many = make_plan("Apple's quarterly revenue", SearchFilters(tickers=("AAPL",), fiscal_years=(2022, 2023, 2024),
                                                                fiscal_quarters=(1, 2, 3, 4)))
    assert many.rerank_candidates == MANY_SUB_QUERIES_CANDIDATES
    assert make_plan("Apple revenue", SearchFilters(tickers=("AAPL", "MSFT", "V"), fiscal_years=(2022, 2023, 2024))).rerank_candidates is None


def test_user_filters_and_document_type():
    analyzed = SearchFilters(tickers=("NVDA",), fiscal_quarters=(3,), forms=(FORM_RELEASE,))
    assert merge_filters(analyzed, SearchFilters(forms=(FORM_10K,))).fiscal_quarters is None
    assert merge_filters(SearchFilters(sections=("Item 1A",)), SearchFilters(fiscal_quarters=(2,))).sections is None
    assert merge_filters(analyzed, SearchFilters(fiscal_quarters=(2,))).fiscal_quarters == (2,)


def test_release_rule_only_with_release_sources():
    ten_k = build_messages("q", [Source("S1", TEN_K[0], 1.0)])[0]["content"]
    assert ten_k == SYSTEM_PROMPT and "earnings release" not in ten_k  # prompt and LLM cache of 10-K answers unchanged
    release = build_messages("q", [Source("S1", RELEASES[0], 1.0)])[0]["content"]
    assert release == SYSTEM_PROMPT + RELEASE_RULE
    assert "one line per quarter" in build_messages("q", [Source("S1", RELEASES[0], 1.0)], intent="trend")[0]["content"]


NVDA_TABLE = "| ($ in millions) | Q3 FY25 | Q2 FY25 |\n|---|---|---|\n| Revenue | $35,082 | $30,040 |\n| Net income | $19,309 | $16,599 |"
TSLA_TABLE = "Q1-2024 Q2-2024 YoY\nTotal deliveries 386,810 443,956 -5%\nTesla locations 1,258 1,286 20%"


def verified(text: str, *sources: Source, cited: tuple[str, ...] = ()):
    return verify_claims([Claim(text=text, source_ids=list(cited))], list(sources))[0]


def release_source(sid: str, text: str, ticker: str = "NVDA") -> Source:
    c = release_chunk(9, ticker, 2025, 3, text)
    c.context = f"{ticker} Corp ({ticker}) earnings release, Q3 fiscal year 2025, quarter ended 2024-10-27"
    return Source(sid, c, 1.0)


def test_release_repair_finds_the_figure_in_a_row_naming_the_metric():
    other = release_source("S1", "NVIDIA delivered record results.")
    # Short claim, cited the wrong source: the row "Net income | $19,309" settles it.
    v = verified("Net income in Q3 FY2025 was $19,309 million.", other, release_source("S2", NVDA_TABLE), cited=("S1",))
    assert v.supported and v.repaired and "S2" in v.source_ids
    # No citation; the row says "deliveries", the claim "delivered".
    v = verified("Tesla delivered 443,956 vehicles in Q2 2024.", release_source("S1", TSLA_TABLE, "TSLA"))
    assert v.supported and v.source_ids == ["S1"]


def test_release_repair_never_rescues_a_figure_the_row_does_not_support():
    table = release_source("S1", NVDA_TABLE)
    assert not verified("Net income in Q3 FY2025 was $20,000 million.", table).supported  # invented
    assert not verified("Operating cash flow was $19,309 million.", table).supported  # a row about something else


def test_10k_repair_rules_are_unchanged_for_short_claims():
    source = Source("S1", make_chunk(0, "NVDA", 2025, "Item 7", NVDA_TABLE), 1.0)
    assert not verified("Net income was $19,309 million.", source).supported  # too few words to re-attribute


def test_repeated_release_citation_is_collapsed():
    sources = [release_source("S1", "a"), release_source("S2", "b")]
    assert render_citations("Up [S1][S2].", sources) == "Up [NVDA Q3 FY2025 release]."
    assert render_citations("Up [S1]. [S2]", sources) == "Up [NVDA Q3 FY2025 release]"
    pages = [Source("S1", TEN_K[0], 1.0), Source("S2", TEN_K[0], 1.0)]
    assert render_citations("Up [S1][S2].", pages) == "Up [NVDA FY2025 p.1][NVDA FY2025 p.1]."  # 10-K text unchanged


IPHONE_TABLE = "| ($ in millions) | Q1 FY25 | Q1 FY24 |\n|---|---|---|\n| iPhone | $69,138 | $69,702 |\n| Mac | $8,987 | $7,780 |"
TSLA_MODELS = "Q1-2024 Q2-2024 YoY\nModel 3/Y deliveries 369,783 422,405 -5%\nOther models deliveries 17,027 21,551 12%\nTotal deliveries 386,810 443,956 -5%"


@pytest.mark.parametrize("claim", [
    "Apple sold 69,138 million iPhone units in Q1 FY2025.",
    "Apple sold 69,138 iPhones units in the quarter.",
    "Apple shipped 8,987 million Mac devices.",
])
def test_a_count_cannot_rest_on_a_dollar_amount(claim):
    v = verified(claim, release_source("S1", IPHONE_TABLE, "AAPL"), cited=("S1",))
    assert not v.supported and v.unsupported_numbers


@pytest.mark.parametrize("claim", [
    "iPhone net sales were $69,138 million.",
    "iPhone net sales were 69,138 million dollars.",  # not a counted noun
    "iPhone revenue was $69.1 billion, and Mac revenue was $9.0 billion.",
])
def test_dollar_figures_stay_supported(claim):
    assert verified(claim, release_source("S1", IPHONE_TABLE, "AAPL"), cited=("S1",)).supported


@pytest.mark.parametrize("claim", [
    "422,405 Model Y vehicles were delivered in Q2 2024.",
    "Tesla delivered 422,405 Model 3 vehicles in Q2 2024.",
])
def test_one_product_cannot_claim_a_combined_row(claim):
    assert not verified(claim, release_source("S1", TSLA_MODELS, "TSLA"), cited=("S1",)).supported


@pytest.mark.parametrize("claim", [
    "Model 3/Y deliveries were 422,405 in Q2 2024.",
    "Tesla delivered 422,405 Model 3 and Model Y vehicles in Q2 2024.",
    "Tesla delivered 443,956 vehicles in Q2 2024.",
    "Tesla delivered 21,551 other models in Q2 2024.",
])
def test_combined_and_total_figures_stay_supported(claim):
    assert verified(claim, release_source("S1", TSLA_MODELS, "TSLA"), cited=("S1",)).supported


def test_a_relabelled_figure_is_not_rescued_by_citation_repair():
    other = release_source("S1", "Apple had a strong quarter.", "AAPL")
    table = release_source("S2", IPHONE_TABLE, "AAPL")
    assert not verified("Apple sold 69,138 million iPhone units.", other, table).supported  # no citation
    assert not verified("Apple sold 69,138 million iPhone units.", other, table, cited=("S1",)).supported


def test_a_fact_in_a_second_row_still_counts():
    """The figure also stated as a count elsewhere in the chunk: one fitting row is enough."""
    both = release_source("S1", "| iPhone revenue | $5,000 |\nTotal iPhone units 5,000", "AAPL")
    assert verified("Apple sold 5,000 iPhone units.", both, cited=("S1",)).supported


def test_10k_sources_skip_the_release_checks():
    source = Source("S1", make_chunk(0, "AAPL", 2025, "Item 7", IPHONE_TABLE), 1.0)
    assert verified("Apple sold 69,138 million iPhone units in the year.", source, cited=("S1",)).supported  # unchanged behavior


# --- the period a figure's column belongs to ---------------------------------------------------------

FLAT_TSLA = ("OPERATIONAL SUMMARY\n\nQ1-2023 Q2-2023 Q3-2023 Q4-2023 Q1-2024 YoY\n"
             "Total production 440,808 479,700 430,488 494,989 433,371 -2%\n"
             "Model 3/Y deliveries 412,180 446,915 419,074 461,538 369,783 -10%")
MD_NVDA = ("Summary\n\n|  |  |  | GAAP |\n| ($ in millions) | Q3 FY25 | Q2 FY25 | Q3 FY24 |\n|---|---|---|---|\n"
           "| Revenue | $35,082 | $30,040 | $18,120 |")
JPM = ("| Results |  |  | 4Q21 |\n|---|---|---|---|\n| ($ millions) | 1Q22 | 4Q21 | 1Q21 |\n| Net revenue | $30,717 | $29,257 | $32,266 |")
YEARS = "|  |  | Quarter Ended September 30, |\n|  | 2023 | 2024 |\n|---|---|---|\n| Google Cloud | 8,411 | 11,353 |"
MIXED = ("|  | Three Months Ended | Nine Months Ended |\n|  | 2023 | 2024 | 2023 | 2024 |\n|---|---|---|---|---|\n"
         "| Revenue | $18,120 | $35,082 | $38,819 | $91,166 |")


def table_source(text: str, ticker: str, year: int, quarter: int, period_end: str = "") -> Source:
    c = release_chunk(9, ticker, year, quarter, text)
    c.chunk_type, c.period_end = "table", period_end or f"{year}-12-31"
    c.context = f"{ticker} earnings release"
    return Source("S1", c, 1.0)


def test_labels_parse():
    assert [parse_label(x) for x in ("Q1-2024", "Q3 FY25", "Q1 2022", "1Q22", "3Q-2020", "30-Jun-24")] == [
        (1, 2024), (3, 2025), (1, 2022), (1, 2022), (3, 2020), (2, 2024)]
    assert parse_label("Q/Q") is None and parse_label("2024") is None and parse_label("YoY") is None


@pytest.mark.parametrize("text, ticker, year, quarter, wrong, right", [
    (FLAT_TSLA, "TSLA", 2024, 1, "Tesla produced 440,808 vehicles in Q1 2024.", "Tesla produced 433,371 vehicles in Q1 2024."),
    (MD_NVDA, "NVDA", 2025, 3, "NVIDIA's revenue in Q3 FY2025 was $30,040 million.", "NVIDIA's revenue in Q3 FY2025 was $35,082 million."),
    (JPM, "JPM", 2022, 1, "JPMorgan's net revenue in Q1 2022 was $29,257 million.", "JPMorgan's net revenue in Q1 2022 was $30,717 million."),
    (YEARS, "GOOGL", 2024, 3, "Google Cloud revenue in Q3 2024 was $8,411 million.", "Google Cloud revenue in Q3 2024 was $11,353 million."),
])
def test_a_figure_must_sit_in_the_column_of_the_period_it_names(text, ticker, year, quarter, wrong, right):
    source = table_source(text, ticker, year, quarter)
    assert not verified(wrong, source, cited=("S1",)).supported
    assert verified(right, source, cited=("S1",)).supported


def test_a_rounded_figure_finds_its_column():
    source = table_source(MD_NVDA, "NVDA", 2025, 3)
    assert verified("Revenue in Q3 FY2025 was $35.1 billion.", source, cited=("S1",)).supported
    assert not verified("Revenue in Q3 FY2025 was $30.0 billion.", source, cited=("S1",)).supported


def test_a_claim_with_no_period_means_the_release_s_own_quarter():
    source = table_source(FLAT_TSLA, "TSLA", 2024, 1)
    assert not verified("Total production was 440,808 vehicles.", source, cited=("S1",)).supported
    assert verified("Total production was 433,371 vehicles.", source, cited=("S1",)).supported


@pytest.mark.parametrize("claim", [
    "Production was 440,808 vehicles in Q1 2023.",  # the column it names
    "Production fell to 433,371 from 440,808 a year ago.",  # says it is another period
    "Production was 433,371 in Q1 2024, up from 440,808 in Q1 2023 compared with the prior year.",
    "In 2023 production included a quarter of 440,808 vehicles.",  # names a year only
])
def test_claims_about_other_periods_stay_supported(claim):
    assert verified(claim, table_source(FLAT_TSLA, "TSLA", 2024, 1), cited=("S1",)).supported


@pytest.mark.parametrize("text, claim", [
    ("Q1-2023 Q2-2023 Q1-2024\nProduction 1,000 (1) 2,000 3,000", "Production was 1,000 in Q1 2024."),  # a footnote shifts the row
    ("Q1-2023 Q1-2024\nProduction 1,000 2,000 7", "Production was 1,000 in Q1 2024."),  # a trailing page number
    ("|  | Q3 FY25 | Q3 FY24 |\n|---|---|---|\n| Revenue | $5 |", "Revenue in Q3 FY2025 was $5."),  # cells don't line up
])
def test_tables_it_cannot_read_get_no_verdict(text, claim):
    assert verified(claim, table_source(text, "NVDA", 2024, 3), cited=("S1",)).supported


def test_period_outside_the_table_gets_no_verdict():
    assert verified("Production was 440,808 vehicles in Q3 2022.", table_source(FLAT_TSLA, "TSLA", 2024, 1), cited=("S1",)).supported


def test_another_row_with_the_figure_in_the_right_column_is_enough():
    text = "Q1-2023 Q1-2024\nProduction 1,000 2,000\nDeliveries 3,000 1,000"
    assert verified("It was 1,000 in Q1 2024.", table_source(text, "TSLA", 2024, 1), cited=("S1",)).supported


def test_fiscal_year_unlike_the_calendar_year_reads_no_year_columns():
    text = "|  |  | Three Months Ended |\n|  | 2021 | 2020 |\n|---|---|---|\n| Revenue | $5,661 | $3,080 |"
    nvda = table_source(text, "NVDA", 2022, 1, period_end="2021-05-02")  # Q1 FY2022 ended in calendar 2021
    assert not known_periods(nvda.chunk)
    assert verified("Revenue in Q1 FY2022 was $3,080 million.", nvda, cited=("S1",)).supported


def test_count_on_a_money_table_row_without_its_own_dollar_sign():
    table = "| ($ in millions) | Q2 FY25 | Q2 FY24 |\n|---|---|---|\n| iPhone | $46,841 | $45,963 |\n| Mac | 7,949 | 7,451 |\n| Employees | 12,000 | 11,000 |"
    source = table_source(table, "AAPL", 2025, 2)
    assert not verified("Apple sold 7,949 million Mac units in Q2 FY2025.", source, cited=("S1",)).supported
    assert not verified("Apple sold 7,949 million Macs in Q2 FY2025.", source, cited=("S1",)).supported
    assert verified("Apple had 12,000 employees in Q2 FY2025.", source, cited=("S1",)).supported  # the row says what is counted
    assert verified("Mac net sales were 7,949 million in Q2 FY2025.", source, cited=("S1",)).supported


def test_year_to_date_columns_can_be_read_by_their_year():
    source = table_source(MIXED, "NVDA", 2024, 3)
    assert not verified("Revenue in Q3 2024 was $18,120 million.", source, cited=("S1",)).supported  # the 2023 column
    assert verified("Revenue in Q3 2024 was $35,082 million.", source, cited=("S1",)).supported


DATED_TWO_ROWS = ("|  |  | Three Months Ended | Six Months Ended |\n|  | July 28, | July 30, | July 28, | July 30, |\n"
                  "|  | 2024 | 2023 | 2024 | 2023 |\n|---|---|---|---|---|\n| Non-GAAP net income | $16,952 | $6,740 | $32,189 | $9,453 |")
DATED_ONE_ROW = "|  |  | Three Months Ended |\n|  | December 28, 2024 | December 30, 2023 |\n|---|---|---|\n| Products | $97,960 | $96,458 |"


def test_period_end_dates_use_the_company_s_fiscal_calendar():
    nvda = table_source(DATED_TWO_ROWS, "NVDA", 2025, 2, period_end="2024-07-28")
    assert known_periods(nvda.chunk) == {(2, 2025), (2, 2024)}
    assert not verified("Non-GAAP net income was $9,453 million in Q2 FY2025.", nvda, cited=("S1",)).supported  # year-ago year-to-date
    assert verified("Non-GAAP net income was $16,952 million in Q2 FY2025.", nvda, cited=("S1",)).supported
    apple = table_source(DATED_ONE_ROW, "AAPL", 2025, 1, period_end="2024-12-28")
    assert known_periods(apple.chunk) == {(1, 2025), (1, 2024)}
    assert not verified("Products net sales were $96,458 million in Q1 FY2025.", apple, cited=("S1",)).supported


def test_a_balance_sheet_s_dates_are_not_read_as_quarters():
    table = "|  | October 27, 2024 | January 28, 2024 |\n|---|---|---|\n| Cash | $9,107 | $7,280 |"
    assert not known_periods(table_source(table, "NVDA", 2025, 3, period_end="2024-10-27").chunk)


def test_a_wrong_column_outweighs_a_table_it_cannot_read():
    readable = table_source(FLAT_TSLA, "TSLA", 2024, 1)
    unreadable = release_source("S2", "Totals\nProduction 440,808 in the period", "TSLA")
    unreadable.chunk.chunk_type = "table"
    v = verify_claims([Claim(text="Tesla produced 440,808 vehicles in Q1 2024.", source_ids=["S1", "S2"])], [readable, unreadable])[0]
    assert not v.supported


def test_citation_repair_cannot_add_a_wrong_column():
    readable = table_source(FLAT_TSLA, "TSLA", 2024, 1)
    prose = release_source("S2", "Tesla had a strong quarter for production.", "TSLA")
    v = verify_claims([Claim(text="Total production was 440,808 vehicles in Q1 2024.", source_ids=["S2"])], [readable, prose])[0]
    assert not v.supported


def test_a_chart_axis_is_not_a_figure():
    axis = release_source("S1", "0 1 2 3 4 (200) (150) (100) (50) 50 100 150 200 Energy Storage deployments (GWh)", "TSLA")
    assert not verified("Tesla deployed 3.0 GWh of Energy Storage in Q3 2023.", axis, cited=("S1",)).supported
    assert verified("Tesla deployed 3.0 GWh of Energy Storage.", release_source("S1", "Storage deployed was 3.0 GWh, up from 2.4 GWh.", "TSLA"), cited=("S1",)).supported


def test_a_product_number_is_not_a_figure_for_the_column_check():
    text = "Q2-2024 Q3-2024 YoY\nModel 3/Y deliveries 422,405 439,975 5%\nInventory days 3 18 2%"
    source = table_source(text, "TSLA", 2024, 3)
    assert verified("Tesla delivered 439,975 Model 3 and Model Y vehicles in Q3 2024.", source, cited=("S1",)).supported
