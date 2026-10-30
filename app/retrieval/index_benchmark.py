"""Vector index benchmark on FinRAG's real embeddings: exact flat search vs FAISS's ANN indexes.

Backs the "Vector index choice" section of docs/ARCHITECTURE.md with measured numbers. Every index
is built over the 17.6k bge-small chunk vectors and queried with the golden set's retrieval queries
(embedded with the bge query instruction). Exact `IndexFlatIP` is the ground truth; each ANN config
is scored on recall@10 against it, unfiltered and under the question's gold company/year filter
(applied inside the search with an ID selector, as `DenseIndex` does). Latency is per query,
single-threaded, batch size 1 (how the retriever searches).

ScaNN and DiskANN are not in FAISS and not installed (see the doc for why); they are compared on
paper only.

Usage:
    python -m app.retrieval.index_benchmark            # -> reports/index_benchmark.md
"""

import argparse
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass

import faiss
import numpy as np

from app.config import PROJECT_ROOT

K = 10


@dataclass
class IndexConfig:
    name: str
    family: str
    build: Callable[[int], faiss.Index]  # dim -> untrained index
    params: Callable[[np.ndarray | None], faiss.SearchParameters | None]  # allowed ids -> search params
    note: str = ""


def _selector(allowed: np.ndarray | None):
    return faiss.IDSelectorBatch(allowed) if allowed is not None else None


def _plain(allowed):
    return faiss.SearchParameters(sel=_selector(allowed)) if allowed is not None else None


def _ivf(nprobe: int):
    return lambda allowed: faiss.SearchParametersIVF(nprobe=nprobe, sel=_selector(allowed))


def _hnsw(ef: int):
    return lambda allowed: faiss.SearchParametersHNSW(efSearch=ef, sel=_selector(allowed))


def configs(n: int) -> list[IndexConfig]:
    nlist = int(round(np.sqrt(n)))  # ~133 for 17.6k vectors, the usual sqrt(N) rule

    def ivf_flat(d):
        return faiss.IndexIVFFlat(faiss.IndexFlatIP(d), d, nlist, faiss.METRIC_INNER_PRODUCT)

    def ivf_sq8(d):
        return faiss.IndexIVFScalarQuantizer(faiss.IndexFlatIP(d), d, nlist, faiss.ScalarQuantizer.QT_8bit,
                                             faiss.METRIC_INNER_PRODUCT)

    def ivf_pq(d):
        return faiss.IndexIVFPQ(faiss.IndexFlatIP(d), d, nlist, 48, 8, faiss.METRIC_INNER_PRODUCT)

    def hnsw(d):
        index = faiss.IndexHNSWFlat(d, 32, faiss.METRIC_INNER_PRODUCT)
        index.hnsw.efConstruction = 200
        return index

    out = [IndexConfig("Flat (exact)", "flat", lambda d: faiss.IndexFlatIP(d), _plain, "ground truth")]
    out += [IndexConfig(f"IVF-Flat nprobe={p}", "ivf", ivf_flat, _ivf(p), f"nlist={nlist}") for p in (1, 8, 32)]
    out += [IndexConfig(f"IVF-SQ8 nprobe={p}", "ivf", ivf_sq8, _ivf(p), "8-bit scalar quantization") for p in (8, 32)]
    out += [IndexConfig(f"IVF-PQ nprobe={p}", "ivf", ivf_pq, _ivf(p), "PQ 48 x 8 bit (48 B/vector)") for p in (8, 32)]
    out += [IndexConfig("PQ (flat scan)", "pq", lambda d: faiss.IndexPQ(d, 48, 8, faiss.METRIC_INNER_PRODUCT),
                        _plain, "48 x 8 bit, no inverted lists")]
    out += [IndexConfig(f"HNSW M=32 efSearch={ef}", "hnsw", hnsw, _hnsw(ef), "efConstruction=200") for ef in (16, 64, 128)]
    out += [IndexConfig("LSH 1536 bits", "lsh", lambda d: faiss.IndexLSH(d, 4 * d), _plain,
                        "random hyperplanes (Hamming; cosine on normalized vectors)")]
    return out


@dataclass
class Row:
    name: str
    family: str
    note: str
    build_s: float
    size_mb: float
    p50_ms: float
    p95_ms: float
    recall: float
    recall_filtered: float | None
    filter_supported: bool = True


def _recall(found: np.ndarray, truth: np.ndarray) -> float:
    t = set(int(i) for i in truth if i >= 0)
    return len(t & set(int(i) for i in found if i >= 0)) / len(t) if t else 1.0


def run(vectors: np.ndarray, queries: np.ndarray, allowed: list[np.ndarray | None]) -> list[Row]:
    faiss.omp_set_num_threads(1)  # per-query latency as the retriever sees it
    d = vectors.shape[1]
    exact = faiss.IndexFlatIP(d)
    exact.add(vectors)
    truth = exact.search(queries, K)[1]
    truth_f = [exact.search(q[None], K, params=_plain(a))[1][0] if a is not None else None
               for q, a in zip(queries, allowed)]
    rows = []
    for cfg in configs(len(vectors)):
        start = time.perf_counter()
        index = cfg.build(d)
        if not index.is_trained:
            index.train(vectors)
        index.add(vectors)
        build_s = time.perf_counter() - start
        size_mb = faiss.serialize_index(index).nbytes / 1e6
        lat, rec, rec_f = [], [], []
        filter_supported = True
        for q, t, a, tf in zip(queries, truth, allowed, truth_f):
            s = time.perf_counter()
            ids = index.search(q[None], K, params=cfg.params(None))[1][0]
            lat.append((time.perf_counter() - s) * 1000)
            rec.append(_recall(ids, t))
            if a is not None and filter_supported:
                try:
                    rec_f.append(_recall(index.search(q[None], K, params=cfg.params(a))[1][0], tf))
                except RuntimeError:  # e.g. IndexPQ / IndexLSH reject search params: no in-search filtering
                    filter_supported = False
        rows.append(Row(cfg.name, cfg.family, cfg.note, build_s, size_mb, statistics.median(lat),
                        statistics.quantiles(lat, n=20)[-1], statistics.fmean(rec),
                        statistics.fmean(rec_f) if rec_f and filter_supported else None, filter_supported))
    return rows


def render(rows: list[Row], n: int, d: int, nq: int, nf: int) -> str:
    lines = ["# Vector index benchmark", "",
             "Generated by `python -m app.retrieval.index_benchmark`. Real data: "
             f"{n:,} bge-small-en-v1.5 chunk vectors ({d} dims, float32, normalized), {nq} golden retrieval "
             f"queries ({nf} with a gold company/year filter). Recall@{K} is overlap with exact search's top {K}; "
             "filtered recall applies the filter inside the search (ID selector). Latency: one query, one thread.", "",
             f"| Index | Build s | Size MB | p50 ms | p95 ms | Recall@{K} | Filtered recall@{K} | Notes |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        rf = "unsupported" if not r.filter_supported else "-" if r.recall_filtered is None else f"{r.recall_filtered:.3f}"
        lines.append(f"| {r.name} | {r.build_s:.2f} | {r.size_mb:.1f} | {r.p50_ms:.3f} | {r.p95_ms:.3f} | "
                     f"{r.recall:.3f} | {rf} | {r.note} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(PROJECT_ROOT / "reports" / "index_benchmark.md"))
    args = parser.parse_args()

    from app.config import get_settings
    from app.evaluation.build_golden import DEFAULT_PATH
    from app.evaluation.golden import load_golden
    from app.retrieval.embedder import BGE_QUERY_INSTRUCTION, EmbeddingCache, SentenceTransformerEmbedder

    settings = get_settings()
    cache = EmbeddingCache(settings.index_dir, settings.embedding_model)
    vectors_by_key = cache.load()
    keys = list(vectors_by_key)
    vectors = np.ascontiguousarray(np.stack([vectors_by_key[k] for k in keys]), dtype=np.float32)
    golden = load_golden(DEFAULT_PATH)
    embedder = SentenceTransformerEmbedder(settings.embedding_model, settings.device)
    queries = np.ascontiguousarray(embedder.embed_documents([BGE_QUERY_INSTRUCTION + q.retrieval_query for q in golden]),
                                   dtype=np.float32)
    # Keys look like "AAPL-FY2022-10-K-0000:<hash>": company and fiscal year without loading chunks.
    meta = [(k.split("-")[0], int(k.split("-")[1][2:])) for k in keys]
    allowed = []
    for q in golden:
        f = q.filters
        if not (f.tickers or f.fiscal_years):
            allowed.append(None)
            continue
        ids = [i for i, (t, y) in enumerate(meta)
               if (not f.tickers or t in f.tickers) and (not f.fiscal_years or y in f.fiscal_years)]
        allowed.append(np.array(ids, dtype=np.int64))
    rows = run(vectors, queries, allowed)
    report = render(rows, len(vectors), vectors.shape[1], len(queries), sum(a is not None for a in allowed))
    from pathlib import Path
    Path(args.out).write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
