# FinRAG Progress

Single source of truth for project state. Update this file at the end of every work session.

## Current status

- **Last completed:** Phase 2 (parsing and chunking)
- **In progress:** Phase 3 (indexing and retrieval): code + 32 tests done; embeddings being built; smoke test not yet run
- **Next up:** finish Phase 3 (see "Remaining Phase 3 steps" below), then Phase 4
- **Machine switch:** user is moving to the MacBook (M4). First "go" there: run "New machine setup"
  from `CLAUDE.md` (data and indexes are gitignored), then continue Phase 3.
- **Last updated:** 2026-10-07

## Phase checklist

- [x] **Phase 1: Data acquisition.** EDGAR 10-K downloader, 40 filings (10 companies × FY2022–2025), manifest
- [x] **Phase 2: Parsing and chunking.** 17,602 chunks (14,975 text / 2,627 table), 0 over the 512-token limit, all core items found in all 40 filings, 96.8% of chunks carry a printed page number
- [ ] **Phase 3: Indexing and retrieval.** Local bge embeddings + FAISS, BM25, RRF hybrid, metadata filters, cross-encoder reranker *(in progress: code and tests done)*
- [ ] **Phase 4: Evaluation v0.** Golden set (~80 Qs incl. unanswerable), Recall@K / MRR / nDCG, ablation table
- [ ] **Phase 5: Grounded generation.** Structured output, page citations, citation verifier, abstention, confidence
- [ ] **Phase 6: LangGraph agent.** Query analyzer, decomposition, conversational memory, XBRL financial-facts tool
- [ ] **Phase 7: Full evaluation.** RAGAS, Langfuse tracing, latency/cost per stage
- [ ] **Phase 8: Serving.** FastAPI (`/query`, `/health`, streaming) + Streamlit UI with citations
- [ ] **Phase 9: Production.** Postgres + pgvector (Pinecone optional), Docker Compose, CI with eval regression gate
- [ ] **Phase 10: Expansion.** Earnings releases (8-K Ex-99.1), investor presentations (PDF parser)

## Next task in detail: finish Phase 3

### Done (2026-10-07)
- Installed CPU-only torch 2.14 + sentence-transformers 6.1, faiss-cpu 1.15, bm25s 0.3, PyStemmer.
- Modules in `app/retrieval/`: `types.py` (SearchFilters, ScoredChunk, SearchResult), `store.py`
  (ChunkStore with numpy metadata masks shared by both indexes), `embedder.py` (bge-small,
  query instruction prefix, resumable on-disk cache keyed by chunk_id + content hash),
  `dense.py` (FAISS IndexFlatIP + IDSelectorBatch pre-filtering), `bm25.py` (bm25s, financial
  tokenizer keeping `10-k`/`7a`/`416,161`, Snowball stemming of words only), `hybrid.py` (RRF k=60),
  `retriever.py` (modes `bm25|dense|hybrid|hybrid_rerank`, per-stage scores + timings),
  `factory.py`, `build_index.py`, `search_cli.py`, `smoke.py`. `app/reranking/cross_encoder.py`.
- `tests/test_retrieval.py`: 12 tests with a fake hashed-BoW embedder (no downloads). 32/32 pass.
- Embedding cache `data/indexes/embeddings__BAAI__bge-small-en-v1.5.{npy,json}`: 13,312 / 17,602
  done when this was written; a resumed build was running.

### Remaining Phase 3 steps
1. Build embeddings: `python -m app.retrieval.build_index` (resumes from cache; prints
   "Done: 17602 x 384"). Windows CPU: ~5.5 chunks/s (~55 min total). On the M4 it runs on `mps`;
   record the measured throughput here (CPU vs MPS is a nice data point for the README).
2. Run `.venv/Scripts/python -m app.retrieval.smoke` (12 target queries x 4 modes, top-3 keyword
   check + latency). Record the summary table here.
3. Check reranker latency (`BAAI/bge-reranker-base`, 30 candidates) on the current machine
   (record both machines if possible). If p95 > ~3 s, make
   `cross-encoder/ms-marco-MiniLM-L-6-v2` the default (`reranker_model` in `app/config.py`) and
   note the trade-off. Consider `max_length=384` for the reranker.
4. Inspect failures from the smoke test (e.g. table vs text chunks, unfiltered company
   confusion) and fix obvious issues; leave tuning to Phase 4, which measures it properly.
5. Update this file, tick Phase 3, write "Next task in detail: Phase 4" (golden set design:
   ~80 questions across lookup / trend / comparison / numeric / follow-up / unanswerable, with
   gold (doc_id, printed page) evidence; Recall@K, MRR, nDCG; ablation over the 4 modes).

## Ingestion design notes (Phase 2, for interviews)

- Pages split at `<hr style="page-break-after:always">`, which every one of the 40 filings uses.
  Printed page numbers come from footers in 4 formats (`6`, `5.`, `Apple Inc. | 2025 Form 10-K | 2`,
  `MASTERCARD 2025 FORM 10-K 21`). A number only counts as a page label if a neighbouring page
  agrees; gaps between agreeing pages are interpolated.
- Repeated headers/footers are detected by frequency (≥25% of pages, digits normalized) and
  flagged as `furniture`, not deleted: JPM's running header "Management's discussion and analysis"
  is the best section signal in its annex.
- **By-reference items:** JPM (all years) and NVDA FY2022 put MD&A/financials in an annex after
  Part IV, with one-line stubs under Items 7/8. Annex headings are mapped back to the stub item, so
  JPM's MD&A is `Item 7` (pp. 35–163), not `Item 15`. Before this fix, 90% of JPM was mislabeled.
- TOC pages vs. stub pages: both list many items on one page; TOC has <80 chars between items.
- Tables: currency/`%`/`)` cells glued to values, letter footnotes `(g)` attached (numeric `(5)`
  is a negative number), rowspan/colspan expanded right-aligned, then **adjacent columns that are
  never both filled are merged**, which aligns headers over values for every filer's layout.
  One-row tables (footers, checkboxes) and tables with prose cells become text.
- Chunk sizing uses the **embedding model's tokenizer**: bge-small truncates at 512 tokens, so
  body target 320 / max 420 tokens plus a contextual header
  (`Company (TICKER) Form 10-K, fiscal year N | Item 7: MD&A | <subsection>`). Chunks never cross
  Items; headings start new chunks; tables are separate chunks with captions and split by rows
  with repeated headers; a lone heading before a table becomes its caption; overlap (≤50 tokens
  of trailing sentences) only on size splits.
- Full pipeline: 40 filings in ~44 s. Outputs `chunks.jsonl` (33 MB), `pages.jsonl` (page text for
  citation verification), `quality_report.{md,json}`.

## Zero-cost stack (user requirement: no paid services)

| Component | Choice |
|---|---|
| Embeddings | `BAAI/bge-small-en-v1.5` via sentence-transformers (local CPU); `bge-base` as an ablation |
| Vector / keyword | FAISS + `bm25s`, RRF fusion |
| Reranker | `BAAI/bge-reranker-base` cross-encoder (local CPU) |
| Main LLM | Gemini API free tier (`GEMINI_API_KEY`, from Google AI Studio) |
| Fallback LLM | Groq free tier (`GROQ_API_KEY`) |
| Offline LLM | Ollama, `qwen2.5:3b` or `llama3.2:3b` (CPU) |
| Eval judge | RAGAS with Gemini/Groq; cache all judge calls |
| Tracing | Langfuse Cloud Hobby tier (or Opik free) |
| DB / deploy | PostgreSQL + pgvector, Docker Desktop (Phase 9) |
| Multimodal (Phase 10) | Gemini free-tier vision for chart/slide captioning; ColPali skipped (needs GPU) |

All LLM calls go through one provider-agnostic interface with retries, rate-limit backoff,
an on-disk response cache, and provider fallback (Gemini → Groq → Ollama).

## Key decisions (see docs/ARCHITECTURE.md for rationale)

- Source = SEC EDGAR HTML, not IR-site PDFs (stable URLs, structured tables, exact page breaks).
- `fiscal_year` = year of the period end (matches company labels: NVDA FY2025 ended 2025-01-26).
- Original 10-K only; 10-K/A excluded.
- Dependencies are added to `requirements.txt` phase by phase.
- Build eval v0 (Phase 4) before generation so retrieval tuning is measured.

## Environment notes

- Two machines: Windows laptop (CPU only) and MacBook M4 (MPS). Per-machine commands and
  gotchas are in the "Machines" table in `CLAUDE.md`. `app/devices.py` picks mps/cuda/cpu
  automatically (`DEVICE` env var overrides).
- Windows: Python 3.11.7, venv at `finrag/.venv` (`.venv/Scripts/python`).
- Hardware: CPU-only laptop, 16 GB RAM, i7-1165G7 (4 cores), MX350 2 GB (not usable for LLMs), ~74 GB free disk.
- Docker not installed yet (needed in Phase 9). Ollama not installed yet (optional, offline LLM).
- `.env` not created yet: user must copy `.env.example`, set `SEC_USER_AGENT` with their email,
  and add free keys `GEMINI_API_KEY` (aistudio.google.com) and `GROQ_API_KEY` (console.groq.com)
  before Phase 5. Phases 2–4 need no keys (local embeddings and reranker).
- Git initialized in `finrag/`, no commits yet (commit only when the user asks).
- Hugging Face cache: `~/.cache/huggingface` (bge tokenizer already downloaded). Windows has no
  symlink support there; the warning is silenced in `app/ingestion/tokens.py`.
- Run the pipeline: `.venv/Scripts/python -m app.ingestion.pipeline` (from `finrag/`).
- **Windows throttles long background jobs on battery** (efficiency mode / EcoQoS): one embedding
  slice took 21 min instead of ~2.5 min, and a Phase 2 run stalled for 605 s. Fixes: plug into AC,
  or raise the process priority:
  `Get-Process python | ? WorkingSet64 -gt 100MB | % { $_.PriorityClass = 'AboveNormal' }`.
- Models cached in `~/.cache/huggingface`: bge-small-en-v1.5 (downloaded); bge-reranker-base
  downloads on first reranked search.
- GitHub: https://github.com/Mayanksingh2518/finrag (branch `main`, `origin` tracks it). On the M4,
  `git clone` it; pull before starting work on either machine. `gh` CLI not installed on Windows.
- Windows embedding cache reached 13,312 / 17,602 before the switch; it isn't in git, so the M4
  rebuilds from scratch (fast on MPS). Embeddings from MPS vs CPU differ only by float noise.

## Session log

- **2026-10-07:** Scope, architecture, and roadmap defined. Phase 1 built: `app/config.py`,
  `app/ingestion/companies.py`, `app/ingestion/sec_downloader.py`, 6 passing tests.
  All 40 filings downloaded (JPM required walking 26 EDGAR archive pages).
- **2026-10-07:** User set a zero-cost requirement. Switched to local embeddings/reranker,
  Gemini + Groq free tiers, Ollama fallback. Updated config, `.env.example`, architecture doc.
- **2026-10-07:** Phase 2 built: `models.py`, `html_parser.py`, `tables.py`, `sections.py`,
  `chunker.py`, `tokens.py`, `pipeline.py`; 20 passing tests. Quality report drove fixes:
  table column alignment, rowspan, Mastercard/JPM footer formats (page labels 0%/13% → 98%/99%),
  JPM/NVDA annex sections, TOC vs. stub detection, oversized prose tables, orphan headings.
  Result: 17,602 chunks, 0 over token limit, 0 filings missing a core item.
- **2026-10-07:** Phase 3 started: retrieval stack written (store, embedder + cache, FAISS dense,
  BM25, RRF, cross-encoder reranker, retriever, CLIs, smoke test), 32/32 tests passing. Embedding
  build interrupted by Windows background throttling and a task time limit; resumes from cache.
- **2026-10-07:** Prepared for the switch to the M4: `CLAUDE.md` moved into the repo with
  per-machine setup, device auto-selection (`app/devices.py`: mps/cuda/cpu) for the embedder and
  reranker, progress notes made machine-neutral.
