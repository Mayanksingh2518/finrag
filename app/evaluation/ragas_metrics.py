"""RAGAS metrics as a second opinion on the LLM judge, run through FinRAG's own `LLM` layer.

RAGAS's collection metrics (0.4+) only need an object with `generate/agenerate(prompt, PydanticModel)`.
`RagasLLM` implements that over `app.generation.llm.LLM`, so every RAGAS call gets the same on-disk
cache, Groq rate limiting, strict JSON schema output and provider fallback as the rest of FinRAG,
and no OpenAI client or key is involved. Each call is counted, so a smoke run shows the cost per
question before a full run spends the free-tier quota.

Two metrics, chosen because they check the same things as the judge, by a different method:
- `Faithfulness` (2 calls): split the answer into statements, then NLI of each against the cited
  sources. Judge counterpart: per-claim faithfulness.
- `FactualCorrectness` (4 calls): decompose answer and reference into claims, check each side
  against the other. No sources in the prompt. Reported three ways from the same calls:
  - precision: share of the answer's claims the reference entails. Penalises correct extra detail
    and exact figures the reference rounds ("$26,914 million" vs "$26.91B" fails NLI; seen on T06).
  - coverage: share of the reference's claims the answer entails, i.e. true recall. This is the
    judge's correctness counterpart (the judge ignores extra detail and rounding).
  - f1: RAGAS's own score, unchanged. (RAGAS's "recall" mode is tp / (tp + fn) with tp from the
    precision direction, not coverage, so it is not used.)
"""

import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel
from ragas.llms.base import InstructorBaseRagasLLM
from ragas.metrics.collections import FactualCorrectness, Faithfulness
from ragas.metrics.utils import fbeta_score

from app.generation.context import Source
from app.generation.llm import LLM

T = TypeVar("T", bound=BaseModel)


@dataclass
class CallStats:
    calls: int = 0
    cached: int = 0
    tokens: int = 0  # uncached only: what the free-tier quota pays
    prompt_chars: int = 0
    models: set[str] = field(default_factory=set)


class RagasLLM(InstructorBaseRagasLLM):
    """RAGAS's LLM interface over FinRAG's cached, rate-limited `LLM`."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.stats = CallStats()

    def generate(self, prompt: str, response_model: type[T]) -> T:
        parsed, response = self.llm.generate([{"role": "user", "content": prompt}], response_model)
        s = self.stats
        s.calls += 1
        s.cached += response.cached
        s.tokens += 0 if response.cached else response.usage.total
        s.prompt_chars += len(prompt)
        s.models.add(response.model)
        return parsed

    async def agenerate(self, prompt: str, response_model: type[T]) -> T:
        return self.generate(prompt, response_model)  # sequential on purpose: one free-tier call at a time


def render_contexts(sources: Sequence[Source]) -> list[str]:
    return [f"{s.citation}\n{s.chunk.text}" for s in sources]  # same text the judge sees


@dataclass
class RagasScores:
    faithfulness: float | None = None
    factual_correctness: float | None = None  # RAGAS f1
    fc_precision: float | None = None
    fc_coverage: float | None = None


class RagasScorer:
    def __init__(self, llm: LLM, max_sources: int = 8):
        self.llm = RagasLLM(llm)
        self.max_sources = max_sources  # same bound as the judge
        self.faithfulness = Faithfulness(llm=self.llm)
        self.factual_correctness = FactualCorrectness(llm=self.llm, mode="f1")

    def score(self, question: str, answer: str, reference: str, cited_sources: Sequence[Source]) -> RagasScores:
        return asyncio.run(self.ascore(question, answer, reference, cited_sources))

    async def ascore(self, question: str, answer: str, reference: str,
                     cited_sources: Sequence[Source]) -> RagasScores:
        contexts = render_contexts(list(cited_sources)[: self.max_sources])
        scores = RagasScores()
        if contexts:  # RAGAS faithfulness needs contexts; an uncited answer has nothing to be faithful to
            res = await self.faithfulness.ascore(user_input=question, response=answer, retrieved_contexts=contexts)
            scores.faithfulness = _finite(res.value)
        # The metric's own two steps (same prompts and cache entries as `ascore`), kept apart so that
        # precision and coverage can be reported next to f1.
        fc = self.factual_correctness
        answer_claims = await fc._decompose_and_verify_claims(answer, reference)  # entailed by the reference?
        reference_claims = await fc._decompose_and_verify_claims(reference, answer)  # entailed by the answer?
        tp, fp, fn = int(answer_claims.sum()), int((~answer_claims).sum()), int((~reference_claims).sum())
        scores.factual_correctness = round(float(fbeta_score(tp, fp, fn, fc.beta)), 2)
        scores.fc_precision = tp / len(answer_claims) if len(answer_claims) else None
        scores.fc_coverage = float(reference_claims.mean()) if len(reference_claims) else None
        return scores


def _finite(value) -> float | None:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)
