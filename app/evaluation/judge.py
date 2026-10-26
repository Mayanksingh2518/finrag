"""LLM judge: is an answer *right*, and does each claim mean what its cited sources say?

The citation verifier (`verify.py`) checks figures, not meaning: "NVIDIA's revenue grew at a CAGR
of 114.2%" passes because 114.2% is in the source (it's FY2025's one-year growth), and "Apple had
more employees (166,000) than Microsoft (228,000)" passes because both figures are cited. The
judge reads the question, the reference answer, the candidate answer and the cited sources, and
returns:
- correctness vs the reference: correct / partially_correct / incorrect, with the reference
  facts that are missing or contradicted
- per-claim faithfulness: supported / partially_supported / unsupported by its cited sources,
  in meaning (company, period, metric, direction), not just figures

Zero cost: one call per answered question on a free tier (Groq gpt-oss-120b, Gemini fallback),
never the local model that wrote the answers; every call is cached by the `LLM` layer. Only the
cited sources are sent, which keeps a call at ~2k tokens (Groq's free tier: 200k tokens/day).
Abstentions need no call: they are scored by rule in the eval runner.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.generation.context import Source
from app.generation.llm import LLM, LLMResponse, Message

Correctness = Literal["correct", "partially_correct", "incorrect"]
Support = Literal["supported", "partially_supported", "unsupported"]

CORRECTNESS_SCORE: dict[str, float] = {"correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0}
SUPPORT_SCORE: dict[str, float] = {"supported": 1.0, "partially_supported": 0.5, "unsupported": 0.0}

JUDGE_PROMPT = """You grade answers to questions about SEC Form 10-K filings. You get the question, a reference
answer written by an expert, a candidate answer, and the sources the candidate cited.

Correctness (candidate vs reference):
- "correct": answers what the question asks with the reference's key facts. Rounding and unit changes
  are fine ($130.5 billion = $130,497 million). Extra details are fine if they are not wrong. Secondary
  reference details the question did not ask for (e.g. a growth rate when only the amount was asked)
  may be missing.
- "partially_correct": right on part of what was asked (e.g. two of four years, or one of two companies)
  and wrong on nothing important.
- "incorrect": misses the main asked fact, or states something that contradicts the reference: a wrong
  figure, a figure for the wrong year/company/metric, a wrong direction ("increased" when it fell), a wrong
  comparison ("A had more" when B had more), or a mislabeled figure (a one-year growth rate called a CAGR).
List the reference facts the candidate misses (missing_facts) and those it contradicts (contradicted_facts).

Faithfulness (candidate vs its cited sources): split the candidate answer into its factual claims. For each,
decide whether the cited sources state it with the same meaning: same company, period, metric and direction.
"supported": stated; "partially_supported": part of it is stated, or it needs an inference the sources only
partly back; "unsupported": not stated, or the sources say something different. A conclusion drawn from
supported figures (e.g. "Mastercard grew faster") is supported only if it follows from them.

Judge only from the text given. Do not use outside knowledge about the companies."""


class ClaimVerdict(BaseModel):
    claim: str = Field(description="One factual claim from the candidate answer.")
    verdict: Support
    reason: str = Field(description="Short reason, naming what the sources say if they differ.")


class Judgment(BaseModel):
    correctness: Correctness
    missing_facts: list[str] = Field(description="Reference facts the candidate answer leaves out.")
    contradicted_facts: list[str] = Field(description="Reference facts the candidate answer gets wrong.")
    claims: list[ClaimVerdict] = Field(description="Every factual claim of the candidate answer.")
    reason: str = Field(description="One or two sentences explaining the correctness grade.")


@dataclass
class JudgeResult:
    judgment: Judgment
    response: LLMResponse

    @property
    def correctness(self) -> float:
        return CORRECTNESS_SCORE[self.judgment.correctness]

    @property
    def faithfulness(self) -> float | None:
        claims = self.judgment.claims
        return sum(SUPPORT_SCORE[c.verdict] for c in claims) / len(claims) if claims else None


def render_sources(sources: Sequence[Source]) -> str:
    return "\n\n".join(f"{s.citation}\n{s.chunk.text}" for s in sources)


def build_judge_messages(question: str, reference: str, answer: str, sources: Sequence[Source]) -> list[Message]:
    user = (f"Question: {question}\n\nReference answer: {reference}\n\nCandidate answer: {answer}\n\n"
            f"Sources cited by the candidate:\n\n{render_sources(sources) or '(none)'}")
    return [{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": user}]


class Judge:
    def __init__(self, llm: LLM, max_sources: int = 8):
        self.llm = llm
        self.max_sources = max_sources  # bounds a call's tokens on long trend answers

    def judge(self, question: str, reference: str, answer: str, cited_sources: Sequence[Source]) -> JudgeResult:
        messages = build_judge_messages(question, reference, answer, list(cited_sources)[: self.max_sources])
        judgment, response = self.llm.generate(messages, Judgment)
        return JudgeResult(judgment, response)
