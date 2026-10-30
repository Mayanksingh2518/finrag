"""Postgres + pgvector backend: SQL building with a fake connection; a real round trip when PG_TEST_DSN is set.

The integration test replaces the `chunks` table, so PG_TEST_DSN must point at a scratch database:
    docker compose exec db createdb -U finrag finrag_test
    PG_TEST_DSN=postgresql://finrag:finrag@localhost:5433/finrag_test python -m pytest tests/test_pg_store.py
"""

import os
from dataclasses import fields, replace

import numpy as np
import pytest

from app.ingestion.models import Chunk
from app.retrieval.dense import DenseIndex
from app.retrieval.pg_store import COLUMNS, PgVectorIndex, filter_sql, schema_sql
from app.retrieval.store import ChunkStore
from app.retrieval.types import SearchFilters
from tests.test_retrieval import CHUNKS, FakeEmbedder


class FakeConnection:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchall(self):
        return self.rows


def test_columns_cover_every_chunk_field_and_schema_has_filter_indexes():
    assert list(COLUMNS) == [f.name for f in fields(Chunk)]
    sql = "\n".join(schema_sql(384))
    assert "embedding vector(384) NOT NULL" in sql and "row integer NOT NULL UNIQUE" in sql
    assert all(f"ON chunks ({c})" in sql for c in ("ticker", "fiscal_year", "section", "chunk_type"))


def test_filter_sql_matches_the_store_mask_semantics():
    assert filter_sql(None) == ("", []) and filter_sql(SearchFilters()) == ("", [])
    where, params = filter_sql(SearchFilters(tickers=("aapl", "MSFT"), fiscal_years=(2025,), chunk_types=("table",)))
    assert where == "WHERE ticker = ANY(%s) AND fiscal_year = ANY(%s) AND chunk_type = ANY(%s)"
    assert params == [["AAPL", "MSFT"], [2025], ["table"]]


def test_pgvector_index_orders_by_inner_product_and_filters_in_sql():
    conn = FakeConnection([(3, -0.9), (0, -0.5)])
    index = PgVectorIndex(conn, 8)
    hits = index.search(np.ones(4, dtype=np.float32), 2, mask=np.ones(8, bool), filters=SearchFilters(tickers=("AAPL",)))
    assert hits == [(3, 0.9), (0, 0.5)] and len(index) == 8
    sql, params = conn.calls[0]
    assert "embedding <#> %s" in sql and "WHERE ticker = ANY(%s)" in sql and sql.endswith("ORDER BY distance LIMIT %s")
    assert params[1:] == [["AAPL"], 2]
    index.search(np.ones(4, dtype=np.float32), 2, mask=np.array([True, False, True] + [False] * 5))
    assert "WHERE row = ANY(%s)" in conn.calls[1][0] and conn.calls[1][1][1] == [0, 2]  # mask without filters


@pytest.mark.skipif(not os.environ.get("PG_TEST_DSN"), reason="needs a scratch Postgres with pgvector (PG_TEST_DSN)")
def test_round_trip_and_same_neighbours_as_faiss():
    from app.retrieval.pg_store import connect, corpus_meta, load, load_chunks

    chunks = [replace(c, metadata={"note": "ünïcode"}) if i == 0 else c for i, c in enumerate(CHUNKS)]
    vectors = FakeEmbedder().embed_documents([c.embed_text for c in chunks])
    with connect(os.environ["PG_TEST_DSN"]) as conn:
        load(conn, chunks, vectors, "fake")
        assert load_chunks(conn) == chunks and corpus_meta(conn)["embedding_model"] == "fake"
        store, faiss_index, pg_index = ChunkStore(chunks), DenseIndex(vectors), PgVectorIndex(conn, len(chunks))
        query = FakeEmbedder().embed_query("cloud revenue increased")
        for filters in (None, SearchFilters(tickers=("MSFT", "AMZN")), SearchFilters(fiscal_years=(2025,), sections=("Item 7",))):
            mask = store.mask(filters)
            expected = faiss_index.search(query, 5, mask, filters)
            got = pg_index.search(query, 5, mask, filters)
            assert [r for r, _ in got] == [r for r, _ in expected]
            assert np.allclose([s for _, s in got], [s for _, s in expected], atol=1e-6)
