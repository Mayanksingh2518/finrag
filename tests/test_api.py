import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.retrieval.bm25 import BM25Index
from app.retrieval.dense import DenseIndex
from app.retrieval.retriever import Retriever
from app.retrieval.store import ChunkStore
from tests.test_retrieval import CHUNKS, FakeEmbedder, ReverseReranker


@pytest.fixture
def client(tmp_path):
    embedder = FakeEmbedder()
    retriever = Retriever(
        ChunkStore(CHUNKS), BM25Index([c.embed_text for c in CHUNKS]),
        DenseIndex(embedder.embed_documents([c.embed_text for c in CHUNKS])), embedder, ReverseReranker(),
        candidates_per_retriever=5,
    )
    with TestClient(create_app(retriever, frontend_dir=tmp_path)) as c:
        yield c


def test_health_and_meta(client):
    assert client.get("/api/health").json() == {"status": "ok", "chunks": len(CHUNKS)}
    meta = client.get("/api/meta").json()
    assert [c["ticker"] for c in meta["companies"]] == ["AAPL", "MSFT", "NVDA", "AMZN", "V"]  # registry order
    assert meta["companies"][0]["name"] == "Apple Inc." and meta["companies"][0]["fiscal_years"] == [2022, 2025]
    assert [s["section"] for s in meta["sections"]] == ["Item 1A", "Item 7", "Item 8"]
    assert meta["fiscal_years"] == [2022, 2025] and "hybrid_rerank" in meta["modes"]


def test_search_returns_cited_hits_and_respects_filters(client):
    body = client.post("/api/search", json={"query": "cloud revenue", "tickers": ["MSFT", "AMZN"], "mode": "hybrid", "k": 5}).json()
    assert body["hits"] and {h["ticker"] for h in body["hits"]} <= {"MSFT", "AMZN"}
    hit = body["hits"][0]
    assert hit["rank"] == 1 and hit["page_label"] == "1" and "rrf" in hit["stages"]
    assert body["timings_ms"]["total"] >= 0 and body["decomposed"] is False


def test_decomposed_search_covers_each_company(client):
    body = client.post("/api/search", json={"query": "revenue increased", "tickers": ["AAPL", "V"], "decompose": True,
                                            "mode": "hybrid", "k": 2}).json()
    assert body["decomposed"] and {h["ticker"] for h in body["hits"]} == {"AAPL", "V"}


@pytest.mark.parametrize("payload", [{"query": ""}, {"query": "x", "k": 0}, {"query": "x", "mode": "magic"},
                                     {"query": "x", "tickers": ["NFLX"]}])
def test_search_rejects_bad_requests(client, payload):
    assert client.post("/api/search", json=payload).status_code == 422


def test_built_frontend_is_served_when_present(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>FinRAG</title>")
    embedder = FakeEmbedder()
    retriever = Retriever(ChunkStore(CHUNKS), BM25Index([c.embed_text for c in CHUNKS]),
                          DenseIndex(embedder.embed_documents([c.embed_text for c in CHUNKS])), embedder)
    with TestClient(create_app(retriever, frontend_dir=tmp_path)) as c:
        assert "FinRAG" in c.get("/").text and c.get("/api/health").status_code == 200


def _app_with_llm(llm, tmp_path):
    embedder = FakeEmbedder()
    retriever = Retriever(ChunkStore(CHUNKS), BM25Index([c.embed_text for c in CHUNKS]),
                          DenseIndex(embedder.embed_documents([c.embed_text for c in CHUNKS])), embedder, ReverseReranker(),
                          candidates_per_retriever=5)
    return create_app(retriever, frontend_dir=tmp_path, llm=llm)


def test_answer_returns_verified_claims_and_cited_sources(tmp_path):
    from app.generation.schemas import Claim, GeneratedAnswer
    from tests.test_generation import ScriptedLLM

    llm = ScriptedLLM(GeneratedAnswer(answer="Services revenue increased due to advertising [S1].",
                                      claims=[Claim(text="Services revenue increased.", source_ids=["S1"]),
                                              Claim(text="It rose $5 billion.", source_ids=["S1"])],
                                      abstained=False, abstain_reason=""))
    with TestClient(_app_with_llm(llm, tmp_path)) as c:
        body = c.post("/api/answer", json={"query": "Why did services revenue increase?", "tickers": ["AAPL"],
                                           "fiscal_years": [2025]}).json()
    assert body["answer"].endswith("[AAPL FY2025 p.1].") and not body["abstained"]
    assert [cl["status"] for cl in body["claims"]] == ["supported", "unsupported_number"]
    assert body["claims"][1]["unsupported_numbers"] == ["$5 billion"]
    assert body["sources"][0]["cited"] and body["sources"][0]["hit"]["ticker"] == "AAPL"
    assert body["confidence"] == "medium" and {"retrieval", "generation", "total"} <= set(body["timings_ms"])


def test_answer_disabled_without_keys_and_502_on_provider_failure(tmp_path, monkeypatch):
    import app.api.main as main
    from app.generation.llm import LLMError

    def no_keys():
        raise LLMError("No LLM providers configured")

    monkeypatch.setattr(main, "build_llm", no_keys)
    with TestClient(_app_with_llm(None, tmp_path)) as c:
        res = c.post("/api/answer", json={"query": "revenue"})
        assert res.status_code == 503 and "No LLM providers" in res.json()["detail"]
        assert c.post("/api/search", json={"query": "revenue", "mode": "hybrid"}).status_code == 200  # search unaffected

    class FailingLLM:
        def generate(self, messages, output):
            raise LLMError("groq: 429; gemini: 503")

    with TestClient(_app_with_llm(FailingLLM(), tmp_path)) as c:
        res = c.post("/api/answer", json={"query": "revenue", "tickers": ["AAPL"]})
        assert res.status_code == 502 and "groq: 429" in res.json()["detail"]


# --- the agent behind /api/answer ----------------------------------------------------------------


def _agent_client(tmp_path, llm, xbrl=None):
    embedder = FakeEmbedder()
    retriever = Retriever(ChunkStore(CHUNKS), BM25Index([c.embed_text for c in CHUNKS]),
                          DenseIndex(embedder.embed_documents([c.embed_text for c in CHUNKS])), embedder, ReverseReranker(),
                          candidates_per_retriever=5)
    return TestClient(create_app(retriever, frontend_dir=tmp_path, llm=llm, xbrl=xbrl))


def test_answer_runs_the_agent_and_keeps_a_conversation_per_thread(tmp_path):
    from tests.test_graph import ScriptedLLM, answer

    llm = ScriptedLLM(answers=[answer("Services revenue increased due to advertising", "S1"),
                               answer("Services net sales grew driven by cloud services", "S1")],
                      rewrites=[{"standalone_question": "Why did Apple's services revenue change in fiscal 2022?"}])
    with _agent_client(tmp_path, llm) as c:
        first = c.post("/api/answer", json={"query": "Why did Apple's services revenue increase in fiscal 2025?",
                                            "thread_id": "t-1"}).json()
        assert not first["abstained"] and first["filters"] == {"tickers": ["AAPL"], "fiscal_years": [2025], "sections": []}
        assert first["steps"][0] == "analyze" and first["steps"][-1] == "respond" and first["thread_id"] == "t-1"
        assert first["standalone_query"] == first["query"] and first["intent"] and first["facts"] == []
        assert first["sources"][0]["hit"]["ticker"] == "AAPL" and {"analyze", "retrieval", "total"} <= set(first["timings_ms"])

        follow = c.post("/api/answer", json={"query": "And in fiscal 2022?", "thread_id": "t-1"}).json()
    assert follow["standalone_query"] == "Why did Apple's services revenue change in fiscal 2022?"
    assert follow["filters"]["tickers"] == ["AAPL"] and follow["filters"]["fiscal_years"] == [2022]
    assert "advertising" in llm.prompts[1][-1]["content"]  # the rewrite call saw the first turn
    assert "fiscal 2022" in llm.prompts[2][-1]["content"]  # the second answer used the rewrite


def test_answer_refuses_out_of_scope_without_an_llm_call_and_user_filters_override(tmp_path):
    from tests.test_graph import ScriptedLLM, answer

    llm = ScriptedLLM(answers=[answer("Intelligent Cloud revenue increased driven by Azure consumption", "S1")])
    with _agent_client(tmp_path, llm) as c:
        refused = c.post("/api/answer", json={"query": "What were Apple's total net sales in fiscal 2019?"}).json()
        assert refused["abstained"] and "2019" in refused["abstain_reason"] and "refuse" in refused["steps"]
        assert refused["intent"] is None and refused["sources"] == [] and llm.prompts == []

        # The question names no company; the sidebar's MSFT filter decides.
        body = c.post("/api/answer", json={"query": "Why did cloud revenue increase in fiscal 2025?",
                                           "tickers": ["MSFT"]}).json()
    assert body["filters"]["tickers"] == ["MSFT"] and body["filters"]["fiscal_years"] == [2025]
    assert {s["hit"]["ticker"] for s in body["sources"]} == {"MSFT"}
    assert c.post("/api/answer", json={"query": "x", "thread_id": "bad id!"}).status_code == 422


def test_answer_returns_xbrl_facts_as_sources(tmp_path):
    from app.agent.xbrl import XbrlStore, load_filing_periods
    from tests.test_graph import FIXTURES, ScriptedLLM, answer

    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "NVDA.json").write_text((FIXTURES / "companyfacts_nvda_sample.json").read_text())
    xbrl = XbrlStore(tmp_path / "x", load_filing_periods(FIXTURES / "manifest_nvda_sample.json"))
    llm = ScriptedLLM(answers=[answer("Revenue was $130,497 million in fiscal 2025", "S1")])
    with _agent_client(tmp_path, llm, xbrl) as c:
        body = c.post("/api/answer", json={"query": "What was NVIDIA's revenue in fiscal 2025?"}).json()
    assert body["facts"] and body["facts"][0].startswith("[XBRL NVDA")
    fact = body["sources"][0]
    assert fact["hit"]["section"] == "XBRL" and fact["hit"]["stages"] == {"xbrl": 1.0} and fact["cited"]


def test_locked_retriever_holds_the_lock_only_during_model_calls():
    import threading

    from app.api.main import LockedRetriever

    lock = threading.Lock()

    class Probe:
        rerank_candidates = 30

        def search(self, *a, **k):
            return lock.locked()

        def search_many(self, *a, **k):
            return lock.locked()

    locked = LockedRetriever(Probe(), lock)
    assert locked.search("q") and locked.search_many([]) and not lock.locked()
    assert locked.rerank_candidates == 30


# --- streaming --------------------------------------------------------------------------------------


def _events(res) -> list[tuple[str, dict]]:
    import json

    out = []
    for block in res.text.strip().split("\n\n"):
        kind = next(line[7:] for line in block.splitlines() if line.startswith("event: "))
        data = json.loads(next(line[6:] for line in block.splitlines() if line.startswith("data: ")))
        out.append((kind, data))
    return out


def test_answer_stream_sends_node_steps_then_the_answer(tmp_path):
    from tests.test_graph import ScriptedLLM, answer

    llm = ScriptedLLM(answers=[answer("Services revenue increased due to advertising", "S1"),
                               answer("Services net sales grew driven by cloud services", "S1")],
                      rewrites=[{"standalone_question": "Why did Apple's services revenue change in fiscal 2022?"}])
    q = {"query": "Why did Apple's services revenue increase in fiscal 2025?", "thread_id": "s-1"}
    with _agent_client(tmp_path, llm) as c:
        res = c.post("/api/answer/stream", json=q)
        follow = _events(c.post("/api/answer/stream", json={"query": "And in fiscal 2022?", "thread_id": "s-1"}))
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
    events = _events(res)
    kinds = [k for k, _ in events]
    assert kinds[-1] == "answer" and set(kinds[:-1]) == {"step"}
    steps = [d["node"] for k, d in events if k == "step"]
    assert steps[0] == "analyze" and set(steps[1:3]) == {"retrieve", "xbrl"} and steps[3:] == ["generate", "verify", "respond"]
    by_node = {d["node"]: d for k, d in events if k == "step"}
    assert by_node["analyze"]["in_scope"] and by_node["analyze"]["filters"]["tickers"] == ["AAPL"]
    assert by_node["retrieve"]["hits"] > 0 and by_node["retrieve"]["intent"] and by_node["xbrl"]["facts"] == []
    assert by_node["verify"] == {**by_node["verify"], "claims": 1, "verified": 1, "abstained": False}
    elapsed = [d["elapsed_ms"] for k, d in events if k == "step"]
    assert elapsed == sorted(elapsed)
    final = events[-1][1]
    assert final["answer"].startswith("Services revenue increased") and final["thread_id"] == "s-1"
    assert sorted(final["steps"]) == sorted(steps)  # retrieve and xbrl are parallel: order may differ
    # memory works through the streaming path too
    assert follow[0][1]["standalone_query"] == "Why did Apple's services revenue change in fiscal 2022?"
    assert follow[-1][1]["filters"]["fiscal_years"] == [2022]


def test_answer_stream_reports_errors_as_events_and_refusals_as_short_streams(tmp_path, monkeypatch):
    from app.generation.llm import LLMError

    class FailingLLM:
        def generate(self, messages, output):
            raise LLMError("groq: 429; ollama is not running")

    with _agent_client(tmp_path, FailingLLM()) as c:
        events = _events(c.post("/api/answer/stream", json={"query": "Why did Apple's services revenue increase in fiscal 2025?"}))
        refused = _events(c.post("/api/answer/stream", json={"query": "What is Microsoft's current stock price?"}))
    assert events[-1] == ("error", {"status": 502, "detail": "LLM providers failed: groq: 429; ollama is not running"})
    assert [d["node"] for k, d in events if k == "step"][:1] == ["analyze"]
    assert [d.get("node") for _, d in refused[:-1]] == ["analyze", "refuse", "respond"]
    assert refused[0][1]["in_scope"] is False and refused[-1][0] == "answer" and refused[-1][1]["abstained"]

    import app.api.main as main

    def no_keys():
        raise LLMError("No LLM providers configured")

    monkeypatch.setattr(main, "build_llm", no_keys)
    with TestClient(_app_with_llm(None, tmp_path)) as c:  # no agent: a plain 503 before any streaming
        res = c.post("/api/answer/stream", json={"query": "revenue"})
    assert res.status_code == 503 and "No LLM providers" in res.json()["detail"]
