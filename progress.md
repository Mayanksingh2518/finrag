# FinRAG Progress

Single source of truth for project state. Update this file at the end of every work session.

## Current status

- **Last completed:** Phase 4 (evaluation v0): golden set, metrics, runner, ablations, decomposition preview
- **In progress:** Phase 8 started early at the user's request: FastAPI + React glassmorphism UI over retrieval (done); answer panel waits for Phase 5
- **Next up:** finish Phase 5 (see "Resume here" just below), then wire answers into the UI.
- **Resume here (2026-10-08):** Phase 5 code works end to end and the false-abstention problem is
  fixed (0.324 → 0.054 on Ollama granite4.1:3b, `reports/generation_v1_ollama.md`). Not ticked yet:
  1. **Groq baseline.** The prompt changed on 2026-10-08, so every Groq answer is a cache miss
     again (~3.5k tokens per question, ~300k for all 84 > the 200k/day cap). Run
     `LLM_PROVIDERS=groq python -m app.evaluation.run_generation_eval --out reports/generation_v1_groq`;
     it fails over (error rows) when the daily cap hits. Rerun the next day to fill the rest from cache.
  2. **Live-test the answer panel** (API on :8010 + UI) with the repaired-citation note; stop the API
     afterwards (memory).
  3. Then tick Phase 5 and start Phase 6. Carry over: figure-free claims and "whose figure"
     errors need an LLM faithfulness judge (Phase 7); T04 makes granite emit unbounded JSON.
- **Disk/memory warning (MacBook, 16 GB RAM):** the disk once filled because swap grew to 10 GB
  while the API server, an eval, tests and Ollama all held models at once. Run one model-loading
  process at a time and stop the API server during evals.
- **Active machine:** MacBook M4 (setup done 2026-10-07: venv, data, embedding cache)
- **Last updated:** 2026-10-08 (false-abstention fix, generation eval v1)

## Phase checklist

- [x] **Phase 1: Data acquisition.** EDGAR 10-K downloader, 40 filings (10 companies × FY2022–2025), manifest
- [x] **Phase 2: Parsing and chunking.** 17,602 chunks (14,975 text / 2,627 table), 0 over the 512-token limit, all core items found in all 40 filings, 96.8% of chunks carry a printed page number
- [x] **Phase 3: Indexing and retrieval.** Local bge-small embeddings + FAISS, BM25, RRF hybrid, metadata filters, bge-reranker-base cross-encoder; 12/12 smoke queries in all 4 modes; 33 tests
- [x] **Phase 4: Evaluation v0.** 84-question golden set (quote-verified pages), Recall@K / MRR / nDCG, 4 modes × filters on/off, reranker ablations, decomposition preview; hybrid_rerank recall@5 0.884, MRR 0.920; 48 tests
- [ ] **Phase 5: Grounded generation.** Structured output, page citations, citation verifier, abstention, confidence
- [ ] **Phase 6: LangGraph agent.** Query analyzer, decomposition, conversational memory, XBRL financial-facts tool
- [ ] **Phase 7: Full evaluation.** RAGAS, Langfuse tracing, latency/cost per stage
- [ ] **Phase 8: Serving.** FastAPI + React/Vite glassmorphism UI (user's choice over Streamlit). Done: `/api/health`, `/api/meta`, `/api/search`, search UI with filters, citations, tables, latency. Left: `/api/query` with streaming answers after Phase 5
- [ ] **Phase 9: Production.** Postgres + pgvector (Pinecone optional), Docker Compose, CI with eval regression gate
- [ ] **Phase 10: Expansion.** Earnings releases (8-K Ex-99.1), investor presentations (PDF parser)

## Next task in detail: finish Phase 5 (Groq baseline, live UI test)

Phase 5 is built: `llm.py` (Groq → Gemini → Ollama, retries, TPM limiter, disk cache),
`context.py`, `answer.py`, `verify.py`, `run_generation_eval.py`. Remaining before ticking it:

1. **Groq gpt-oss-120b baseline** on the 84 questions with the current prompt (see "Resume here":
   ~300k tokens > 200k/day, so it takes two days of cache-filling). Compare with
   `reports/generation_v1_ollama.md`: expect fewer format failures than the 3B model, so the gap
   shows how much the verifier repair is compensating for a small model.
2. **Live test** `/api/answer` + the answer panel on a few lookup / comparison / unanswerable
   questions; check that repaired claims show the "Citation added by the verifier" note.
3. Tick Phase 5 in this file and the README, then plan Phase 6 (LangGraph agent: query analyzer
   that extracts the filters the eval currently gets from gold, per-entity quotas, XBRL tool).

Provider facts (measured 2026-10-07): Groq free tier per model is 1,000 requests/day,
8,000 tokens/minute and a rolling **200,000 tokens/day** (not in headers). Gemini works only
through the Interactions API (`gemini-3.8-flash`) and was slow/unreliable. Ollama
`granite4.1:3b` is the default local model (`LLM_PROVIDERS=ollama,groq,gemini`).

## Generation eval v1: false-abstention fix (Phase 5, MacBook M4, 2026-10-08)

All 24 v0 false abstentions were replayed from the LLM cache and diagnosed:

| Cause | Questions | Fix |
|---|---|---|
| No citation markers at all (answer mostly right) | L05 L09 L16 L17 L23 L25 N11 N15 N16 F02 F05 T05 | citation repair |
| Markers as `(S1)`, `[S6, S2]`, `[S4, S8, S9]` | L21 T12 C07 C10 | `normalize_markers` |
| One marker block after several sentences | T04 C02 | sentences inherit the line's closing block |
| Right figure, wrong source id | N13 T10 | citation repair |
| Derived figure `12% + 11% + 11% = 34%` | L08 | arithmetic shown in the claim is checked |
| Copied the prompt example "Revenue grew 14% [S1]." | N05 | prompt uses `<statement> [S1]` |
| Wrong figure, correctly withheld | T01 C01 (T04 T05 partly) | none (verifier working) |

**Citation repair** (`verify.py`): a claim with no valid citation, or whose figures are not in its
cited sources, is re-attributed to provided sources that (a) share ≥60% of its content words and
(b) state each missing figure in a sentence/table row sharing ≥2 content words with the claim.
Rule (b) was added after the first version rescued wrong figures: T12's "$115.80 billion" capex
(really operating cash flow) and C01's "Azure $168.9 billion" (really Microsoft Cloud). Applying
rule (b) to model-cited claims too was tested and rejected: it failed 14/76 correct claims (table
rows share too few words). Repaired claims are flagged (`repaired`, shown in the UI and CLI) and
cap confidence at medium. Invented figures are never rescued.

**Gold review:** 10 questions got alt quotes where the cited page restates the reference fact
(L04 L22 L23 N01 N08 N13 C04 C07 F01 F04; e.g. Meta revenue "$200.97 billion" on p.60, not only
the 200,966 tables). Like the Phase 4 review, this only looked at pages the system cited.
`reports/retrieval_v0.md` predates these alts (not rerun).

| Run (Ollama granite4.1:3b, 84 q) | Gold | False abst. | Citation hit | Evidence recall | Claim support | Figure recall |
|---|---|---|---|---|---|---|
| v0 (old verifier) | old | 0.324 | 0.527 | 0.464 | 0.911 | 0.467 |
| v0 answers + new verifier | old | 0.068 | 0.743 | 0.661 | 0.978 | 0.579 |
| v0 answers + new verifier | new | 0.068 | 0.878 | 0.783 | 0.978 | 0.579 |
| **v1: new prompt + new verifier** | new | **0.054** | 0.863 | **0.797** | 0.978 | **0.583** |

Abstention recall stays **1.000** in every run (all 10 unanswerable refused by the model).
Reports: `reports/generation_v0_ollama_repair.md`, `reports/generation_v1_ollama.md`.

Reading: the verifier fix is almost the whole gain; the prompt fix is within noise (fixes N05,
but T04 now makes granite generate unbounded JSON → 1 error). Remaining v1 abstentions: L17
("November 2023", too short to attribute), T05/T06/C01 (wrong or mislabelled figures). Known
verifier limits, for Phase 7's LLM judge: (1) claims without figures are only checked for a valid
citation (L01/L13 cite unrelated chunks; word overlap can't separate them from correct ones);
(2) a real figure attached to the wrong metric/entity passes (C07: a JPM segment's $4.5B net
income as the firm's; T05's $15.0B).

## Generation eval v0 results (Phase 5, MacBook M4)

Ollama `granite4.1:3b`, hybrid_rerank k=10, gold filters, automatic decomposition, 3,500-token
source budget, 84 questions (`reports/generation_v0_ollama.md`).

| Metric | Value |
|---|---|
| Abstention recall (unanswerable refused) | 1.000 (10/10) |
| Abstention precision | 0.294 |
| False abstention rate | 0.324 (24/74), all withheld by the verifier |
| Citation hit (verified citation on a gold page) | 0.527 |
| Evidence recall | 0.464 |
| Claim support | 0.911 |
| Figure recall | 0.467 |
| LLM latency | p50 17.5 s, p95 24.6 s (local, M4) |

Reading: the system never answers what it can't support, but it is too strict: a third of
answerable questions are withheld. The verifier and the 3B model's citation habits are the next
target. Groq gpt-oss-120b baseline still pending (daily token cap, see "Resume here").

## Evaluation v0 results (Phase 4, MacBook M4)

Full report: `reports/retrieval_v0.md` (+ per-question JSON). Golden set
`data/eval/golden_v0.jsonl`: 84 questions = lookup 27, numeric 17, trend 12, comparison 12,
follow-up 6, unanswerable 10; 119 evidence items over all 10 companies and FY2022–2025.

| Mode (k=10) | Filters | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | p50 |
|---|---|---|---|---|---|---|---|
| bm25 | gold | 0.373 | 0.697 | 0.819 | 0.579 | 0.620 | <1 ms |
| dense | gold | 0.538 | 0.828 | 0.902 | 0.764 | 0.777 | 8 ms |
| hybrid | gold | 0.579 | 0.860 | 0.926 | 0.794 | 0.805 | 7 ms |
| **hybrid_rerank** | gold | **0.707** | **0.884** | 0.922 | **0.920** | 0.877 | 2.2 s |
| hybrid_rerank + decomposition | gold | 0.704 | 0.901 | **0.966** | 0.905 | **0.902** | 1.6 s (p95 7 s) |
| bm25 | none | 0.271 | 0.464 | 0.602 | 0.414 | 0.442 | <1 ms |
| hybrid | none | 0.396 | 0.783 | 0.858 | 0.665 | 0.686 | 8 ms |
| hybrid_rerank | none | 0.694 | 0.884 | 0.905 | 0.909 | 0.866 | 2.1 s |

Reranker ablations (gold filters): bge-reranker-base 30 cand / len 512 = MRR 0.920;
len 384 = 0.909 (~15% faster); 50 cand = 0.917 (1.6× slower); MiniLM-L-6 = 0.818 (7× faster).
**Decision: keep bge-reranker-base, 30 candidates, max_length 512.** MiniLM is the fallback if
latency ever matters more than ~0.1 MRR.

Findings:
- Hybrid beats either retriever alone; the reranker is the biggest single gain (MRR +0.13
  filtered, +0.24 unfiltered). BM25 alone is weak on numeric questions (recall@5 0.65).
- With the reranker, filters barely matter for quality (0.884 vs 0.884 recall@5): the
  cross-encoder finds the right company/year itself. Filters still cut work and noise.
- Lookup, numeric and follow-up (via the standalone rewrite) are near-solved: recall@5 1.0.
- **Trend and comparison are the gap** (recall@5 0.62 / 0.67): one filing crowds out the
  others. Decomposition (one sub-search per company × year, round-robin merge ordered by score,
  `app/retrieval/decompose.py`) lifts recall@10 for comparison 0.792 → 0.958 and trend
  0.729 → 0.833 under reranking. At k=5 a 4-year trend can't fit, so Phase 6 should use
  **per-entity quotas** (top-n per sub-query) rather than one global k, and batch the
  sub-queries' reranking (decomposed p95 is 7 s with sequential reranking).
- Residual trend misses: the reranker prefers Item 8 notes or segment pages over the MD&A
  sentence with the figure (e.g. JPM net income → segment results pages), and Item 5 buyback
  tables over the annual total.

Golden-set method (for interviews): evidence is written as verbatim quotes; `build_golden`
fills `pages` with every page of the filing containing a quote, and `validate` checks each page
really contains it. Labels therefore never come from the retriever and survive re-chunking. A
failure review found 8 questions where the same fact was restated on another page (Item 8
notes, liquidity section); alt quotes were added (noted in each row). That review only looked
at pages the reranked system retrieved, so it slightly favours that mode; v1 should add
labels from a pooled review of all modes.

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

- Frontend: React + Vite + TypeScript with hand-written glassmorphism CSS (user asked for a
  fully glassmorphism UI; Streamlit can't do that). FastAPI serves `frontend/dist` at `/`, so one
  process runs the app; `npm run dev` proxies `/api` to :8010 for hot reload.

- Gold evidence is quote-verified and page-level (not chunk ids); `data/eval/` and `reports/` are committed.
- Reranker default `bge-reranker-base`, 30 candidates, max_length 512 (Phase 4 ablation).

- Source = SEC EDGAR HTML, not IR-site PDFs (stable URLs, structured tables, exact page breaks).
- `fiscal_year` = year of the period end (matches company labels: NVDA FY2025 ended 2025-01-26).
- Original 10-K only; 10-K/A excluded.
- Dependencies are added to `requirements.txt` phase by phase.
- Build eval v0 (Phase 4) before generation so retrieval tuning is measured.
- Multi-entity questions use per-(company, year) decomposition with per-entity quotas (Phase 4 data).

## Environment notes

- Two machines: Windows laptop (CPU only) and MacBook M4 (MPS). Per-machine commands and
  gotchas are in the "Machines" table in `CLAUDE.md`. `app/devices.py` picks mps/cuda/cpu
  automatically (`DEVICE` env var overrides).
- Windows: Python 3.11.7, venv at `finrag/.venv` (`.venv/Scripts/python`).
- Hardware: CPU-only laptop, 16 GB RAM, i7-1165G7 (4 cores), MX350 2 GB (not usable for LLMs), ~74 GB free disk.
- Windows: Docker not installed. MacBook: Docker Desktop 29.0.1 installed (Docker Model Runner
  running, no models pulled). Ollama not installed on either machine (optional offline LLM;
  on the M4: `brew install ollama && ollama pull qwen2.5:7b`).
- **Ollama output cap:** `OllamaProvider` sets `num_predict=1500` (answers need < 500 tokens).
  Without it, granite on T04 never closed its JSON and generated for 15+ minutes; the 180 s HTTP
  timeout did not fire, probably because the Mac slept on battery. Run long evals plugged in and
  under `caffeinate -i` (the cache resumes a killed run).
- MacBook `.env` has `SEC_USER_AGENT`, `GEMINI_API_KEY` and `GROQ_API_KEY` (verified
  2026-10-07; chmod 600). Keys go in `.env` only: `.env.example` is tracked by git (the keys
  were first pasted there by mistake and moved before any commit). The Windows laptop needs
  its own `.env`.
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
- MacBook: `gh` logged in as Mayanksingh2518 (device-code web login, 2026-10-07) and
  `gh auth setup-git` done, so `git push` works over HTTPS. `~/.ssh/id_ed25519` is not
  registered with GitHub (SSH push would fail).
- Full retrieval eval takes ~20 min on the M4 (mostly reranking); `--no-ablations` ~8 min.
- Web app: API on **port 8010** (port 8000 on the MacBook is taken by another local app).
  Node 24 / npm 11 on the MacBook. Startup loads the retriever and runs one warm-up search
  (~15-20 s); reranked searches take ~1.3-2.5 s, plain hybrid ~10 ms.
- UI checks: headless Chrome screenshots (`--headless=new --screenshot`); Chrome's minimum
  window is ~500 px wide, so test phone widths inside a 390 px iframe.

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
- **2026-10-07 (MacBook M4):** Phase 4 built: golden set (84 questions, 119 quote-verified
  evidence items, `build_golden` resolver/validator, `find_evidence` authoring CLI), page-level
  metrics, eval runner + report, reranker ablations, decomposition preview
  (`app/retrieval/decompose.py`). hybrid_rerank: recall@5 0.884, MRR 0.920; decomposition lifts
  comparison/trend recall@10 to 0.958/0.833. Kept bge-reranker-base. 48 tests passing.
  Committed Phase 3 + Phase 4; pushed to GitHub after logging in gh on this Mac.
- **2026-10-07 (MacBook M4):** User added API keys. Moved them from the tracked `.env.example`
  into the gitignored `.env` before any commit. Verified both: Groq gpt-oss-120b works (8k
  TPM, 1k RPD free); Gemini works only through the Interactions API with `gemini-3.8-flash`,
  and was slow and unreliable. Updated the Phase 5 plan to make Groq primary.
- **2026-10-07 (MacBook M4):** Frontend, at the user's request (glassmorphism, FastAPI + React,
  search UI before Phase 5). Built `app/api/` (FastAPI: health, meta, search with filters and
  decomposition, serves the built UI, warm-up at startup, lock around the models) + 6 API
  tests (56 total). Built `frontend/`: aurora backdrop, frosted panels, filter sidebar
  (collapsible on phones), evidence cards with highlighted terms, rendered Markdown tables,
  rerank/BM25/dense meters, copyable `[TICKER FY p.N]` citations, latency per stage, URL state,
  `/` shortcut, reduced-motion and no-backdrop-filter fallbacks. Fixed during visual checks: the
  body background hid the aurora; phone layout. Lint and type-check clean.
- **2026-10-07 (MacBook M4):** After a restart (disk full from 10 GB swap), fixed the claim
  splitter, committed and pushed Phase 5 code, API and frontend. Eval reports now name the model
  that answered. Groq run stopped at question 57: a 200k tokens/day cap (not in headers), so Groq
  now fails over immediately on a daily-limit 429 instead of retrying (+1 test, 87 total). Ran
  the full Ollama eval (results above). Published an interactive data-flow diagram of the
  pipeline as a private claude.ai artifact.
- **2026-10-08 (MacBook M4):** Fixed false abstentions. Replayed all 84 questions from the LLM
  cache and diagnosed the 24 v0 false abstentions (table in "Generation eval v1"). Added
  citation-marker normalization, closing-block inheritance, arithmetic support and context-checked
  citation repair (`repaired` flag through API/CLI/UI); fixed the prompt example the 3B model
  copied; added gold alt quotes for 10 questions; capped Ollama output (`num_predict`) after a
  15-minute runaway generation; fixed a flaky timing assertion in a retrieval test. False
  abstention 0.324 → 0.054, citation hit 0.527 → 0.863, abstention recall 1.000. 92 tests passing;
  frontend lint/type-check clean.
