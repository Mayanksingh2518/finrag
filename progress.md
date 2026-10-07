# FinRAG Progress

Single source of truth for project state. Update this file at the end of every work session.

## Current status

- **Last completed:** Phase 3 (indexing and retrieval), verified on the MacBook M4
- **In progress:** nothing
- **Next up:** Phase 4 (evaluation v0), see "Next task in detail" below
- **Active machine:** MacBook M4 (setup done 2026-10-07: venv, data, embedding cache)
- **Last updated:** 2026-10-07

## Phase checklist

- [x] **Phase 1: Data acquisition.** EDGAR 10-K downloader, 40 filings (10 companies × FY2022–2025), manifest
- [x] **Phase 2: Parsing and chunking.** 17,602 chunks (14,975 text / 2,627 table), 0 over the 512-token limit, all core items found in all 40 filings, 96.8% of chunks carry a printed page number
- [x] **Phase 3: Indexing and retrieval.** Local bge-small embeddings + FAISS, BM25, RRF hybrid, metadata filters, bge-reranker-base cross-encoder; 12/12 smoke queries in all 4 modes; 33 tests
- [ ] **Phase 4: Evaluation v0.** Golden set (~80 Qs incl. unanswerable), Recall@K / MRR / nDCG, ablation table
- [ ] **Phase 5: Grounded generation.** Structured output, page citations, citation verifier, abstention, confidence
- [ ] **Phase 6: LangGraph agent.** Query analyzer, decomposition, conversational memory, XBRL financial-facts tool
- [ ] **Phase 7: Full evaluation.** RAGAS, Langfuse tracing, latency/cost per stage
- [ ] **Phase 8: Serving.** FastAPI (`/query`, `/health`, streaming) + Streamlit UI with citations
- [ ] **Phase 9: Production.** Postgres + pgvector (Pinecone optional), Docker Compose, CI with eval regression gate
- [ ] **Phase 10: Expansion.** Earnings releases (8-K Ex-99.1), investor presentations (PDF parser)

## Next task in detail: Phase 4 (evaluation v0)

Goal: measure retrieval quality so every later change (reranker choice, chunking, query
analysis) is judged by numbers, not by the smoke test (which every mode already passes, so it
no longer discriminates).

1. **Golden set** `data/eval/golden_v0.jsonl` (committed, unlike other data; hand-checked).
   ~80 questions, each with: `id`, `question`, `category`, `filters` (what the Phase 6 analyzer
   should extract: tickers / fiscal_years / sections), `reference_answer`, and gold evidence as
   a list of `(ticker, fiscal_year, printed page)` (optionally `chunk_id`s).
   Categories, roughly: single lookup (~25), multi-year trend (~12, one evidence item per year),
   cross-company comparison (~12, decomposed per company), numeric/table (~15, evidence in table
   chunks), conversational follow-up (~6, with prior turn), unanswerable (~10: out-of-corpus
   companies/years, facts not in a 10-K). Spread across all 10 companies and 4 years.
   Build it semi-automatically: draft candidate Q/evidence pairs from chunks (e.g. MD&A segment
   paragraphs, key tables), then verify every page by reading the chunk text. No LLM key needed;
   a local Ollama model could help draft but is optional.
2. **Metrics** `app/evaluation/metrics.py`: Recall@K (K=1,3,5,10), MRR, nDCG@10 at page level
   (a hit = retrieved chunk whose ticker/FY matches and whose page range covers a gold page);
   multi-evidence questions count the fraction of gold items covered. Unit-test on toy rankings.
3. **Runner** `app/evaluation/run_retrieval_eval.py`: run each mode (bm25 / dense / hybrid /
   hybrid_rerank), with gold filters and with no filters, write `reports/retrieval_v0.md` +
   JSON (per-category breakdown, p50/p95 latency per stage).
4. **Ablations** worth one row each: reranker bge-reranker-base vs MiniLM-L-6 (8× faster, see
   benchmark below), reranker max_length 512 vs 384, rerank candidates 30 vs 50, optional
   bge-base embeddings. Pick defaults from the table and record the decision here.
5. Look at failure cases per category and note fixes for later phases (do not over-tune on v0).

## Retrieval results (Phase 3, MacBook M4)

Embedding build (bge-small, 17,602 chunks): **236 s on mps (~75 chunks/s)** vs ~5.5 chunks/s
on the Windows i7 CPU (~14× faster).

Smoke test (`python -m app.retrieval.smoke`, 12 queries, required keywords in top 3):

| Mode | Pass | p50 | max |
|---|---|---|---|
| bm25 | 12/12 | 1 ms | 2 ms |
| dense | 12/12 | 14 ms | 146 ms |
| hybrid | 12/12 | 9 ms | 15 ms |
| hybrid_rerank | 12/12 | 1,295 ms | 1,570 ms |

Reranker latency, 30 hybrid candidates per query, 12 smoke queries:

| Reranker | M4 mps p50 / p95 | M4 CPU p50 / p95 |
|---|---|---|
| bge-reranker-base, max_len 512 | 1,797 / 1,937 ms | 2,119 / 2,294 ms |
| bge-reranker-base, max_len 384 | 1,431 / 1,571 ms | 1,742 / 1,754 ms |
| ms-marco-MiniLM-L-6-v2, max_len 512 | 236 / 257 ms | 411 / 432 ms |
| ms-marco-MiniLM-L-6-v2, max_len 384 | 170 / 180 ms | n/a |

Decision: keep `bge-reranker-base` (p95 < 3 s on both devices); MiniLM vs bge is a Phase 4
ablation decided on quality. The M4 CPU is only ~15% slower than mps for the cross-encoder.
(CPU numbers measured in a process without FAISS; see the macOS OpenMP note below.)

Smoke observations to check in Phase 4: reranker sometimes prefers Item 1A risk-factor chunks
that mention the topic (AMZN "cloud growth" → Item 1A p.9; unfiltered "Meta Reality Labs
operating loss" → FY2023 Item 1A) over MD&A segment results; BM25 favors Item 1A for "Apple
services revenue". Possible fixes: section priors from the query analyzer (Phase 6), tables
for numeric questions.

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
- Windows: Docker not installed. MacBook: Docker Desktop 29.0.1 installed (Docker Model Runner
  running, no models pulled). Ollama not installed on either machine (optional offline LLM;
  on the M4: `brew install ollama && ollama pull qwen2.5:7b`).
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
- MacBook M4: Python 3.11.14 (Homebrew, `/opt/homebrew/bin/python3.11`; system default is 3.13),
  venv at `.venv` (`.venv/bin/python`), torch 2.14.1 with MPS, sentence-transformers 6.1,
  faiss-cpu 1.15.1. `.env` created with `SEC_USER_AGENT` using mayanksingh2518@gmail.com.
  Full setup (download 37 s, pipeline 17 s, embeddings 4 min) reproduced 17,602 chunks.
- **macOS: torch on CPU + FAISS in one process crashes or deadlocks.** The faiss-cpu and torch
  wheels each bundle their own `libomp`; multithreaded torch CPU inference then segfaults, and
  `KMP_DUPLICATE_LIB_OK=TRUE` turns that into a hang. On mps it works. `build_retriever` now
  refuses `DEVICE=cpu` on macOS with a clear error (`app/devices.py`). Windows is unaffected.
  If CPU-on-Mac is ever needed: one shared libomp, or numpy exact search instead of FAISS.

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
- **2026-10-07 (MacBook M4):** New-machine setup (Python 3.11 venv, torch MPS, 40 filings,
  17,602 chunks, embeddings in 236 s on mps). Finished Phase 3: smoke test 12/12 in all 4 modes,
  reranker benchmark (bge-reranker-base vs MiniLM, mps vs CPU, max_len 512/384), kept
  bge-reranker-base. Found and diagnosed the macOS torch-CPU + FAISS OpenMP crash/deadlock;
  added a fail-fast guard + test (33/33 passing). Checked for local LLMs: none installed.
