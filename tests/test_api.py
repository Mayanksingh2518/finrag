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
