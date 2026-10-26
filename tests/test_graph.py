"""LangGraph agent: routing, XBRL facts in the context, follow-up memory, the widen retry.

The retriever and LLM are scripted fakes; the XBRL store reads the real-data NVIDIA fixture.
"""

import json
from pathlib import Path

import pytest

from app.agent.analyze import StandaloneQuestion
from app.agent.graph import ConversationMemory, FinRAGAgent
from app.agent.xbrl import XbrlStore, load_filing_periods
from app.generation.llm import LLMResponse
from app.retrieval.types import ScoredChunk, SearchFilters, SearchResult
from tests.test_retrieval import make_chunk

FIXTURES = Path(__file__).parent / "fixtures"

CHUNKS = [
    make_chunk(0, "NVDA", 2025, "Item 7", "Revenue for fiscal year 2025 was $130.5 billion, up 114%."),
    make_chunk(1, "NVDA", 2024, "Item 7", "Revenue for fiscal year 2024 was $60.9 billion, up 126%."),
    make_chunk(2, "NVDA", 2025, "Item 1A", "Export controls to China restrict sales of data center GPUs."),
    make_chunk(3, "AAPL", 2025, "Item 7", "Total net sales were $416,161 million in 2025."),
]


class FakeRetriever:
    rerank_candidates = 30

    def __init__(self, chunks):
        self.chunks = chunks
        self.calls: list[list] = []

    def _match(self, c, f) -> bool:
        return ((not f.tickers or c.ticker in f.tickers) and (not f.fiscal_years or c.fiscal_year in f.fiscal_years)
                and (not f.sections or c.section in f.sections))

    def search_many(self, queries, k=10, mode="hybrid_rerank", rerank_candidates=None):
        self.calls.append(queries)
        return [SearchResult(q, mode, f, [ScoredChunk(c, 0.8) for c in self.chunks if self._match(c, f)][:k])
                for q, f in queries]


class ScriptedLLM:
    """Returns the next scripted output for each schema; records every prompt."""

    def __init__(self, answers=(), rewrites=()):
        self.answers, self.rewrites = list(answers), list(rewrites)
        self.prompts: list[list[dict]] = []

    def generate(self, messages, output):
        self.prompts.append(list(messages))
        data = self.rewrites.pop(0) if output is StandaloneQuestion else self.answers.pop(0)
        return output.model_validate(data), LLMResponse(text=json.dumps(data), provider="fake", model="fake")


def answer(text, *ids, abstained=False):
    if abstained:
        return {"answer": "", "claims": [], "abstained": True, "abstain_reason": text}
    return {"answer": f"{text} {''.join(f'[{i}]' for i in ids)}", "claims": [{"text": text, "source_ids": list(ids)}],
            "abstained": False, "abstain_reason": ""}


@pytest.fixture
def xbrl(tmp_path):
    (tmp_path / "NVDA.json").write_text((FIXTURES / "companyfacts_nvda_sample.json").read_text())
    return XbrlStore(tmp_path, load_filing_periods(FIXTURES / "manifest_nvda_sample.json"))


def make_agent(llm, xbrl=None, chunks=CHUNKS):
    return FinRAGAgent(FakeRetriever(chunks), llm, xbrl=xbrl, mode="hybrid")


def test_out_of_range_question_is_refused_without_retrieval():
    llm = ScriptedLLM()
    agent = make_agent(llm)
    turn = agent.run("What were Apple's total net sales in fiscal 2019?")
    assert turn.steps == ["analyze", "refuse", "respond"]
    assert turn.result.abstained and "2019" in turn.result.abstain_reason
    assert agent.retriever.calls == [] and llm.prompts == []


def test_metric_question_puts_xbrl_facts_first_and_verifies_against_them(xbrl):
    llm = ScriptedLLM(answers=[answer("NVIDIA's fiscal 2025 revenue was $130.5 billion, up 114%.", "S1")])
    turn = make_agent(llm, xbrl).run("What was NVIDIA's total revenue in fiscal 2025?")
    assert set(turn.steps) == {"analyze", "retrieve", "xbrl", "generate", "verify", "respond"}
    assert [f.citation for f in turn.facts] == ["[XBRL NVDA FY2025 Total revenue]"]
    sources = turn.result.sources
    assert sources[0].is_xbrl and not sources[1].is_xbrl
    system = llm.prompts[0][0]["content"]
    assert "XBRL financial data" in system  # the extra rule is only added with facts
    assert not turn.result.abstained and turn.result.confidence == "high"
    assert "[XBRL NVDA FY2025 Total revenue]" in turn.result.answer


def test_no_facts_without_a_metric_or_a_year(xbrl):
    llm = ScriptedLLM(answers=[answer("Export controls restrict sales to China.", "S1")] * 2)
    agent = make_agent(llm, xbrl)
    assert agent.run("What are NVIDIA's China export risks in fiscal 2025?").facts == []
    assert agent.run("What was NVIDIA's revenue?").facts == []  # no year named
    assert "XBRL" not in llm.prompts[0][0]["content"]


def test_follow_up_uses_thread_memory(xbrl):
    llm = ScriptedLLM(
        answers=[answer("Revenue was $130.5 billion.", "S1"), answer("Revenue was $60.9 billion.", "S1")],
        rewrites=[{"standalone_question": "What was NVIDIA's total revenue in fiscal 2024?"}],
    )
    agent = make_agent(llm, xbrl)
    agent.ask("What was NVIDIA's total revenue in fiscal 2025?", thread_id="t1")
    turn = agent.ask("And the year before?", thread_id="t1")
    assert turn.analysis.filters.tickers == ("NVDA",) and turn.analysis.filters.fiscal_years == (2024,)
    assert turn.analysis.rewritten
    assert [f.fiscal_year for f in turn.facts] == [2024]
    assert "$60.9 billion" in turn.result.answer
    history = agent.memory.history("t1")
    assert history[0] == "What was NVIDIA's total revenue in fiscal 2025?" and len(history) == 4
    assert agent.memory.history("other") == []


def test_abstention_under_a_section_filter_widens_once():
    llm = ScriptedLLM(answers=[answer("Not in these passages.", abstained=True),
                               answer("Revenue for fiscal year 2025 was $130.5 billion.", "S1")])
    agent = make_agent(llm)
    turn = agent.run("What risk factors mention revenue of $130.5 billion for NVIDIA in fiscal 2025?")
    assert turn.analysis.filters.sections  # "risk" -> Item 1A
    assert turn.steps.count("retrieve") == 2 and "widen" in turn.steps
    assert agent.retriever.calls[1][0][1].sections is None
    assert not turn.result.abstained


def test_no_sources_abstains_without_calling_the_llm():
    llm = ScriptedLLM()
    turn = make_agent(llm, chunks=[]).run("What was Tesla's revenue in 2024?")
    assert turn.result.abstained and llm.prompts == []
    assert "verify" not in turn.steps


def test_memory_trims_turns_and_evicts_old_threads():
    memory = ConversationMemory(max_threads=2, max_turns=2)
    for i in range(3):
        memory.append("a", f"q{i}", f"a{i}")
    assert memory.history("a") == ["q1", "a1", "q2", "a2"]
    memory.append("b", "q", "a")
    memory.append("c", "q", "a")
    assert memory.history("a") == []  # least recently used thread dropped


def test_agent_eval_counts_a_verified_xbrl_citation_as_an_evidence_hit(xbrl):
    from app.evaluation.golden import GoldEvidence, GoldQuestion
    from app.evaluation.run_agent_eval import record, summarize_agent

    llm = ScriptedLLM(answers=[answer("NVIDIA's fiscal 2025 revenue was $130.5 billion, up 114%.", "S1")])
    turn = make_agent(llm, xbrl).run("What was NVIDIA's total revenue for fiscal 2025?")
    q = GoldQuestion("N04", "numeric", turn.question, "$130.5 billion, up 114% from a year ago.",
                     (GoldEvidence("NVDA", 2025, (40,), ("Revenue",)),), SearchFilters(("NVDA",), (2025,)))
    rec = record(q, turn, "agent")
    assert rec.citation_hit == 0.0  # the page-based metric can't see an XBRL citation
    assert rec.citation_hit_xbrl == 1.0 and rec.xbrl_cited and rec.facts == 1 and rec.filters_ok
    assert summarize_agent([rec])["questions_with_facts"] == 1


def test_trend_question_gets_a_series_table_and_the_trend_rule(xbrl):
    llm = ScriptedLLM(answers=[answer("Revenue rose from $26,914 million to $130,497 million.", "S1")])
    turn = make_agent(llm, xbrl).run("How did NVIDIA's total revenue change from fiscal 2022 to fiscal 2025?")
    assert turn.plan.intent == "trend" and len(turn.facts) == 4
    xbrl_sources = [s for s in turn.result.sources if s.is_xbrl]
    assert [s.citation for s in xbrl_sources] == ["[XBRL NVDA Total revenue FY2022-FY2025]"]
    system = llm.prompts[0][0]["content"]
    assert "one line per fiscal year asked" in system and "not a CAGR" in system
    assert not turn.result.abstained


def test_lookup_prompt_has_no_intent_rule():
    llm = ScriptedLLM(answers=[answer("Export controls restrict sales to China.", "S1")])
    make_agent(llm).run("What are NVIDIA's China export risks in fiscal 2025?")
    system = llm.prompts[0][0]["content"]
    assert "one line per fiscal year" not in system and "compares companies" not in system
