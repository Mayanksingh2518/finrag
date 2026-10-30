# FinRAG Architecture

## Scope

An agentic RAG system over SEC annual reports (Form 10-K) for 10 companies × 4 fiscal
years (FY2022–FY2025, 40 filings). It answers multi-company, multi-year questions with
page-level citations, refuses when evidence is insufficient, and is measured by an
evaluation harness with ablations.

**In scope (v1):** 10-K ingestion, hybrid retrieval, reranking, query analysis and
decomposition, conversational follow-ups, grounded generation with citations and
abstention, structured XBRL financial facts, offline evaluation, tracing, API, UI, Docker.

**Later:** earnings releases (8-K Ex-99.1), investor presentations (PDF), Pinecone/pgvector.

## Pipeline

```
                       ┌──────────── Query Analyzer (rules; LLM only to rewrite follow-ups) ─────────┐
User query + history → │ condense follow-up → extract {companies, fiscal_years, sections, metric}    │
                       │ classify intent: lookup | compare | trend | numeric | out_of_scope           │
                       │ decompose: "Compare MSFT vs AMZN cloud" → one sub-query per company × year   │
                       └──────────────────────────────────────────────────────────────────────────────┘
                                                    │
                     ┌──────────────────────────────┼──────────────────────────────┐
                     ▼                              ▼                              ▼
          Metadata filter                 Hybrid retrieval per sub-query    XBRL facts tool (numeric)
          (ticker, FY, section)           dense (FAISS) + BM25 → RRF        exact reported figures
                                                    │
                                          Cross-encoder reranker
                                                    │
                                Context selection (per-sub-query quotas, dedupe,
                                token budget, keep table chunks intact)
                                                    │
                                Generator (structured output: answer, claims, citations)
                                                    │
                                Grounding check: every claim cites a chunk and its figures
                                appear in a cited chunk; mis-cited claims re-attributed only
                                when the figure sits next to the claim's words; nothing
                                verified → abstain
                                                    │
                                Answer + [TICKER FY p.N] citations + confidence
```

### Agent graph (LangGraph, `app/agent/graph.py`)

```
START → analyze ─out of range─→ refuse ───────────────────────────────→ respond → END
           └─in corpus─→ retrieve ─┐                                     ↑
           └───────────→ xbrl ─────┴→ generate ─→ verify ─(answered)────┘
                                          └(no sources)→ respond
                                     verify ─(abstained under a section filter, once)→ widen → retrieve + xbrl
```

`retrieve` (retrieval plan: per-(company, year) sub-queries, quotas, MD&A prior, one batched
rerank) and `xbrl` (company facts for detected company-level metrics and named years) run in the
same step; `generate` waits for both and puts the facts first in the context. Conversation memory is
the thread's turn list (`ConversationMemory`, LRU over threads, last 6 exchanges), passed in as
`history`; per-turn chunks are not checkpointed. A question that names its own company and year and
doesn't refer back ("its", "that year", "And ...?") is treated as standalone: no carry-over, no LLM
rewrite call.

## Key design decisions

| Decision | Why |
|---|---|
| SEC EDGAR HTML instead of IR-site PDFs | Canonical, permanent URLs; tables stay structured; page breaks are explicit CSS markers, so page numbers are exact. A generic PDF parser is added later for presentations. |
| Fiscal year = year of period end | Matches each company's own labeling (NVIDIA FY2025 ended Jan 2025, MSFT FY2025 ended Jun 2025). The analyzer maps "2025" to fiscal years and states the mismatch with calendar years. |
| Section-aware chunking (Item 1, 1A, 7, 8…) | Enables `section` filters ("risk factors" → Item 1A) and better chunk coherence. Tables are kept as whole Markdown chunks with a generated caption. |
| Hybrid dense + BM25 with RRF | Financial text is full of exact terms (segment names, "Intelligent Cloud", "cross-border volume") that dense retrieval misses; RRF needs no score calibration. |
| Cross-encoder reranker | Large precision gain at small k; cheap at this corpus size. |
| Decomposition for comparisons | One query for "MSFT vs AMZN" lets the bigger company crowd out the other. Per-entity sub-queries with quotas guarantee coverage. |
| XBRL company facts as a structured tool | Numbers like revenue growth should come from reported figures, not from an LLM reading a table. Text retrieval explains *why*; facts answer *how much*. |
| XBRL facts next to text, never instead | The GAAP line item can differ from the company's own definition (Meta capex incl. finance leases, Amazon net cash capex). Facts come only from the fiscal year's own 10-K (accession + period), with YoY change from the same filing; the prompt says the filing text wins on definitions. |
| Explicit turn memory instead of a LangGraph checkpointer | The analyzer needs only the turns; checkpointing would store every step's chunks per thread and warns on every custom dataclass. Swappable for Redis/Postgres in Phase 9. |
| Abstention as a first-class output | The generator must cite chunks for every claim; uncited claims are dropped, and with no support it returns "insufficient evidence". Evaluated with unanswerable questions. |
| Verify figures in code, repair citations, judge prose later | Small local models often answer correctly but cite nothing or the wrong source. A deterministic checker (figures matched by value across units) accepts a claim when its figures appear in the cited chunk, or re-attributes it when they appear in the same sentence/row as the claim's words in another provided chunk; invented figures are never rescued. It cannot tell *whose* figure it is (a segment's net income vs the firm's) or check figure-free claims: that needs an LLM faithfulness judge (Phase 7). |
| Zero-cost, provider-agnostic models | Local bge embeddings and cross-encoder on CPU; Gemini free tier for generation with Groq and local Ollama as fallbacks, behind one LLM interface with caching and rate-limit backoff. No vendor lock-in, no spend. |
| Storage behind interfaces | FAISS + local files first, Postgres (metadata/chunks) + pgvector or Pinecone later, with no changes to retrieval logic. |
| Exact FAISS (`IndexFlatIP`), no ANN index | Benchmarked on our data: exact search over 17.6k vectors takes 0.36 ms (retrieval is 1.5 s, the reranker), with recall 1.0 under metadata filters, where HNSW/IVF drop to 0.87/0.59 at cheap settings. IVF / PQ / ScaNN / DiskANN solve problems this corpus doesn't have; HNSW in pgvector past ~1M vectors. See "Vector index choice". |

## Vector index choice: why exact search, not IVF, ScaNN or DiskANN

**What we use.** FAISS `IndexFlatIP` over normalized `bge-small-en-v1.5` vectors (384 dims), so inner
product = cosine similarity (`app/retrieval/dense.py`). Search is exact (brute force). Metadata filters
(ticker, fiscal year, section) are applied *inside* the search with `IDSelectorBatch`, so only allowed
chunks are scored, never "search everything, then filter". Dense search is one leg of the hybrid:
dense + BM25 → RRF (k=60) → `bge-reranker-base` cross-encoder on the top 30.

### Measured on our data

`python -m app.retrieval.index_benchmark` (`reports/index_benchmark.md`): all 17,602 chunk vectors,
the 84 golden retrieval queries (74 with a gold company/year filter), recall@10 = overlap with exact
search's top 10, one query on one thread (MacBook M4).

| Index | Size MB | p50 ms | Recall@10 | Recall@10 with company/year filter | Build s |
|---|---|---|---|---|---|
| **Flat, exact (ours)** | 27.0 | 0.364 | **1.000** | **1.000** | 0.00 |
| IVF-Flat, nlist 133, nprobe 1 | 27.4 | 0.011 | 0.665 | 0.588 | 0.04 |
| IVF-Flat, nprobe 8 | 27.4 | 0.033 | 0.989 | 0.982 | 0.03 |
| IVF-Flat, nprobe 32 | 27.4 | 0.109 | 1.000 | 1.000 | 0.03 |
| IVF-SQ8 (8-bit scalar quantization), nprobe 8 | 7.1 | 0.082 | 0.982 | 0.980 | 0.04 |
| IVF-PQ (48 B/vector), nprobe 32 | 1.6 | 0.082 | 0.688 | 0.742 | 2.67 |
| PQ, flat scan (48 B/vector) | 1.2 | 0.178 | 0.574 | not supported | 2.65 |
| HNSW, M 32, efSearch 16 | 31.8 | 0.020 | 0.957 | **0.868** | 1.67 |
| HNSW, M 32, efSearch 64 | 31.8 | 0.043 | 0.998 | 0.995 | 1.93 |
| HNSW, M 32, efSearch 128 | 31.8 | 0.082 | 1.000 | 0.999 | 1.66 |
| LSH, 1,536 bits | 5.7 | 0.076 | 0.687 | not supported | 0.09 |

What it shows:
- **Exact search costs 0.36 ms.** Retrieval takes 1.5 s p50 (`progress.md`, "Tracing v0"), almost all of
  it the cross-encoder. The best ANN index saves ~0.3 ms of 1,500 ms: 0.02%, invisible to a user.
- **ANN only matches exact search when tuned up to nearly exact work** (IVF nprobe 32 scans ~24% of the
  vectors; HNSW efSearch 128). Cheaper settings lose recall: IVF nprobe 1 misses a third of the true top 10.
- **Filters are where ANN breaks.** 74 of 84 questions carry a company/year filter that leaves a few
  hundred allowed chunks. HNSW efSearch 16 drops from 0.957 to 0.868 under the filter (the graph walk
  passes through disallowed nodes and runs out of candidates); IVF nprobe 1 drops to 0.588 (the probed
  cluster holds few allowed chunks). Exact search is 1.000 by construction.
- **Compression costs accuracy** our 27 MB index doesn't need to pay: PQ/IVF-PQ recall 0.57-0.74 (it needs a
  re-ranking pass on full vectors to recover), and FAISS's PQ and LSH indexes can't filter inside the search.
- Exact search is also the **honest baseline for evaluation**: retrieval metrics (recall@5 0.884, MRR 0.920)
  measure the models, not index approximation.

### Every index family compared

| Family (examples) | How it works | Recall | Speed | Memory | Training / updates | Filtered search | Built for | FinRAG verdict |
|---|---|---|---|---|---|---|---|---|
| **Flat / brute force** (FAISS `IndexFlatIP`/`L2`; pgvector without an index) | Compares the query with every vector | Exact (1.0) | O(N); 0.36 ms at 17.6k | Full vectors (27 MB) | None; add/delete instantly | Exact, via ID selector | < ~1M vectors, ground truth for tuning any ANN | **Used.** Fast enough with no recall loss |
| **IVF** (FAISS `IndexIVFFlat`; pgvector `ivfflat`; Milvus) | k-means splits space into `nlist` cells; searches the `nprobe` nearest cells | Tunable via `nprobe`; 0.67-1.0 here | Sub-linear | Full vectors + centroids | Needs training; drifts as data changes (retrain) | Weak with tight filters (0.588 at nprobe 1) | 1M-100M vectors in RAM | Not needed; filter weakness |
| **IVF + scalar quantization** (`IVF-SQ8`, SQ4) | IVF with each dimension stored in 8 (or 4) bits | Near-exact at 8 bits (0.98) | Like IVF | ~4x smaller | Training | As IVF | RAM-limited large indexes | Saves 20 MB we don't need to save |
| **Product quantization** (`IndexPQ`, `IVFPQ`, OPQ; Milvus, Vespa) | Splits vectors into sub-vectors, stores a codebook id per sub-vector | Lossy (0.57-0.74 here) unless re-ranked on full vectors | Fast scans via lookup tables | 8-64 B/vector (1.2 MB here) | Codebook training (2.7 s) | FAISS `IndexPQ` can't filter in-search | Billions of vectors, memory-bound | Accuracy loss for no reason at our size |
| **HNSW** (FAISS `IndexHNSWFlat`, pgvector `hnsw`, Qdrant, Weaviate, Elasticsearch, OpenSearch, hnswlib) | Multi-layer proximity graph; greedy walk from the top layer | High, tunable via `efSearch` (0.96-1.0 here) | Very fast (0.02-0.08 ms) | Full vectors + graph (~18% more here) | No training; incremental inserts; deletes are awkward | Drops with tight filters (0.868 at ef 16); engines add workarounds | 100k-100M vectors, low latency | **Next step** past ~1M vectors, in pgvector (Phase 9) |
| **ScaNN** (Google; also in AlloyDB) | Partitioning + anisotropic vector quantization + exact re-ranking | Very high at high speed | Among the fastest on public ANN benchmarks | Compressed | Training | Supported in recent versions | Millions-billions, Google stack | Extra library, mainly Linux wheels (we need macOS + Windows); gains only at scale. Not benchmarked: not in FAISS |
| **DiskANN / Vamana** (Microsoft; pgvectorscale, Milvus DiskANN, Azure Cosmos DB) | Graph index stored on SSD; compressed vectors in RAM guide the search | High | Fast with few SSD reads | Small RAM footprint; index on disk | Slow build; fresh variants support updates | Filtered-DiskANN exists | Billions of vectors that don't fit in RAM | Solves a memory problem a 27 MB index doesn't have. Not benchmarked |
| **Other graphs** (NSG, CAGRA on GPU) | Pruned proximity graphs, GPU-built graphs | High | Very fast (GPU for CAGRA) | Graph + vectors | Static or GPU build | Limited | Large static indexes, GPU serving | No GPU on one laptop; static data only |
| **Tree-based** (Annoy, KD-trees) | Random projection trees; search several trees | Medium; degrades in high dims | Fast | Trees + vectors (memory-mapped) | Static: rebuild to add | Not in-search | Read-only indexes, mmap sharing (Spotify) | Superseded by HNSW for 384-dim vectors |
| **LSH** (FAISS `IndexLSH`, FALCONN) | Random hyperplanes hash similar vectors to the same buckets/bits | Low-medium (0.69 here) | Fast | Small (bits) | None | FAISS `IndexLSH` can't filter in-search | Streaming, theory-friendly baselines | Worst recall in the benchmark |
| **Binary quantization** (1 bit/dim; Qdrant, Weaviate, Vespa) | Sign of each dimension, Hamming distance, re-rank on full vectors | Needs re-ranking; suits large-dim models | Very fast | 32x smaller | None | As the host engine | Huge collections of 1024+ dim embeddings | Pointless at 384 dims and 17.6k vectors |

Managed vector databases (Pinecone, Qdrant, Weaviate, Milvus, pgvector) are hosts for these index
families, not different algorithms; most default to HNSW. The project keeps storage behind an interface
so the Phase 9 move to pgvector changes no retrieval logic.

### When to switch

Past roughly a few hundred thousand to a million vectors (Phase 10 adding earnings releases and
presentations, or many more companies/years), or once dense search shows up in the latency trace.
Then: **HNSW in pgvector** (no training, incremental inserts, filters next to the metadata), tuning
`m`, `ef_construction` and `ef_search` against the exact index as ground truth and checking *filtered*
recall, which this benchmark shows is the weak spot. IVF-SQ8 if memory becomes the constraint;
DiskANN only at a scale this project won't reach.

### Answer in one breath

"I benchmarked it on our data. Exact FAISS search over 17.6k vectors takes 0.36 ms, while retrieval
takes 1.5 s because of the cross-encoder, so an ANN index would save 0.02% of the latency. ANN only
matched exact recall when tuned up to nearly exact work, and with the company/year filters that
most questions carry, HNSW at low efSearch fell from 0.96 to 0.87 recall and IVF at nprobe 1 to 0.59.
PQ and LSH lose 30-40% of recall. ScaNN and DiskANN solve problems at millions to billions of
vectors. So exact search, which also keeps the retrieval metrics honest; past about a million vectors,
HNSW in pgvector, tuned against the exact index with filtered recall checked."

## Chunk metadata

`chunk_id, ticker, company, fiscal_year, form, filing_date, section (e.g. "Item 7"),
section_title, page_start, page_end, chunk_type (text|table), source_url, text`

## Evaluation

- Golden set (~80 questions) across categories: single lookup, multi-year trend,
  cross-company comparison, numeric, conversational follow-up, unanswerable.
  Each item: question, reference answer, gold (ticker, FY, page) evidence.
- Retrieval: Recall@K, MRR, nDCG against the gold pages.
- Generation: RAGAS faithfulness, answer relevancy, context precision/recall;
  citation accuracy; abstention precision/recall on unanswerable items.
- Ops: p50/p95 latency per stage, tokens/cost per query (Langfuse traces).
- Ablation table: BM25 / dense / hybrid / +rerank / +query analysis / +decomposition.
