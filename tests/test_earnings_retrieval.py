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
