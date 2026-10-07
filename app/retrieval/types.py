"""Shared retrieval types."""

from dataclasses import dataclass, field
from typing import Literal

from app.ingestion.models import Chunk

SearchMode = Literal["bm25", "dense", "hybrid", "hybrid_rerank"]
SEARCH_MODES: tuple[SearchMode, ...] = ("bm25", "dense", "hybrid", "hybrid_rerank")


@dataclass(frozen=True)
class SearchFilters:
    """Metadata constraints applied identically to every retriever (None = no constraint)."""

    tickers: tuple[str, ...] | None = None
    fiscal_years: tuple[int, ...] | None = None
    sections: tuple[str, ...] | None = None  # e.g. ("Item 1A",)
    chunk_types: tuple[str, ...] | None = None  # "text" / "table"

    def is_empty(self) -> bool:
        return not (self.tickers or self.fiscal_years or self.sections or self.chunk_types)


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
