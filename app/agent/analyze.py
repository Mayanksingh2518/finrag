"""Query analysis: question (+ conversation) -> retrieval filters, standalone query, scope.

Filters come from rules (`entities.py`); the LLM only rewrites follow-ups ("And Mastercard's?")
into standalone questions. For a follow-up, missing companies/years are carried over from the
conversation, and "the year before" / "that year" resolve against the year discussed last.
Questions that only ask about years outside the corpus are refused before any retrieval.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.entities import CORPUS_YEARS, Entities, extract
from app.generation.llm import LLM, LLMError, Message
from app.retrieval.types import SearchFilters

log = logging.getLogger(__name__)

Scope = Literal["in_corpus", "out_of_range"]

REWRITE_PROMPT = """Rewrite the user's last question as one standalone question that can be understood without
the conversation. Resolve pronouns and ellipsis ("its", "that year", "And Mastercard's?", "the year before")
using the conversation: name the company and the fiscal year explicitly. Keep the user's wording otherwise.
Do not answer the question. If it is already standalone, return it unchanged."""


class StandaloneQuestion(BaseModel):
    standalone_question: str = Field(description="The question rewritten to be self-contained.")


@dataclass(frozen=True)
class QueryAnalysis:
    question: str
    standalone_query: str  # what retrieval and generation should use
    filters: SearchFilters
    scope: Scope
    reason: str = ""  # why the question is out of scope
    rewritten: bool = False  # standalone_query came from the LLM rewrite
    carried_over: tuple[str, ...] = ()  # filter fields taken from the conversation ("tickers", "fiscal_years")

    @property
    def answerable_scope(self) -> bool:
        return self.scope == "in_corpus"


def _rewrite(llm: LLM, question: str, history: Sequence[str]) -> str | None:
    turns = "\n".join(f"{'User' if i % 2 == 0 else 'Assistant'}: {t}" for i, t in enumerate(history))
    messages: list[Message] = [
        {"role": "system", "content": REWRITE_PROMPT},
        {"role": "user", "content": f"Conversation:\n{turns}\n\nLast question: {question}"},
    ]
    try:
        out, _ = llm.generate(messages, StandaloneQuestion)
    except LLMError as e:
        log.warning("follow-up rewrite failed, using the raw question: %s", e)
        return None
    text = out.standalone_question.strip()
    return text or None


# Words that point back into the conversation ("its revenue", "that segment", "the same period").
_ANAPHORA = re.compile(r"\b(?:its|it|they|their|them|that|those|these|this|same|also|too|else)\b|^\s*(?:and|how about|what about)\b",
                       re.IGNORECASE)


def is_standalone(question: str, own: Entities) -> bool:
    """Names its own company and year and doesn't refer back: no carry-over, no LLM rewrite needed."""
    return bool(own.tickers and own.fiscal_years and not own.relative_year and not _ANAPHORA.search(question))


class QueryAnalyzer:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm  # optional: without it, follow-ups keep their wording but still inherit filters

    def analyze(self, question: str, history: Sequence[str] = ()) -> QueryAnalysis:
        """`history` alternates user and assistant turns, oldest first."""
        own = extract(question)
        if own.out_of_range_years and not own.fiscal_years:  # also mid-conversation: never inherit a year
            years = ", ".join(map(str, own.out_of_range_years))
            return QueryAnalysis(question, question, SearchFilters(), "out_of_range",
                                 f"The filings cover fiscal {CORPUS_YEARS[0]}-{CORPUS_YEARS[-1]}; the question asks about {years}.")
        if history and not is_standalone(question, own):
            return self._follow_up(question, own, history)
        return QueryAnalysis(question, question, _filters(own.tickers, own.fiscal_years, own.sections), "in_corpus")

    def _follow_up(self, question: str, own: Entities, history: Sequence[str]) -> QueryAnalysis:
        # The conversation's subject: the most recent user turn that names a company or year.
        user_turns = history[::2]
        context = next((e for e in map(extract, reversed(user_turns)) if e.tickers or e.fiscal_years),
                       extract(" ".join(history)))
        rewrite = _rewrite(self.llm, question, history) if self.llm else None
        from_rewrite = extract(rewrite) if rewrite else None
        carried: list[str] = []

        tickers = own.tickers
        if not tickers:
            tickers = (from_rewrite.tickers if from_rewrite else ()) or context.tickers
            carried.append("tickers")
        years = own.fiscal_years
        if not years:
            if own.relative_year == "prior" and context.fiscal_years:
                years = tuple(y - 1 for y in context.fiscal_years if y - 1 in CORPUS_YEARS)
            elif own.relative_year == "same" or not (from_rewrite and from_rewrite.fiscal_years):
                years = context.fiscal_years
            else:
                years = from_rewrite.fiscal_years
            carried.append("fiscal_years")
        sections = own.sections or (from_rewrite.sections if from_rewrite else ())
        standalone = rewrite or f"{user_turns[-1]} {question}"  # crude, but keeps the subject for retrieval
        return QueryAnalysis(question, standalone, _filters(tickers, years, sections), "in_corpus",
                             rewritten=bool(rewrite), carried_over=tuple(carried))


def _filters(tickers: Sequence[str], years: Sequence[int], sections: Sequence[str]) -> SearchFilters:
    return SearchFilters(tuple(tickers) or None, tuple(years) or None, tuple(sections) or None)
