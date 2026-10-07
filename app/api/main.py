"""HTTP API for the FinRAG web frontend.

Endpoints:
    GET  /api/health   liveness + corpus size
    GET  /api/meta     companies, fiscal years, sections and modes (drives the filter UI)
    POST /api/search   hybrid retrieval with filters; returns cited evidence cards
    POST /api/answer   grounded answer: retrieval + LLM + citation verification (needs an API key)

The retriever (embeddings, FAISS, BM25, reranker) loads once at startup. If the
frontend has been built (`frontend/dist`), it is served at `/` too, so one process
serves the whole app.

Usage:
    uvicorn app.api.main:app --port 8010            # API (+ built frontend); 8000 is often taken
    cd frontend && npm run dev                       # dev UI on :5173, proxies /api to :8010
"""

import collections
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from app.api.schemas import (
    AnswerClaim,
    AnswerRequest,
    AnswerResponse,
    AnswerSource,
    CompanyInfo,
    HealthResponse,
    Hit,
    MetaResponse,
    SearchRequest,
    SearchResponse,
    SectionInfo,
)
from app.config import PROJECT_ROOT, get_settings
from app.generation.answer import Answerer
from app.generation.llm import LLM, LLMError, build_llm
from app.ingestion.companies import COMPANIES
from app.retrieval.decompose import search_decomposed
from app.retrieval.retriever import Retriever
from app.retrieval.types import SEARCH_MODES, ScoredChunk, SearchFilters

logger = logging.getLogger(__name__)
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def _page_label(start: str | None, end: str | None) -> str | None:
    if not start:
        return None
    return start if not end or end == start else f"{start}-{end}"


def _to_hit(rank: int, hit: ScoredChunk) -> Hit:
    c = hit.chunk
    return Hit(
        rank=rank, chunk_id=c.chunk_id, ticker=c.ticker, company=c.company, fiscal_year=c.fiscal_year,
        section=c.section, section_title=c.section_title, subsection=c.subsection,
        page_start=c.page_start, page_end=c.page_end, page_label=_page_label(c.page_label_start, c.page_label_end),
        chunk_type=c.chunk_type, text=c.text, source_url=c.source_url, score=hit.score,
        stages={k: float(v) for k, v in hit.stages.items()},
    )


def build_meta(retriever: Retriever) -> MetaResponse:
    chunks = retriever.store.chunks
    years_by_ticker: dict[str, set[int]] = collections.defaultdict(set)
    titles: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for c in chunks:
        years_by_ticker[c.ticker].add(c.fiscal_year)
        titles[c.section][c.section_title] += 1

    def section_key(section: str) -> tuple:
        # "Item 1A" -> (1, "A"); non-items (Cover) first
        if not section.startswith("Item "):
            return (-1, section)
        num = section.removeprefix("Item ")
        digits = "".join(ch for ch in num if ch.isdigit())
        return (int(digits or 0), num[len(digits):])

    companies = [
        CompanyInfo(ticker=t, name=co.name, sector=co.sector, fiscal_year_end=co.fiscal_year_end,
                    fiscal_years=sorted(years_by_ticker[t]))
        for t, co in COMPANIES.items() if t in years_by_ticker
    ]
    sections = [
        SectionInfo(section=s, title=titles[s].most_common(1)[0][0], chunks=sum(titles[s].values()))
        for s in sorted(titles, key=section_key)
    ]
    return MetaResponse(
        companies=companies,
        fiscal_years=sorted({y for ys in years_by_ticker.values() for y in ys}),
        sections=sections, modes=list(SEARCH_MODES), chunks=len(chunks),
    )


def _filters(tickers: list[str], years: list[int], sections: list[str], chunk_types: list[str] | None = None) -> SearchFilters:
    return SearchFilters(tickers=tuple(tickers) or None, fiscal_years=tuple(years) or None,
                         sections=tuple(sections) or None, chunk_types=tuple(chunk_types or ()) or None)


def _check_tickers(request: Request, tickers: list[str]) -> None:
    unknown = sorted(set(tickers) - {c.ticker for c in request.app.state.meta.companies})
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown tickers: {', '.join(unknown)}")


def create_app(retriever: Retriever | None = None, frontend_dir: Path | None = FRONTEND_DIST,
               llm: LLM | None = None) -> FastAPI:
    """App factory; tests pass a small in-memory retriever (and fake LLM), production builds the real ones."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if retriever is None:
            from app.retrieval.factory import build_retriever

            logger.info("Loading retriever (embeddings, indexes, reranker)...")
            app.state.retriever = build_retriever()
            app.state.retriever.search("warm up", k=1)  # first mps call is slow; pay it at startup
        else:
            app.state.retriever = retriever
        app.state.meta = build_meta(app.state.retriever)
        app.state.answerer = None
        app.state.answer_error = ""
        try:
            app.state.answerer = Answerer(app.state.retriever, llm or build_llm(),
                                          token_budget=get_settings().context_token_budget)
        except LLMError as e:  # no API keys: search still works, answers are disabled
            app.state.answer_error = str(e)
            logger.warning("Answers disabled: %s", e)
        # Torch models aren't safe to call from several threads at once (MPS especially).
        app.state.search_lock = threading.Lock()
        yield

    app = FastAPI(title="FinRAG API", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        return HealthResponse(status="ok", chunks=len(request.app.state.retriever.store))

    @app.get("/api/meta", response_model=MetaResponse)
    def meta(request: Request) -> MetaResponse:
        return request.app.state.meta

    @app.post("/api/search", response_model=SearchResponse)
    def search(req: SearchRequest, request: Request) -> SearchResponse:
        _check_tickers(request, req.tickers)
        filters = _filters(req.tickers, req.fiscal_years, req.sections, list(req.chunk_types))
        query = req.query.strip()
        with request.app.state.search_lock:
            if req.decompose:
                result = search_decomposed(request.app.state.retriever, query, filters, k=req.k, mode=req.mode)
            else:
                result = request.app.state.retriever.search(query, filters, k=req.k, mode=req.mode)
        return SearchResponse(
            query=query, mode=req.mode, decomposed=req.decompose,
            hits=[_to_hit(i, h) for i, h in enumerate(result.hits, start=1)],
            timings_ms=result.timings_ms,
        )

    @app.post("/api/answer", response_model=AnswerResponse)
    def answer(req: AnswerRequest, request: Request) -> AnswerResponse:
        answerer: Answerer | None = request.app.state.answerer
        if answerer is None:
            raise HTTPException(status_code=503, detail=f"Answers are disabled: {request.app.state.answer_error}")
        _check_tickers(request, req.tickers)
        query = req.query.strip()
        start = time.perf_counter()
        with request.app.state.search_lock:  # models only; the LLM call below runs unlocked
            retrieved = answerer.retrieve(query, _filters(req.tickers, req.fiscal_years, req.sections), req.decompose)
        retrieval_ms = round((time.perf_counter() - start) * 1000, 1)
        try:
            r = answerer.answer_from_hits(query, retrieved.hits, retrieval_ms=retrieval_ms)
        except LLMError as e:
            raise HTTPException(status_code=502, detail=f"LLM providers failed: {e}") from None
        hits = {h.chunk.chunk_id: (i, h) for i, h in enumerate(retrieved.hits, start=1)}
        citation_of = {s.id: s.citation for s in r.sources}
        return AnswerResponse(
            query=query, answer=r.answer, abstained=r.abstained, abstain_reason=r.abstain_reason,
            confidence=r.confidence,
            claims=[AnswerClaim(text=c.text, status=c.status, citations=[citation_of[i] for i in c.source_ids if i in citation_of],
                                unsupported_numbers=c.unsupported_numbers) for c in r.claims],
            sources=[AnswerSource(id=s.id, citation=s.citation, cited=s.id in r.cited_source_ids,
                                  hit=_to_hit(*hits[s.chunk.chunk_id])) for s in r.sources],
            provider=r.provider, model=r.model, cached=r.cached,
            timings_ms={**r.timings_ms, "total": round((time.perf_counter() - start) * 1000, 1)}, usage=r.usage,
        )

    if frontend_dir is not None and (frontend_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app


app = create_app()
