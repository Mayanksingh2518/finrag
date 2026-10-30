"""Query analyzer: rule-based entities/years/sections and follow-up handling.

Phrasings here are deliberately different from the golden set, which the rules were tuned on.
"""

import pytest

from app.agent.analyze import QueryAnalyzer, StandaloneQuestion
from app.agent.entities import extract, find_tickers, find_years
from app.generation.llm import LLMError, LLMResponse


@pytest.mark.parametrize("text,tickers", [
    ("How did Instagram and WhatsApp affect Meta's ad revenue?", ("META",)),
    ("Compare YouTube ads with Amazon Web Services growth", ("GOOGL", "AMZN")),
    ("What did JP Morgan say about deposits versus Visa?", ("JPM", "V")),
    ("Is Xbox content growing faster than GeForce gaming?", ("MSFT", "NVDA")),
    ("Did Mastercard or Visa grow faster?", ("MA", "V")),  # order of mention
    ("What metadata does the 10-K include?", ()),  # "meta" only on a word boundary
    ("What was Netflix's revenue?", ()),
])
def test_tickers_from_names_brands_and_products(text, tickers):
    assert find_tickers(text) == tickers


@pytest.mark.parametrize("text,years,outside,relative", [
    ("revenue in FY 2023 and fiscal 2024", (2023, 2024), (), None),
    ("growth through 2022 to 2024", (2022, 2024), (), None),  # not a "from/between" range
    ("from fiscal year 2023 through fiscal year 2025", (2023, 2024, 2025), (), None),
    ("over the past two years", (2024, 2025), (), None),
    ("in the most recent fiscal year", (2025,), (), None),
    ("sales in 2019 and 2023", (2023,), (2019,), None),
    ("about 1,990 stores and $2025 million, up 20.25%", (), (), None),
    ("and in the prior year?", (), (), "prior"),
    ("what drove it in that year?", (), (), "same"),
])
def test_year_phrases(text, years, outside, relative):
    assert find_years(text) == (years, outside, relative)


def test_sections_only_for_unambiguous_cues():
    assert extract("What risk factors does Tesla list about China?").sections == ("Item 1A",)
    assert extract("How is cybersecurity governed at Visa?").sections == ("Item 1C",)
    assert extract("What were Apple's net sales?").sections == ()


def test_standalone_question_filters_and_out_of_range_refusal():
    a = QueryAnalyzer()
    r = a.analyze("Compare Azure and AWS growth between 2023 and 2025.")
    assert r.scope == "in_corpus" and r.filters.tickers == ("MSFT", "AMZN") and r.filters.fiscal_years == (2023, 2024, 2025)
    assert r.standalone_query == r.question and not r.rewritten

    refused = a.analyze("What will Apple's revenue be in 2028?")
    assert refused.scope == "out_of_range" and "2028" in refused.reason and refused.filters.is_empty()
    mixed = a.analyze("Compare Apple's net sales in 2019 and 2024.")  # partly covered: answer that part
    assert mixed.scope == "in_corpus" and mixed.filters.fiscal_years == (2024,)


class RewriteLLM:
    def __init__(self, text: str | None):
        self.text = text
        self.messages = None

    def generate(self, messages, output):
        self.messages = messages
        if self.text is None:
            raise LLMError("all providers failed")
        assert output is StandaloneQuestion
        return StandaloneQuestion(standalone_question=self.text), LLMResponse(text="", provider="fake", model="fake")


HISTORY = ("What was Visa's net revenue in fiscal 2024?", "$35.9 billion, up 10%.")


def test_follow_up_inherits_subject_and_resolves_relative_years():
    a = QueryAnalyzer()  # no LLM: filters still come from the conversation
    other_company = a.analyze("And Mastercard's?", HISTORY)
    assert other_company.filters.tickers == ("MA",) and other_company.filters.fiscal_years == (2024,)
    assert other_company.carried_over == ("fiscal_years",)
    assert other_company.standalone_query.startswith(HISTORY[0])  # crude fallback keeps the subject

    before = a.analyze("What about the year before?", HISTORY)
    assert before.filters.tickers == ("V",) and before.filters.fiscal_years == (2023,)
    later = a.analyze("How about 2025?", HISTORY)
    assert later.filters.tickers == ("V",) and later.filters.fiscal_years == (2025,)


def test_follow_up_uses_llm_rewrite_and_survives_its_failure():
    llm = RewriteLLM("What was Mastercard's net revenue in fiscal 2024?")
    r = QueryAnalyzer(llm).analyze("And Mastercard's?", HISTORY)
    assert r.rewritten and r.standalone_query == "What was Mastercard's net revenue in fiscal 2024?"
    assert "Visa's net revenue" in llm.messages[1]["content"] and "Last question: And Mastercard's?" in llm.messages[1]["content"]
    assert r.filters.tickers == ("MA",) and r.filters.fiscal_years == (2024,)

    failed = QueryAnalyzer(RewriteLLM(None)).analyze("And Mastercard's?", HISTORY)
    assert not failed.rewritten and failed.filters.tickers == ("MA",)


def test_standalone_question_mid_conversation_skips_rewrite_and_carry_over():
    llm = RewriteLLM("should not be called")
    r = QueryAnalyzer(llm).analyze("What were Meta's capital expenditures in 2025?", HISTORY)
    assert llm.messages is None and not r.carried_over
    assert r.filters.tickers == ("META",) and r.filters.fiscal_years == (2025,)
    # Refers back ("its"), so it is still a follow-up even though it names a company and year.
    assert QueryAnalyzer().analyze("How did Visa's growth compare with its 2023 rate?", HISTORY).carried_over == ()


def test_out_of_range_year_is_refused_mid_conversation():
    r = QueryAnalyzer().analyze("What were Apple's iPhone net sales in fiscal 2018?", HISTORY)
    assert r.scope == "out_of_range" and "2018" in r.reason


# --- Retrieval plan -------------------------------------------------------------------------

from app.agent.plan import apply_prior, classify_intent, execute_plan, make_plan, section_prior  # noqa: E402
from app.retrieval.types import ScoredChunk, SearchFilters  # noqa: E402
from tests.test_retrieval import CHUNKS, FakeEmbedder, make_chunk  # noqa: E402


@pytest.mark.parametrize("question,filters,intent", [
    ("Is AWS bigger than Azure?", SearchFilters(("AMZN", "MSFT")), "comparison"),
    ("Compare Apple's margins with last year", SearchFilters(("AAPL",)), "comparison"),
    ("How did Visa's operating expenses change from 2023?", SearchFilters(("V",)), "trend"),
    ("Tesla's free cash flow, 2023 and 2024", SearchFilters(("TSLA",), (2023, 2024)), "trend"),
    ("How many Model Y units were produced?", SearchFilters(("TSLA",)), "numeric"),
    ("What did Meta say about AI glasses?", SearchFilters(("META",)), "lookup"),
])
def test_intent_rules(question, filters, intent):
    assert classify_intent(question, filters) == intent


def test_section_prior_only_for_reported_metrics():
    assert section_prior("What was Alphabet's operating income in 2024?") == {"Item 7": 0.05}
    assert section_prior("How many deliveries did Tesla make?", bonus=0.1) == {"Item 7": 0.1}
    assert section_prior("Who sits on Microsoft's audit committee?") == {}
    assert section_prior("What was Apple's revenue?", bonus=0.0) == {}


def test_quota_is_shared_k_with_a_floor():
    single = make_plan("q", SearchFilters(("MSFT",), (2025,)), k=10)
    assert not single.decomposed and single.quota == 10
    trend = make_plan("q", SearchFilters(("MSFT",), (2022, 2023, 2024, 2025)), k=10)
    assert len(trend.sub_queries) == 4 and trend.quota == 3
    wide = make_plan("q", SearchFilters(("MSFT", "AMZN"), (2022, 2023, 2024, 2025)), k=10)
    assert len(wide.sub_queries) == 8 and wide.quota == 2  # floor: more than k hits, budget trims tails


def test_prior_lifts_mdna_without_overriding_a_clearly_better_chunk():
    def hit(i, section, score):
        return ScoredChunk(make_chunk(i, "JPM", 2024, section, f"text {i}"), score)

    near = apply_prior([hit(0, "Item 8", 0.99), hit(1, "Item 7", 0.96)], {"Item 7": 0.05})
    assert [h.chunk.section for h in near] == ["Item 7", "Item 8"] and near[0].stages["section_prior"] == 0.05
    far = apply_prior([hit(0, "Item 1A", 0.99), hit(1, "Item 7", 0.40)], {"Item 7": 0.05})
    assert far[0].chunk.section == "Item 1A"


class PairReranker:
    """Scores by passage length (shorter = better) and records how often it was called."""

    model_name = "pairs"

    def __init__(self):
        self.calls = []

    def score(self, query, passages):
        raise AssertionError("search_many should batch through score_pairs")

    def score_pairs(self, pairs):
        self.calls.append(len(pairs))
        return [1.0 / len(p) for _, p in pairs]


@pytest.fixture
def plan_retriever():
    from app.retrieval.bm25 import BM25Index
    from app.retrieval.dense import DenseIndex
    from app.retrieval.retriever import Retriever
    from app.retrieval.store import ChunkStore

    # Item 7's text is longer, so the length-based PairReranker strictly prefers Item 8: no tie whose
    # outcome depends on first-stage candidate order (that differed on GitHub's x86 runners).
    chunks = CHUNKS + [make_chunk(10 + i, "MSFT", y, s, f"Revenue grew {y} {s} cloud{extra}") for i, (y, s, extra) in
                       enumerate([(2024, "Item 8", ""), (2024, "Item 7", " services"), (2025, "Item 1", "")])]
    emb = FakeEmbedder()
    return Retriever(ChunkStore(chunks), BM25Index([c.embed_text for c in chunks]),
                     DenseIndex(emb.embed_documents([c.embed_text for c in chunks])), emb, PairReranker(),
                     candidates_per_retriever=10)


def test_plan_reranks_all_sub_queries_in_one_call_and_interleaves(plan_retriever):
    plan = make_plan("cloud revenue", SearchFilters(("MSFT", "AMZN"), (2024, 2025)), k=4, section_bonus=0.0)
    result = execute_plan(plan_retriever, plan)
    assert len(plan_retriever.reranker.calls) == 1  # 4 sub-queries, one model call
    assert result.hits and len({h.chunk.chunk_id for h in result.hits}) == len(result.hits)
    first_tier = {(h.chunk.ticker, h.chunk.fiscal_year) for h in result.hits[:3]}
    assert first_tier == {("MSFT", 2024), ("MSFT", 2025), ("AMZN", 2025)}  # AMZN FY2024 has no chunks
    assert result.timings_ms["rerank"] >= 0 and result.timings_ms["total"] >= result.timings_ms["rerank"]


def test_plan_applies_section_prior_before_the_quota_cut(plan_retriever):
    filters = SearchFilters(("MSFT",), (2024,))
    plain = execute_plan(plan_retriever, make_plan("revenue grew", filters, k=1, section_bonus=0.0))
    boosted = execute_plan(plan_retriever, make_plan("revenue grew", filters, k=1, section_bonus=0.5))
    assert plain.hits[0].chunk.section == "Item 8"  # the reranker prefers the shorter Item 8 chunk
    assert boosted.hits[0].chunk.section == "Item 7"  # the MD&A prior outweighs that preference


@pytest.mark.parametrize("question", [
    "What is Microsoft's current stock price?",
    "How much is a Tesla share trading at right now?",
    "What's Apple's market cap today?",
    "What is NVIDIA's current market capitalization?",
])
def test_live_market_data_is_out_of_scope(question):
    a = QueryAnalyzer().analyze(question)
    assert a.scope == "live_data" and not a.answerable_scope


@pytest.mark.parametrize("question", [
    "What were Apple's current liabilities in fiscal 2025?",  # "current" without a market quantity
    "What was the average price per share Microsoft paid for repurchases in fiscal 2025?",  # no live cue
    "How does Visa describe its current market position?",
    "What is Tesla's current valuation allowance on deferred tax assets in 2024?",  # a tax term, not a price
])
def test_live_data_rule_leaves_filing_questions_alone(question):
    assert QueryAnalyzer().analyze(question).scope == "in_corpus"
