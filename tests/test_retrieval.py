"""Retrieval tests with a deterministic fake embedder (no model downloads)."""

import zlib

import numpy as np
import pytest

from app.ingestion.models import Chunk
from app.retrieval.bm25 import BM25Index, tokenize
from app.retrieval.dense import DenseIndex
from app.retrieval.embedder import EmbeddingCache, embed_chunks
from app.retrieval.hybrid import reciprocal_rank_fusion
from app.retrieval.retriever import Retriever
from app.retrieval.store import ChunkStore
from app.retrieval.types import SearchFilters


class FakeEmbedder:
    """Hashed bag-of-words vectors: texts sharing words are similar."""

    model_name = "fake"
    dim = 64

    def __init__(self) -> None:
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        self.calls += len(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for tok in tokenize(text):
                out[i, zlib.crc32(tok.encode()) % self.dim] += 1
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]


class ReverseReranker:
    """Prefers shorter passages, to prove reranking reorders candidates."""

    model_name = "fake-reranker"

    def score(self, query: str, passages: list[str]) -> list[float]:
        return [-float(len(p)) for p in passages]


def make_chunk(i: int, ticker: str, year: int, section: str, text: str, kind: str = "text") -> Chunk:
    return Chunk(
        chunk_id=f"{ticker}-FY{year}-10-K-{i:04d}", doc_id=f"{ticker}-FY{year}-10-K", ticker=ticker,
        company=ticker, fiscal_year=year, form="10-K", filing_date="", period_end="", part=None,
        section=section, section_title=section, subsection=None, page_start=1, page_end=1,
        page_label_start="1", page_label_end="1", chunk_type=kind,  # type: ignore[arg-type]
        context=f"{ticker} FY{year} | {section}", text=text, token_count=10, source_url="",
    )


CHUNKS = [
    make_chunk(0, "AAPL", 2025, "Item 7", "Services revenue increased due to advertising and App Store."),
    make_chunk(1, "AAPL", 2022, "Item 7", "Services net sales grew driven by cloud services and AppleCare."),
    make_chunk(2, "MSFT", 2025, "Item 7", "Intelligent Cloud revenue increased driven by Azure consumption."),
    make_chunk(3, "AMZN", 2025, "Item 7", "AWS segment sales increased from customer usage of cloud services."),
    make_chunk(4, "NVDA", 2022, "Item 1A", "Supply chain risks: we depend on foundries such as TSMC."),
    make_chunk(5, "NVDA", 2025, "Item 1A", "Export controls to China restrict sales of data center GPUs."),
    make_chunk(6, "V", 2025, "Item 7", "International transaction revenue increased on cross-border volume.", "text"),
    make_chunk(7, "V", 2025, "Item 8", "| | 2025 |\n| International transaction revenue | $13,000 |", "table"),
]


@pytest.fixture
def retriever() -> Retriever:
    store = ChunkStore(CHUNKS)
    embedder = FakeEmbedder()
    dense = DenseIndex(embedder.embed_documents([c.embed_text for c in CHUNKS]))
    bm25 = BM25Index([c.embed_text for c in CHUNKS])
    return Retriever(store, bm25, dense, embedder, ReverseReranker(), candidates_per_retriever=5)


def test_tokenizer_keeps_financial_tokens_and_stems_words():
    tokens = tokenize("Revenues of $416,161 million in Item 7A of the Form 10-K rose 3.5%")
    assert {"416,161", "7a", "10-k", "3.5", "revenu"} <= set(tokens)
    assert "the" not in tokens


def test_rrf_rewards_agreement_between_lists():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 1, 4]])
    assert [row for row, _ in fused][:2] == [1, 3]  # 1 is 1st+2nd, 3 is 3rd+1st
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)


def test_store_mask_combines_filters():
    store = ChunkStore(CHUNKS)
    assert store.mask(SearchFilters()) is None
    mask = store.mask(SearchFilters(tickers=("nvda",), fiscal_years=(2022,)))
    assert np.flatnonzero(mask).tolist() == [4]
    mask = store.mask(SearchFilters(tickers=("V",), chunk_types=("table",)))
    assert np.flatnonzero(mask).tolist() == [7]


@pytest.mark.parametrize("mode", ["bm25", "dense", "hybrid", "hybrid_rerank"])
def test_every_mode_respects_filters(retriever, mode):
    result = retriever.search("cloud revenue increased", SearchFilters(tickers=("MSFT", "AMZN")), k=5, mode=mode)
    assert result.hits
    assert {h.chunk.ticker for h in result.hits} <= {"MSFT", "AMZN"}
    assert "total" in result.timings_ms


def test_bm25_finds_exact_terms(retriever):
    hits = retriever.search("TSMC foundries", k=1, mode="bm25").hits
    assert hits[0].chunk.chunk_id == "NVDA-FY2022-10-K-0004"


def test_hybrid_records_both_stages(retriever):
    hits = retriever.search("international transaction revenue", SearchFilters(tickers=("V",)), k=2, mode="hybrid").hits
    assert {h.chunk.chunk_id for h in hits} == {"V-FY2025-10-K-0006", "V-FY2025-10-K-0007"}
    assert all("rrf" in h.stages and "bm25_rank" in h.stages and "dense_rank" in h.stages for h in hits)


def test_rerank_reorders_candidates(retriever):
    result = retriever.search("revenue increased", k=3, mode="hybrid_rerank")
    scores = [h.stages["rerank"] for h in result.hits]
    assert scores == sorted(scores, reverse=True)
    assert "rerank" in result.timings_ms


def test_filter_with_no_matches_returns_empty(retriever):
    assert retriever.search("revenue", SearchFilters(tickers=("TSLA",))).hits == []


def test_embedding_cache_only_embeds_new_or_changed_chunks(tmp_path):
    embedder = FakeEmbedder()
    cache = EmbeddingCache(tmp_path, "fake")
    first = embed_chunks(CHUNKS[:4], embedder, cache)
    assert embedder.calls == 4

    changed = CHUNKS[:4] + CHUNKS[4:6]
    changed[0] = make_chunk(0, "AAPL", 2025, "Item 7", "Edited text about services revenue.")
    second = embed_chunks(changed, embedder, cache)
    assert embedder.calls == 4 + 3  # one edited + two new
    assert np.allclose(first[1:4], second[1:4])
    assert second.shape == (6, FakeEmbedder.dim)
