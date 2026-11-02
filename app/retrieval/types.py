"""Shared retrieval types."""

from dataclasses import dataclass, field
from typing import Literal

from app.ingestion.models import Chunk

SearchMode = Literal["bm25", "dense", "hybrid", "hybrid_rerank"]
SEARCH_MODES: tuple[SearchMode, ...] = ("bm25", "dense", "hybrid", "hybrid_rerank")

FORM_10K = "10-K"
FORM_RELEASE = "8-K EX-99.1"  # quarterly earnings release


@dataclass(frozen=True)
class SearchFilters:
    """Metadata constraints applied identically to every retriever (None = no constraint)."""

    tickers: tuple[str, ...] | None = None
    fiscal_years: tuple[int, ...] | None = None
    sections: tuple[str, ...] | None = None  # e.g. ("Item 1A",)
    chunk_types: tuple[str, ...] | None = None  # "text" / "table"
    fiscal_quarters: tuple[int, ...] | None = None  # 1-4; only earnings releases have quarters
    forms: tuple[str, ...] | None = None  # None: see `effective_forms`

    def is_empty(self) -> bool:
        return not (self.tickers or self.fiscal_years or self.sections or self.chunk_types
                    or self.fiscal_quarters or self.forms)

    def effective_forms(self) -> tuple[str, ...]:
        """The 10-K is the default corpus: releases are searched only when a filter asks for them."""
        return self.forms or ((FORM_RELEASE,) if self.fiscal_quarters else (FORM_10K,))


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float
    # Per-stage scores/ranks ("bm25_rank", "dense_score", "rrf", "rerank", ...) for debugging and evals.
    stages: dict[str, float] = field(default_factory=dict)


@dataclass
class SearchResult:
    query: str
    mode: SearchMode
    filters: SearchFilters
    hits: list[ScoredChunk]
    timings_ms: dict[str, float] = field(default_factory=dict)
