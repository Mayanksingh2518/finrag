"""Request/response models for the HTTP API (the frontend's contract)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.retrieval.types import SearchMode


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    tickers: list[str] = Field(default_factory=list)
    fiscal_years: list[int] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    chunk_types: list[Literal["text", "table"]] = Field(default_factory=list)
    mode: SearchMode = "hybrid_rerank"
    k: int = Field(default=8, ge=1, le=30)
    # One sub-search per (company, year), merged round-robin (helps comparisons and trends).
    decompose: bool = False


class Hit(BaseModel):
    rank: int
    chunk_id: str
    ticker: str
    company: str
    fiscal_year: int
    section: str
    section_title: str
    subsection: str | None
    page_start: int
    page_end: int
    page_label: str | None  # printed page number(s), e.g. "23" or "23-24"
    chunk_type: Literal["text", "table"]
    text: str
    source_url: str
    score: float
    stages: dict[str, float]  # per-stage ranks/scores (bm25_rank, dense_score, rrf, rerank, ...)


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    decomposed: bool
    hits: list[Hit]
    timings_ms: dict[str, float]


class CompanyInfo(BaseModel):
    ticker: str
    name: str
    sector: str
    fiscal_year_end: str
    fiscal_years: list[int]


class SectionInfo(BaseModel):
    section: str
    title: str
    chunks: int


class MetaResponse(BaseModel):
    companies: list[CompanyInfo]
    fiscal_years: list[int]
    sections: list[SectionInfo]
    modes: list[str]
    chunks: int


class HealthResponse(BaseModel):
    status: Literal["ok"]
    chunks: int


class AnswerRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    tickers: list[str] = Field(default_factory=list)
    fiscal_years: list[int] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    # None = decompose automatically when several companies/years are selected.
    decompose: bool | None = None


class AnswerClaim(BaseModel):
    text: str
    status: Literal["supported", "unsupported_number", "invalid_citation"]
    citations: list[str]  # human citations of the cited sources, e.g. "[AAPL FY2025 p.23]"
    unsupported_numbers: list[str]


class AnswerSource(BaseModel):
    id: str  # "S1"
    citation: str
    cited: bool  # used by a verified claim
    hit: Hit


class AnswerResponse(BaseModel):
    query: str
    answer: str
    abstained: bool
    abstain_reason: str
    confidence: Literal["high", "medium", "low", "none"]
    claims: list[AnswerClaim]
    sources: list[AnswerSource]
    provider: str
    model: str
    cached: bool
    timings_ms: dict[str, float]
    usage: dict[str, int]
