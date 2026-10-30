"""Postgres + pgvector backend: chunks and their embeddings in one table, dense search in SQL.

`VECTOR_BACKEND=pgvector` makes `build_retriever` load the chunks from Postgres and run dense search
there (`PgVectorIndex`), instead of `chunks.jsonl` + FAISS. Everything else (BM25, RRF, reranking,
the agent) is unchanged: rows keep their position in `chunks.jsonl` (`row` column), which is the id
BM25 and the retriever share.

Search is exact by default (`ORDER BY embedding <#> q`, no vector index), so pgvector returns the
same neighbours as FAISS `IndexFlatIP` (see "Vector index choice" in docs/ARCHITECTURE.md). Filters
are SQL `WHERE` clauses on indexed metadata columns, applied before ranking. `--hnsw` adds an HNSW
index (approximate; pgvector then uses it for unfiltered and filtered queries alike).

    docker compose up -d db
    python -m app.retrieval.pg_store                 # load chunks + cached embeddings (idempotent)
    VECTOR_BACKEND=pgvector python -m app.retrieval.search_cli "..."
"""

import argparse
import json
import logging
import time
from dataclasses import asdict, fields

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from app.ingestion.models import Chunk
from app.retrieval.types import SearchFilters

log = logging.getLogger(__name__)

# Chunk field -> SQL type. Kept in sync with the dataclass by a test.
COLUMNS: dict[str, str] = {
    "chunk_id": "text PRIMARY KEY", "doc_id": "text NOT NULL", "ticker": "text NOT NULL", "company": "text NOT NULL",
    "fiscal_year": "integer NOT NULL", "form": "text NOT NULL", "filing_date": "text NOT NULL",
    "period_end": "text NOT NULL", "part": "text", "section": "text NOT NULL", "section_title": "text NOT NULL",
    "subsection": "text", "page_start": "integer NOT NULL", "page_end": "integer NOT NULL",
    "page_label_start": "text", "page_label_end": "text", "chunk_type": "text NOT NULL", "context": "text NOT NULL",
    "text": "text NOT NULL", "token_count": "integer NOT NULL", "source_url": "text NOT NULL",
    "metadata": "jsonb NOT NULL",
}
FILTER_COLUMNS = ("ticker", "fiscal_year", "section", "chunk_type")


def schema_sql(dims: int) -> list[str]:
    cols = ",\n  ".join(f"{name} {kind}" for name, kind in COLUMNS.items())
    return [
        "CREATE EXTENSION IF NOT EXISTS vector",
        f"CREATE TABLE IF NOT EXISTS chunks (\n  row integer NOT NULL UNIQUE,\n  {cols},\n  embedding vector({dims}) NOT NULL\n)",
        *(f"CREATE INDEX IF NOT EXISTS chunks_{c}_idx ON chunks ({c})" for c in FILTER_COLUMNS),
        "CREATE TABLE IF NOT EXISTS corpus_meta (key text PRIMARY KEY, value text NOT NULL)",
    ]


def filter_sql(filters: SearchFilters | None) -> tuple[str, list]:
    """WHERE clause for the filters (same semantics as `ChunkStore.mask`); column names are constants."""
    if filters is None or filters.is_empty():
        return "", []
    clauses, params = [], []
    for column, values in (("ticker", filters.tickers and [t.upper() for t in filters.tickers]),
                           ("fiscal_year", filters.fiscal_years), ("section", filters.sections),
                           ("chunk_type", filters.chunk_types)):
        if values:
            clauses.append(f"{column} = ANY(%s)")
            params.append(list(values))
    return "WHERE " + " AND ".join(clauses), params


def connect(dsn: str) -> psycopg.Connection:
    conn = psycopg.connect(dsn, autocommit=True)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")  # register_vector needs the type to exist
    register_vector(conn)
    return conn


def _vector_literal(v: np.ndarray) -> str:
    return "[" + ",".join(repr(x) for x in v.tolist()) + "]"  # float32 -> exact decimal -> float4


def load(conn: psycopg.Connection, chunks: list[Chunk], vectors: np.ndarray, model: str, hnsw: bool = False) -> None:
    """Replace the table contents with these chunks (row = list position) and embeddings, in one transaction."""
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    names = ["row", *COLUMNS, "embedding"]
    with conn.transaction(), conn.cursor() as cur:
        for stmt in schema_sql(vectors.shape[1]):
            cur.execute(stmt)
        cur.execute("TRUNCATE chunks")
        cur.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw")
        with cur.copy(f"COPY chunks ({', '.join(names)}) FROM STDIN") as copy:
            for row, (chunk, vector) in enumerate(zip(chunks, vectors)):
                d = asdict(chunk)
                d["metadata"] = json.dumps(d["metadata"], ensure_ascii=False)
                copy.write_row([row, *(d[c] for c in COLUMNS), _vector_literal(vector)])
        if hnsw:
            cur.execute("CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_ip_ops) "
                        "WITH (m = 16, ef_construction = 200)")
        meta = {"embedding_model": model, "dims": str(vectors.shape[1]), "chunks": str(len(chunks)),
                "index": "hnsw" if hnsw else "exact"}
        cur.executemany("INSERT INTO corpus_meta (key, value) VALUES (%s, %s) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", list(meta.items()))
        cur.execute("ANALYZE chunks")


def corpus_meta(conn: psycopg.Connection) -> dict[str, str]:
    try:
        return dict(conn.execute("SELECT key, value FROM corpus_meta").fetchall())
    except psycopg.errors.UndefinedTable:
        return {}


def load_chunks(conn: psycopg.Connection) -> list[Chunk]:
    """All chunks in row order (rows must be 0..n-1: they are the ids BM25 and the retriever share)."""
    rows = conn.execute(f"SELECT row, {', '.join(COLUMNS)} FROM chunks ORDER BY row").fetchall()
    if [r[0] for r in rows] != list(range(len(rows))):
        raise RuntimeError("chunks.row is not 0..n-1: reload with `python -m app.retrieval.pg_store`")
    return [Chunk(**dict(zip(COLUMNS, r[1:]))) for r in rows]


class PgVectorIndex:
    """Dense search in Postgres with the same contract as `DenseIndex`: top-k (row, inner product)."""

    def __init__(self, conn: psycopg.Connection, size: int):
        self.conn = conn
        self.size = size

    def __len__(self) -> int:
        return self.size

    def search(self, query: np.ndarray, k: int, mask: np.ndarray | None = None,
               filters: SearchFilters | None = None) -> list[tuple[int, float]]:
        """`filters` become SQL; `mask` (the same filters as rows) is only used when no filters are given."""
        where, params = filter_sql(filters)
        if not where and mask is not None:
            where, params = "WHERE row = ANY(%s)", [np.flatnonzero(mask).tolist()]
        sql = (f"SELECT row, embedding <#> %s AS distance FROM chunks {where} "  # <#> = negative inner product
               "ORDER BY distance LIMIT %s")
        rows = self.conn.execute(sql, [np.asarray(query, dtype=np.float32), *params, k]).fetchall()
        return [(int(r), -float(d)) for r, d in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hnsw", action="store_true", help="add an approximate HNSW index (default: exact search)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from app.config import get_settings
    from app.retrieval.embedder import EmbeddingCache, SentenceTransformerEmbedder, embed_chunks
    from app.retrieval.store import ChunkStore

    settings = get_settings()
    start = time.perf_counter()
    chunks = ChunkStore.from_jsonl(settings.processed_dir / "chunks.jsonl").chunks
    embedder = SentenceTransformerEmbedder(settings.embedding_model, device=settings.device)  # only for cache misses
    vectors = embed_chunks(chunks, embedder, EmbeddingCache(settings.index_dir, settings.embedding_model))
    with connect(settings.database_url) as conn:
        load(conn, chunks, vectors, settings.embedding_model, hnsw=args.hnsw)
        n = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        size = conn.execute("SELECT pg_size_pretty(pg_total_relation_size('chunks'))").fetchone()[0]
    log.info("Loaded %d chunks (%s, %s search) in %.1f s", n, size, "HNSW" if args.hnsw else "exact",
             time.perf_counter() - start)


if __name__ == "__main__":
    main()
