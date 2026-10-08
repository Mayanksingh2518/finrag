"""Grounded answering: retrieve, prompt with numbered sources, verify, render citations.

The model must answer only from the sources and cite them; `verify.py` then
checks each claim. Confidence comes from that check and retrieval scores, not
from the model's opinion of itself. If no claim survives, the answer abstains.
"""

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.generation.context import Source, build_sources, render_sources
from app.generation.llm import LLM, Message
from app.generation.schemas import Claim, GeneratedAnswer
from app.generation.verify import VerifiedClaim, verify_claims
from app.retrieval.decompose import search_decomposed, split_filters
from app.retrieval.retriever import Retriever
from app.retrieval.types import ScoredChunk, SearchFilters, SearchMode

SYSTEM_PROMPT = """You are FinRAG, an analyst answering questions about SEC Form 10-K filings.

Rules:
1. Use ONLY the numbered sources provided. Never use outside knowledge, even if you are sure.
2. Every factual statement must cite the source ids that state it, inline in the answer text itself,
   right after the statement: "<statement> [S1]." or "<statement> [S2][S3]." Put each id in its own
   square brackets, never "(S1)" or "[S1, S2]". An answer without inline [S#] markers is invalid.
3. Copy figures exactly as the sources state them (you may convert units, e.g. 109,158 million = $109.2 billion).
   Do not compute new figures unless the question asks for a comparison; then show the inputs with citations.
4. Fiscal years are each company's own (e.g. NVIDIA fiscal 2025 ended January 2025). Say so when it matters.
5. If the sources do not contain the information needed, set abstained=true, explain what is missing in
   abstain_reason, and leave answer empty and claims empty. A partial answer is fine when part of the
   question is covered: answer that part and say what is missing.
6. Be concise: 1-4 sentences, or a short list for multi-company or multi-year questions.
7. List every factual statement of the answer in claims, each with its source ids."""

Confidence = Literal["high", "medium", "low", "none"]


@dataclass
class AnswerResult:
    question: str
    answer: str  # with [S1] replaced by human citations like [AAPL FY2025 p.23]
    abstained: bool
    abstain_reason: str
    confidence: Confidence
    claims: list[VerifiedClaim]
    sources: list[Source]
    cited_source_ids: list[str]
    timings_ms: dict[str, float] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    cached: bool = False


def build_messages(question: str, sources: Sequence[Source]) -> list[Message]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Sources:\n\n{render_sources(sources)}\n\nQuestion: {question}"},
    ]


def render_citations(text: str, sources: Sequence[Source]) -> str:
    """[S1] -> [AAPL FY2025 p.23]; unknown ids are left visible so they can be spotted."""
    by_id = {s.id: s.citation for s in sources}
    return re.sub(r"\[(S\d+)\]", lambda m: by_id.get(m.group(1), m.group(0)), text)


_MARKER = re.compile(r"\[(S\d+)\]")
_ID_PREFIX = r"(?:S|Source\s*)"
_ID = rf"{_ID_PREFIX}\d+"
# "[S1, S2]", "(S1)", "(Source 3; S4)": groups the model wrote in some other style than "[S1][S2]".
_MARKER_GROUP = re.compile(rf"[\[(]\s*{_ID}(?:\s*(?:,|;|and|&)\s*{_ID})*\s*[\])]", re.IGNORECASE)
# Sentence ends: punctuation + space before a marker, letter, digit or $, except after common abbreviations.
_SENTENCE_BREAK = re.compile(r"(?<!\bU\.S\.)(?<!\bInc\.)(?<!\bCo\.)(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\bvs\.)"
                             r"(?<=[.!?])\s+(?=\[|[A-Za-z0-9$])")


def normalize_markers(text: str) -> str:
    """Rewrite citation groups like "[S1, S2]" or "(S1)" as "[S1][S2]", the form the rest of the code reads."""
    return _MARKER_GROUP.sub(
        lambda m: "".join(f"[S{n}]" for n in re.findall(rf"{_ID_PREFIX}(\d+)", m.group(0), re.IGNORECASE)), text)


def claims_from_text(answer: str) -> list[Claim]:
    """Fallback when a model cites inline but leaves `claims` empty (common with small local models).

    Each sentence becomes a claim. Models disagree on marker placement ("X [S1]." vs "X. [S1]"
    vs "[S1] X."), so a sentence may use the markers inside it plus those directly after it,
    before the next sentence's text starts. A sentence without markers takes those of the next
    cited sentence on the same line ("A. B. [S1][S2]" cites both). The verifier still requires
    every figure to appear in one of those cited pages.
    """
    claims = []
    for line in normalize_markers(answer).strip().splitlines():
        parts = [p for p in _SENTENCE_BREAK.split(line.strip()) if p.strip()]
        line_claims: list[Claim] = []
        for i, part in enumerate(parts):
            ids = _MARKER.findall(part)
            if i + 1 < len(parts):  # markers leading the next part may belong to this sentence
                lead = re.match(r"^(\s*\[S\d+\])+", parts[i + 1])
                ids += _MARKER.findall(lead.group(0)) if lead else []
            text = _MARKER.sub("", part).strip()
            if text and any(ch.isalnum() for ch in text):
                line_claims.append(Claim(text=text, source_ids=list(dict.fromkeys(ids))))
        pending: list[str] = []
        for claim in reversed(line_claims):  # right to left: carry the closing citation block backwards
            if claim.source_ids:
                pending = claim.source_ids
            else:
                claim.source_ids = list(pending)
        claims += line_claims
    return claims


def confidence_of(claims: Sequence[VerifiedClaim], sources: Sequence[Source], abstained: bool) -> Confidence:
    if abstained or not claims:
        return "none"
    supported = sum(c.supported for c in claims) / len(claims)
    cited = {sid for c in claims if c.supported for sid in c.source_ids}
    best = max((s.score for s in sources if s.id in cited), default=0.0)
    repaired = any(c.repaired for c in claims if c.supported)  # the model mis-cited: don't call it high
    if supported == 1.0 and best >= 0.5 and not repaired:
        return "high"
    if supported >= 0.5:
        return "medium"
    return "low"


class Answerer:
    def __init__(self, retriever: Retriever, llm: LLM, token_budget: int = 3500, k: int = 10,
                 mode: SearchMode = "hybrid_rerank"):
        self.retriever = retriever
        self.llm = llm
        self.token_budget = token_budget
        self.k = k
        self.mode = mode

    def retrieve(self, question: str, filters: SearchFilters, decompose: bool | None = None):
        # Decompose automatically when the filters name several companies or years (Phase 4 finding).
        if decompose is None:
            decompose = len(split_filters(filters)) > 1
        if decompose:
            return search_decomposed(self.retriever, question, filters, k=self.k, mode=self.mode)
        return self.retriever.search(question, filters, k=self.k, mode=self.mode)

    def answer(self, question: str, filters: SearchFilters | None = None, decompose: bool | None = None) -> AnswerResult:
        start = time.perf_counter()
        result = self.retrieve(question, filters or SearchFilters(), decompose)
        return self.answer_from_hits(question, result.hits, retrieval_ms=round((time.perf_counter() - start) * 1000, 1))

    def answer_from_hits(self, question: str, hits: Sequence[ScoredChunk], retrieval_ms: float = 0.0) -> AnswerResult:
        """Generation half of `answer`; callers that lock the retrieval models can run this unlocked."""
        sources = build_sources(hits, self.token_budget)
        timings = {"retrieval": retrieval_ms}
        if not sources:
            return AnswerResult(question, "", True, "No passages matched the question and filters.", "none", [], [], [],
                                timings)

        start = time.perf_counter()
        generated, response = self.llm.generate(build_messages(question, sources), GeneratedAnswer)
        timings["generation"] = round((time.perf_counter() - start) * 1000, 1)  # incl. rate-limit waits
        timings["llm"] = 0.0 if response.cached else response.latency_ms  # the provider call itself

        text = normalize_markers(generated.answer.strip())
        model_claims = generated.claims or ([] if generated.abstained else claims_from_text(text))
        claims = verify_claims(model_claims, sources)
        # An answer is only shown if at least one claim checks out against its cited page;
        # an answer with no claims at all can't be verified, so it is treated as an abstention.
        abstained = generated.abstained or not any(c.supported for c in claims)
        reason = generated.abstain_reason if generated.abstained else ""
        if abstained and not generated.abstained:
            reason = ("None of the answer's claims could be verified against the cited sources." if claims
                      else "The model gave no verifiable, cited claims for its answer.")
        cited = list(dict.fromkeys(sid for c in claims if c.supported for sid in c.source_ids))
        # Citations the model didn't write inline (missing, or repaired by the verifier) go at the end.
        extra = [sid for sid in cited if f"[{sid}]" not in text]
        if extra:
            text = f"{text} {''.join(f'[{sid}]' for sid in extra)}"
        return AnswerResult(
            question=question,
            answer="" if abstained else render_citations(text, sources),
            abstained=abstained,
            abstain_reason=reason,
            confidence=confidence_of(claims, sources, abstained),
            claims=claims,
            sources=sources,
            cited_source_ids=cited,
            timings_ms=timings,
            usage={"prompt": response.usage.prompt_tokens, "completion": response.usage.completion_tokens,
                   "reasoning": response.usage.reasoning_tokens},
            provider=response.provider,
            model=response.model,
            cached=response.cached,
        )
