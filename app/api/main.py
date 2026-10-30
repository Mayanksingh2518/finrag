"""HTTP API for the FinRAG web frontend.

Endpoints:
    GET  /api/health   liveness + corpus size
    GET  /api/meta     companies, fiscal years, sections and modes (drives the filter UI)
    POST /api/search   hybrid retrieval with filters; returns cited evidence cards
    POST /api/answer   grounded answer from the LangGraph agent (`app/agent/graph.py`): query analysis,
                       retrieval plan + XBRL facts, generation (trend/comparison routed to Groq),
                       citation verification; `thread_id` keeps a conversation for follow-ups
    POST /api/answer/stream  the same as Server-Sent Events: a `step` event as each agent node
                       finishes, then `answer` (the /api/answer body) or `error`

The retriever (embeddings, FAISS, BM25, reranker) loads once at startup. If the
frontend has been built (`frontend/dist`), it is served at `/` too, so one process
serves the whole app.

Usage:
    uvicorn app.api.main:app --port 8010            # API (+ built frontend); 8000 is often taken
    cd frontend && npm run dev                       # dev UI on :5173, proxies /api to :8010
"""

import collections
import json
import logging
import queue
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent.graph import AgentEvent, AgentTurn, FinRAGAgent
from app.api.schemas import (
    AnswerClaim,
    AnswerFilters,
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


class LockedRetriever:
    """The retriever with its model calls (embedding, reranking) serialized by a lock.

    Torch models aren't safe to call from several threads at once (MPS especially), but the agent
    graph mixes model calls with LLM calls that take seconds; locking only the retriever lets one
    request's LLM call overlap another's retrieval.
    """

    def __init__(self, retriever: Retriever, lock: threading.Lock):
        self._retriever, self._lock = retriever, lock

    def search(self, *args, **kwargs):
        with self._lock:
            return self._retriever.search(*args, **kwargs)

    def search_many(self, *args, **kwargs):
        with self._lock:
            return self._retriever.search_many(*args, **kwargs)

    def __getattr__(self, name: str):  # store, rerank_candidates, ...
        return getattr(self._retriever, name)


def _build_agent(retriever, llm: LLM | None, routed_llm: LLM | None, xbrl, production: bool) -> FinRAGAgent:
    settings = get_settings()
    sinks = []
    if production:  # tests build the agent from fakes and never read data, keys or trace settings
        from app.agent.xbrl import XbrlStore
        from app.tracing import build_sinks

        xbrl = XbrlStore.from_settings()
        if settings.answer_route and settings.groq_api_key:
            routed_llm = build_llm(settings.model_copy(update={"llm_providers": "groq,ollama"}))
        sinks = build_sinks(settings)
    return FinRAGAgent(retriever, llm or build_llm(), xbrl=xbrl, token_budget=settings.context_token_budget,
                       routed_llm=routed_llm, trace_sinks=sinks)


def answer_response(query: str, thread_id: str | None, turn: AgentTurn) -> AnswerResponse:
    r, a = turn.result, turn.analysis
    hits = {h.chunk.chunk_id: (i, h) for i, h in enumerate(turn.hits, start=1)}

    def source_hit(position: int, s) -> Hit:  # XBRL facts aren't retrieved hits: rank by position
        rank, hit = hits.get(s.chunk.chunk_id, (position, ScoredChunk(s.chunk, s.score, {"xbrl": 1.0})))
        return _to_hit(rank, hit)

    citation_of = {s.id: s.citation for s in r.sources}
    f = a.filters
    return AnswerResponse(
        query=query, standalone_query=a.standalone_query,
        filters=AnswerFilters(tickers=list(f.tickers or ()), fiscal_years=list(f.fiscal_years or ()),
                              sections=list(f.sections or ())),
        intent=turn.plan.intent if turn.plan else None, steps=turn.steps,
        facts=[fact.citation for fact in turn.facts], thread_id=thread_id,
        answer=r.answer, abstained=r.abstained, abstain_reason=r.abstain_reason, confidence=r.confidence,
        claims=[AnswerClaim(text=c.text, status=c.status, citations=[citation_of[i] for i in c.source_ids if i in citation_of],
                            unsupported_numbers=c.unsupported_numbers, repaired=c.repaired) for c in r.claims],
        sources=[AnswerSource(id=s.id, citation=s.citation, cited=s.id in r.cited_source_ids, hit=source_hit(n, s))
                 for n, s in enumerate(r.sources, start=1)],
        provider=r.provider, model=r.model, cached=r.cached, timings_ms=turn.timings_ms, usage=r.usage,
    )


def step_payload(agent: FinRAGAgent, event: AgentEvent) -> dict:
    """What a progress UI needs from one finished node (small: no chunk texts)."""
    u, out = event.update, {"node": event.node, "elapsed_ms": event.elapsed_ms}
    if event.node == "analyze" and (a := u.get("analysis")):
        f = a.filters
        out |= {"standalone_query": a.standalone_query, "in_scope": a.answerable_scope,
                "filters": {"tickers": list(f.tickers or ()), "fiscal_years": list(f.fiscal_years or ()),
                            "sections": list(f.sections or ())}}
    elif event.node == "retrieve":
        plan = u.get("plan")
        out |= {"hits": len(u.get("hits") or ()), "intent": plan.intent if plan else None,
                "answer_model": agent.answer_model(plan.intent if plan else None)}
    elif event.node == "xbrl":
        out["facts"] = [f.citation for f in u.get("facts") or ()]
    elif event.node == "generate":
        response = u.get("response")
        out |= {"model": response.model if response else None, "sources": len(u.get("sources") or ())}
    elif event.node == "verify" and (r := u.get("result")):
        out |= {"claims": len(r.claims), "verified": sum(c.supported for c in r.claims), "abstained": r.abstained}
    return out


def _sse(agent: FinRAGAgent, events: Iterator[AgentEvent | AgentTurn], query: str, thread_id: str | None) -> Iterator[str]:
    """Server-Sent Events from an agent turn.

    The turn runs in its own thread feeding a queue: Starlette iterates a sync generator on varying
    pool threads, and the turn's trace (a contextvar) must open and close in one thread. A client
    that disconnects only stops the reading; the turn finishes and is remembered/traced as usual.
    """
    q: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            for event in events:
                q.put(("answer", answer_response(query, thread_id, event).model_dump(mode="json"))
                      if isinstance(event, AgentTurn) else ("step", step_payload(agent, event)))
        except LLMError as e:
            q.put(("error", {"status": 502, "detail": f"LLM providers failed: {e}"}))
        except Exception as e:  # noqa: BLE001 - report, don't leave the client waiting
            logger.exception("Streaming answer failed")
            q.put(("error", {"status": 500, "detail": f"{type(e).__name__}: {e}"}))
        q.put(None)

    threading.Thread(target=work, name="answer-stream", daemon=True).start()
    while (item := q.get()) is not None:
        kind, data = item
        yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(retriever: Retriever | None = None, frontend_dir: Path | None = FRONTEND_DIST,
               llm: LLM | None = None, routed_llm: LLM | None = None, xbrl=None) -> FastAPI:
    """App factory; tests pass a small in-memory retriever (and fake LLMs), production builds the real ones."""

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
        # Torch models aren't safe to call from several threads at once (MPS especially).
        app.state.search_lock = threading.Lock()
        app.state.agent = None
        app.state.answer_error = ""
        try:
            app.state.agent = _build_agent(LockedRetriever(app.state.retriever, app.state.search_lock), llm,
                                           routed_llm, xbrl, production=retriever is None)
        except LLMError as e:  # no LLM provider: search still works, answers are disabled
            app.state.answer_error = str(e)
            logger.warning("Answers disabled: %s", e)
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
        agent: FinRAGAgent | None = request.app.state.agent
        if agent is None:
            raise HTTPException(status_code=503, detail=f"Answers are disabled: {request.app.state.answer_error}")
        _check_tickers(request, req.tickers)
        query = req.query.strip()
        user_filters = _filters(req.tickers, req.fiscal_years, req.sections)
        try:
            turn = (agent.ask(query, req.thread_id, user_filters) if req.thread_id
                    else agent.run(query, filters=user_filters))
        except LLMError as e:
            raise HTTPException(status_code=502, detail=f"LLM providers failed: {e}") from None
        return answer_response(query, req.thread_id, turn)

    @app.post("/api/answer/stream")
    def answer_stream(req: AnswerRequest, request: Request) -> StreamingResponse:
        agent: FinRAGAgent | None = request.app.state.agent
        if agent is None:  # checked before streaming starts, so these stay plain HTTP errors
            raise HTTPException(status_code=503, detail=f"Answers are disabled: {request.app.state.answer_error}")
        _check_tickers(request, req.tickers)
        query = req.query.strip()
        user_filters = _filters(req.tickers, req.fiscal_years, req.sections)
        events = (agent.stream_ask(query, req.thread_id, user_filters) if req.thread_id
                  else agent.stream(query, filters=user_filters))
        return StreamingResponse(_sse(agent, events, query, req.thread_id), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if frontend_dir is not None and (frontend_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app


app = create_app()
