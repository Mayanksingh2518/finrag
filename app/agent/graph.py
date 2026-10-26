"""The FinRAG agent as a LangGraph graph: analyze -> (refuse | retrieve + XBRL facts) -> generate -> verify.

    START -> analyze --out of range--> refuse ------------------------------> respond -> END
                     \\--in corpus--> retrieve --+--> generate --> verify --+--> respond
                      \\-----------> xbrl -------/        \\(no sources)--/  |
                                ^--------------- widen (once) <-----/   (widen feeds retrieve and xbrl)

- analyze: rule-based filters + LLM rewrite of follow-ups (`analyze.py`); no gold filters.
- retrieve / xbrl run in the same step (fan-out): the retrieval plan (`plan.py`) and, when the
  question names a company-level metric and a year, exact XBRL facts (`xbrl.py`). Facts go first
  in the context: ~40 tokens each, and the generator is told when the filing text wins.
- verify: claim-level citation check (`verify.py`); no verified claim = abstention.
- widen: one retry when an answer abstains under a section filter (a wrong section filter hides
  the answer; the analyzer sets one only on unambiguous cues, so this is rare). The filter is
  dropped and retrieval runs again.

Memory: a conversation is the list of its turns (user question, assistant answer, alternating),
kept per thread id by `ConversationMemory` and passed into the graph as `history`. Per-turn work
(chunks, sources, claims) is not checkpointed: LangGraph's checkpointer would store every step's
chunks for every thread, and the analyzer only needs the turns.
"""

import logging
import operator
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.analyze import QueryAnalysis, QueryAnalyzer
from app.agent.plan import RetrievalPlan, execute_plan, make_plan
from app.agent.xbrl import XbrlFact, XbrlStore, detect_metrics, fact_chunks
from app.generation.answer import AnswerResult, Answerer, finalize, no_sources
from app.generation.context import Source, build_sources
from app.generation.llm import LLM, LLMResponse
from app.generation.schemas import GeneratedAnswer
from app.retrieval.types import ScoredChunk, SearchMode

log = logging.getLogger(__name__)

MAX_FACTS = 8  # e.g. 4 years x 2 metrics; more would crowd filing text out of the context
MAX_TEXT_SOURCES = 12


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class AgentState(TypedDict, total=False):
    question: str
    history: list[str]  # earlier turns, oldest first: user, assistant, user, ...
    analysis: QueryAnalysis
    plan: RetrievalPlan
    hits: list[ScoredChunk]
    facts: list[XbrlFact]
    sources: list[Source]
    generated: GeneratedAnswer
    response: LLMResponse
    result: AnswerResult
    widened: bool
    steps: Annotated[list[str], operator.add]  # node trace, for the UI and evals
    timings_ms: Annotated[dict[str, float], _merge]


@dataclass
class AgentTurn:
    question: str
    analysis: QueryAnalysis
    result: AnswerResult
    plan: RetrievalPlan | None = None
    facts: list[XbrlFact] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)

    @property
    def assistant_text(self) -> str:
        """What the conversation remembers as the assistant's turn."""
        r = self.result
        return r.answer if not r.abstained else f"I could not answer from the filings: {r.abstain_reason}"


class ConversationMemory:
    """Turns per thread id, newest threads kept (LRU), each trimmed to the last `max_turns` exchanges."""

    def __init__(self, max_threads: int = 1000, max_turns: int = 6):
        self.max_threads = max_threads
        self.max_turns = max_turns
        self._threads: OrderedDict[str, list[str]] = OrderedDict()

    def history(self, thread_id: str) -> list[str]:
        return list(self._threads.get(thread_id, []))

    def append(self, thread_id: str, question: str, answer: str) -> None:
        turns = self._threads.pop(thread_id, []) + [question, answer]
        self._threads[thread_id] = turns[-2 * self.max_turns:]
        while len(self._threads) > self.max_threads:
            self._threads.popitem(last=False)

    def clear(self, thread_id: str) -> None:
        self._threads.pop(thread_id, None)


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


class FinRAGAgent:
    def __init__(self, retriever, llm: LLM, xbrl: XbrlStore | None = None, token_budget: int = 3500, k: int = 10,
                 mode: SearchMode = "hybrid_rerank", memory: ConversationMemory | None = None,
                 rewrite_follow_ups: bool = True):
        self.retriever = retriever
        self.answerer = Answerer(retriever, llm, token_budget=token_budget, k=k, mode=mode)
        self.analyzer = QueryAnalyzer(llm if rewrite_follow_ups else None)
        self.xbrl = xbrl
        self.token_budget = token_budget
        self.k = k
        self.mode = mode
        self.memory = memory or ConversationMemory()
        self.graph = self._build()

    # --- nodes ---------------------------------------------------------------------------------

    def _analyze(self, state: AgentState) -> dict:
        start = time.perf_counter()
        analysis = self.analyzer.analyze(state["question"], state.get("history") or ())
        return {"analysis": analysis, "steps": ["analyze"], "timings_ms": {"analyze": _ms(start)}}

    def _refuse(self, state: AgentState) -> dict:
        a = state["analysis"]
        result = AnswerResult(a.question, "", True, a.reason, "none", [], [], [], {})
        return {"result": result, "steps": ["refuse"]}

    def _retrieve(self, state: AgentState) -> dict:
        start = time.perf_counter()
        a = state["analysis"]
        filters = a.filters
        if state.get("widened"):
            filters = replace(filters, sections=None)
        plan = make_plan(a.standalone_query, filters, k=self.k)
        hits = execute_plan(self.retriever, plan, mode=self.mode).hits
        return {"plan": plan, "hits": hits, "steps": ["retrieve"], "timings_ms": {"retrieval": _ms(start)}}

    def _lookup_facts(self, state: AgentState) -> dict:
        a = state["analysis"]
        metrics = detect_metrics(a.standalone_query)
        tickers, years = a.filters.tickers or (), a.filters.fiscal_years or ()
        # No year named -> no facts: four years of figures would swamp a yearless lookup.
        facts = (self.xbrl.lookup_many(tickers, metrics, years)[:MAX_FACTS]
                 if self.xbrl and metrics and tickers and years else [])
        return {"facts": facts, "steps": ["xbrl"]}

    def _generate(self, state: AgentState) -> dict:
        facts = state.get("facts") or []
        plan = state.get("plan")
        intent = plan.intent if plan else None
        # Trend/comparison: a company's metric over several years goes in as one table with YoY
        # changes and directions computed in code (see `series_chunk`).
        chunks = fact_chunks(facts, series=intent in ("trend", "comparison"))
        fact_hits = [ScoredChunk(c, 1.0, {"xbrl": 1.0}) for c in chunks]
        sources = build_sources(fact_hits + list(state.get("hits") or []), self.token_budget,
                                max_sources=MAX_TEXT_SOURCES + len(fact_hits))
        timings: dict[str, float] = {}
        if not sources:
            return {"sources": [], "result": no_sources(state["analysis"].question, timings), "steps": ["generate"]}
        generated, response = self.answerer.generate(state["analysis"].standalone_query, sources, timings, intent)
        return {"sources": sources, "generated": generated, "response": response, "result": None,
                "steps": ["generate"], "timings_ms": timings}

    def _verify(self, state: AgentState) -> dict:
        start = time.perf_counter()
        result = finalize(state["question"], state["generated"], state["response"], state["sources"], {})
        return {"result": result, "steps": ["verify"], "timings_ms": {"verify": _ms(start)}}

    def _widen(self, state: AgentState) -> dict:
        return {"widened": True, "steps": ["widen"]}

    # --- edges ---------------------------------------------------------------------------------

    @staticmethod
    def _scope(state: AgentState) -> list[str] | Literal["refuse"]:
        return ["retrieve", "xbrl"] if state["analysis"].answerable_scope else "refuse"

    @staticmethod
    def _after_generate(state: AgentState) -> Literal["verify", "respond"]:
        return "respond" if state.get("result") is not None else "verify"

    @staticmethod
    def _after_verify(state: AgentState) -> Literal["widen", "respond"]:
        r, a = state["result"], state["analysis"]
        if r.abstained and a.filters.sections and not state.get("widened"):
            return "widen"
        return "respond"

    def _build(self):
        g = StateGraph(AgentState)
        g.add_node("analyze", self._analyze)
        g.add_node("refuse", self._refuse)
        g.add_node("retrieve", self._retrieve)
        g.add_node("xbrl", self._lookup_facts)
        g.add_node("generate", self._generate)
        g.add_node("verify", self._verify)
        g.add_node("widen", self._widen)
        g.add_node("respond", lambda state: {"steps": ["respond"]})
        g.add_edge(START, "analyze")
        g.add_conditional_edges("analyze", self._scope, ["retrieve", "xbrl", "refuse"])
        g.add_edge(["retrieve", "xbrl"], "generate")  # waits for both branches
        g.add_conditional_edges("generate", self._after_generate, ["verify", "respond"])
        g.add_conditional_edges("verify", self._after_verify, ["widen", "respond"])
        g.add_edge("widen", "retrieve")
        g.add_edge("widen", "xbrl")  # the join before generate needs both branches again
        g.add_edge("refuse", "respond")
        g.add_edge("respond", END)
        return g.compile()

    # --- public API ----------------------------------------------------------------------------

    def run(self, question: str, history: Sequence[str] = ()) -> AgentTurn:
        """One turn with an explicit history (stateless; evals use this)."""
        start = time.perf_counter()
        state = self.graph.invoke({"question": question, "history": list(history), "steps": [], "timings_ms": {}})
        result: AnswerResult = state["result"]
        timings = {**state.get("timings_ms", {}), "total": _ms(start)}
        result.timings_ms = {**result.timings_ms, **timings}
        return AgentTurn(question, state["analysis"], result, state.get("plan"), state.get("facts") or [],
                         state.get("steps", []), timings)

    def ask(self, question: str, thread_id: str) -> AgentTurn:
        """One turn of a conversation: history comes from, and goes back to, the thread's memory."""
        turn = self.run(question, self.memory.history(thread_id))
        self.memory.append(thread_id, question, turn.assistant_text)
        return turn


def build_agent(rewrite_follow_ups: bool = True) -> FinRAGAgent:
    from app.config import get_settings
    from app.generation.llm import build_llm
    from app.retrieval.factory import build_retriever

    settings = get_settings()
    return FinRAGAgent(build_retriever(), build_llm(settings), xbrl=XbrlStore.from_settings(),
                       token_budget=settings.context_token_budget, rewrite_follow_ups=rewrite_follow_ups)


def main() -> None:
    """Ask questions as one conversation: python -m app.agent.graph "Q1" "And the year before?" ..."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("questions", nargs="*", help="asked in order in one thread; none = interactive")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    agent = build_agent()

    def show(q: str) -> None:
        t = agent.ask(q, thread_id="cli")
        a = t.analysis
        print(f"\nQ: {q}\n   query: {a.standalone_query}\n   filters: tickers={a.filters.tickers} "
              f"years={a.filters.fiscal_years} sections={a.filters.sections}  steps: {' > '.join(t.steps)}")
        if t.facts:
            print("   facts: " + ", ".join(f.citation for f in t.facts))
        r = t.result
        print(f"A ({r.confidence}, {r.provider or '-'}): " + (r.answer or f"[abstained] {r.abstain_reason}"))
        print("   timings ms: " + ", ".join(f"{k}={v:.0f}" for k, v in t.timings_ms.items()))

    if args.questions:
        for q in args.questions:
            show(q)
    else:
        while (q := input("\n> ").strip()) not in ("", "exit", "quit"):
            show(q)


if __name__ == "__main__":
    main()
