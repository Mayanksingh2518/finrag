# FinRAG handoff

For whoever picks this project up next, person or AI. Written 2026-11-02, after Phase 10 closed.

**Read in this order:** this file, then `CLAUDE.md` (working rules), `reports/eval_earnings_v0.md` and `reports/eval_v1.md` (results), `docs/ARCHITECTURE.md` (design). `progress.md` is the full history, experiment by experiment; where this file summarizes, it has the detail.

## 1. Where things stand

FinRAG is an agentic RAG system over SEC filings, built as an AI Engineer portfolio project. **All 10 planned phases are done.** Nothing is required next. The one improvement worth making is in section 12.

| | State on 2026-11-02 |
|---|---|
| Code | `main`, in sync with `origin` at `d5858d0`, apart from this handoff and the `scripts/audits/` files added with it |
| CI | Green on `d5858d0` (tests with real Postgres, UI lint and build, eval gate) |
| Tests | 324 collected: 322 pass, and 2 need `PG_TEST_DSN` (they pass on a scratch db and in CI) |
| Eval gate | 20 of 20 |
| Running | Nothing: no API, dashboard or eval. The `db` container is stopped |
| Groq quota | `gpt-oss-120b` had used ~215k tokens in the 24 h before 16:26 that day. Check the dashboard before heavy runs |

**To do, only you can:**
- Commit this file and `scripts/audits/`, and `reports/table_questions_larger_model.json`. Commit only when the user asks.
- If using `VECTOR_BACKEND=pgvector`: run `python -m app.retrieval.pg_store` with the `db` container up. When last checked, the main database held only the 17,602 10-K chunks in the old schema, and the API refuses to start until it's reloaded. FAISS mode, the default, needs nothing.
- Optional for the portfolio: add a screenshot of a cited answer to the README, with `scripts/ui_screenshot.py`. There isn't one yet.

## 2. Goals and rules

- **Purpose:** a portfolio project. The owner has said they intend to stop after committing.
- **Zero cost is a hard requirement.** No paid APIs or services: local models and free tiers only.
- **Commit only when asked.** Never push without a remote the user provided. Commit message and PR attribution follow the session's instructions.
- **Report honestly.** Don't mark anything done that wasn't verified, and state failures with their numbers. The reports keep rejected experiments and known failures.
- **"go" command:** a message that is just "go" means work the "Next task in detail" in `progress.md`, verify, update `progress.md` and the README, and stop with a summary. See `CLAUDE.md`.
- **Style:** typed, small modules, tests with fixtures, no notebook-only logic. Add dependencies only when needed.
- **Run one model-loading process at a time** on the 16 GB laptops: the disk once filled because swap reached 10 GB.

## 3. What it does

Answers questions over 40 annual reports (10-K) and 160 quarterly earnings releases (8-K Exhibit 99.1) for AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, V and MA, fiscal years 2022-2025. Every claim carries a citation, `[AAPL FY2025 p.23]`, `[NVDA Q3 FY2025 release]` or `[XBRL NVDA Total revenue FY2022-FY2025]`, and it refuses when the evidence isn't there.

```
question + history
  -> analyze (rules; LLM only to rewrite follow-ups) -- out of range or live data --> refuse --> respond
  -> retrieve (plan: sub-query per company x year x quarter) + xbrl (annual facts), in parallel
  -> generate (structured JSON with [S1] markers) -- no sources --> respond
  -> verify (code) -- abstained under a section filter, once --> widen --> retrieve + xbrl
  -> respond
```

## 4. Results

| | Annual reports | Earnings releases |
|---|---|---|
| Golden set | 84 questions | 60 (46 answerable, 14 not) |
| Judged correctness, answerable (abstention scores 0) | 0.865, both judges | 0.870 gpt-oss, 0.867 qwen |
| Correctness of answers given | 0.901 | 0.930 |
| Abstention recall | 1.000 | 1.000 (14 of 14) |
| False abstention | 0.041 | 0.065 (3 of 46) |
| Retrieval recall@5 / MRR, gold filters | 0.891 / 0.933 | 0.886 / 0.699 |
| Plan recall@10 / MRR | 0.966 / 0.927 | 1.000 / 0.699 |
| Citation hit | 0.878 incl. XBRL | 0.848 |
| Claim support (verifier) | 0.965 | 0.984 |

**The columns aren't comparable.** The earnings set is mostly stated figures with no "why" questions, and both sets were written alongside the system, not independently.

10-K history: judged correctness 0.730 (v0) -> 0.777 (XBRL series tables, intent rules) -> 0.865 (routing trend and comparison to Groq); trend 0.250 -> 0.792, comparison 0.667 -> 0.958-1.000.

Earnings history: 1.000 on 35 easy questions -> 0.970 on 47 -> 0.870 on 60, as harder questions were added. Every drop came from fresh questions, not from a code change.

Latency, uncached: local answers ~17 s p50 (generation is 90%), routed ~6-8 s; earnings first-35 run p50 20.9 s, p95 46.1 s. Retrieval: 1.1-1.6 s single, 3-5 s for four quarters, 6.6 s for a yearly trend. FAISS search is 0.36 ms, and the cross-encoder is the cost.

### Evidence for the larger model

14 table questions (E29, E34-E46), `reports/table_questions_larger_model.json`, each figure checked by hand against the source:

| | Local granite4.1:3b | Groq gpt-oss-120b |
|---|---|---|
| Correct | 8 | 14 |
| Wrong answer shown | 3 | 0 |
| Refused after the verifier rejected a wrong answer | 3 | 0 |

## 5. Known failures and limits

**Wrong answers the shipped system still gives,** with a valid citation and no warning (both judges grade them incorrect):

| Id | Question | Answer | Actual | Why it gets through |
|---|---|---|---|---|
| E36 | Tesla energy storage, Q3 2023 | 3.0 GWh | 3,980 MWh | "3.0" matches a stray "3" in legal boilerplate |
| E40 | JPMorgan reported net revenue, Q1 2022 | $31.6B | $30,717M | that's the managed figure; the verifier can't tell |
| E42 | NVIDIA non-GAAP net income, Q2 FY2025 | $9,453M | $16,952M | a continuation chunk lost its date headers |

**Refused, though answerable (the verifier rejected a wrong answer):** E29 (Tesla production, Q1 2024), E37 (capex, Q4 2024), E38 (AWS, Q2 2024).

**Other limits:**
- The column check gets no verdict on 52% of release tables (1,484 of 2,849). A year-to-date figure can pass as its quarter's. It covers earnings releases only.
- The verifier checks figures, not meaning, so 10-K answers can still have a wrong direction, year or label. That's what the judge measures.
- Tesla FY2022 Q1 to FY2023 Q1: statements exist only as images, so prose only. Later releases show some of those quarters as comparatives, which a quarter-filtered search doesn't reach, so EU1 and EU2 are "unanswerable" only under that filter.
- JPMorgan: Exhibit 99.1 is the narrative; full statements are in Exhibit 99.2, not downloaded. Annual revenue isn't in its release.
- Cross-company fiscal quarters may be different calendar quarters (NVDA vs MSFT "Q2 FY2025"), and answers don't always say so.
- Multi-year quarterly questions (16+ sub-queries) exceed the 12-source cap, so quarters can drop. Not tested live.
- A release citation names the release, not a place in it; the link opens the whole exhibit.
- E15 and E27 miss the citation metric though correct. Not diagnosed.
- `run_judge_eval` runs aren't traced, so they show on the dashboard under tokens and logs, not under turns.

**How much to trust the scores:**
- Questions and labels were written by Claude Code, the assistant that built the system, and checked in code against the text. No independent reviewer has looked at them. The 22 hand labels in `data/eval/judge_labels_v0.jsonl` are in the same position; an owner review takes about 5 minutes.
- Labels were changed after results were seen: citation quotes widened (0.741 -> 0.926 at the time), and E15's reference corrected. Each change was checked in the text, but the review wasn't blind.
- Gate floors for earnings were lowered when harder questions arrived. They sit just below today's numbers, so they accept the wrong answers above.
- A judge grading its own model's answers is biased: read qwen on routed runs.

## 6. Running it

Machines: MacBook M4 (active, Python 3.11.14 at `.venv/bin/python`, MPS, Docker 29, Node 24, ~100 GB free) and a Windows laptop (CPU only, `.venv/Scripts/python`, no Docker, needs its own `.env`). `CLAUDE.md` has the table. Ollama models here: `granite4.1:3b` (used) and `nomic-embed-text` (unused).

**Setup** (data is gitignored and reproducible; `.env` needs a real `SEC_USER_AGENT`):
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install torch                     # Windows: --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env
python -m app.ingestion.sec_downloader --years 2022 2023 2024 2025        # 40 filings, ~1-2 min
python -m app.ingestion.pipeline                                          # ~1 min
python -m app.agent.xbrl --download                                       # ~45 MB
python -m app.ingestion.earnings_downloader --years 2022 2023 2024 2025   # 160 releases, ~3 min
python -m app.ingestion.earnings_pipeline                                 # ~7 s
python -m app.retrieval.build_index                                       # embeddings; only new chunks are embedded
ollama pull granite4.1:3b                                                 # or set a free GROQ_API_KEY
python -m pytest
```

**Ports:** API + UI 8010 (8000 is taken on the MacBook), Vite 5173, dashboard 8020, Postgres 5433 (host), all bound to localhost.

| Task | Command |
|---|---|
| App | `cd frontend && npm install && npm run build && cd ..`, then `uvicorn app.api.main:app --port 8010` |
| UI hot reload | `cd frontend && npm run dev` (API on :8010) |
| Dashboard | `python -m app.dashboard --log <file>`; stop with `pkill -f app.dashboard` |
| Docker | `docker compose up -d db && python -m app.retrieval.pg_store`, then `docker compose up --build`; `docker compose down` when done |
| Conversation in the terminal | `python -m app.agent.graph --route "Q1" "follow-up"` |
| Search | `python -m app.retrieval.search_cli "query" --tickers V --years 2025` |
| Find evidence for a label | `python -m app.evaluation.find_evidence "phrase" --tickers AAPL --years 2025` (10-K pages only) |
| Screenshot | `python scripts/ui_screenshot.py URL out.png WIDTH HEIGHT SELECTOR` |
| Postgres tests | `createdb -U finrag finrag_test` in the container, then `PG_TEST_DSN=postgresql://finrag:finrag@localhost:5433/finrag_test python -m pytest tests/test_pg_store.py`. **Never point this at the main db: the load replaces the table.** If a stale table has other dimensions: `DROP TABLE chunks` in `finrag_test` |

## 7. Configuration

Settings are in `app/config.py`, read from `.env` (gitignored; keys never go in `.env.example`, which is tracked).

| Variable | Default | Notes |
|---|---|---|
| `SEC_USER_AGENT` | placeholder | Required by SEC: name and contact email |
| `LLM_PROVIDERS` | `ollama,groq,gemini` | Tried in order |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | unset | Both set on the MacBook |
| `OLLAMA_MODEL`, `OLLAMA_BASE_URL` | `granite4.1:3b`, `localhost:11434` | `num_ctx` 8192, `num_predict` 1500 |
| `GROQ_MODEL`, `GEMINI_MODEL` | `openai/gpt-oss-120b`, `gemini-3.8-flash` | |
| `CONTEXT_TOKEN_BUDGET` | 3500 | Tokens of sources per prompt, the main token lever |
| `ANSWER_ROUTE` | true | Trend and comparison to Groq, in the API |
| `ANSWER_ROUTE_RELEASES` | **false** | Earnings questions to Groq too; off until its full eval |
| `VECTOR_BACKEND` | `faiss` | Or `pgvector` |
| `DATABASE_URL` | `...localhost:5433/finrag` | Dev password `finrag`; localhost only |
| `DEVICE` | `auto` | mps, cuda or cpu. `cpu` is refused on macOS |
| `EMBEDDING_MODEL`, `RERANKER_MODEL` | `BAAI/bge-small-en-v1.5`, `BAAI/bge-reranker-base` | Local; 512-token limit drives chunk size |
| `TRACE_FILE` | unset | `.env` here sets `data/traces/app.jsonl` |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | unset | Optional. The owner chose the local dashboard instead |
| `LLM_TIMEOUT_S` | 90 | |

### Models and quotas

| Use | Model | Limits and cost |
|---|---|---|
| Embeddings, reranker | bge-small-en-v1.5, bge-reranker-base | Local. 30 rerank candidates per sub-query |
| Answers, default | granite4.1:3b (Ollama) | Local, ~15-20 s |
| Trend and comparison answers | gpt-oss-120b (Groq) | Free: ~8k tokens/min, ~200k tokens/day (observed, not in headers; a day reached ~215k), ~1k requests/day. Limits are per model |
| Second judge | qwen/qwen3.8-27b (Groq) | Its own quota. JSON mode sometimes fails with HTTP 400 |
| Gemini | gemini-3.8-flash | Slow and unreliable (503s, timeouts): last resort only, dropped as a judge |

Token use: ~3.3k per local answer, ~3.6-4.1k per routed answer (92% is input), ~1.6k per judge call, ~5k per question for RAGAS. About 55 routed questions a day fit the free tier, then calls **silently** fall back to Ollama: check a report's "Answers by" line. Every successful call is cached in `data/cache/llm` (key: provider, model, messages, schema), so repeat runs are free, and a killed run resumes. **Any change to a prompt invalidates its cached answers.**

## 8. Code map

```
app/config.py            settings
app/devices.py           device choice; refuses torch CPU + FAISS on macOS
app/tracing.py           per-turn traces in a contextvar; JSONL and Langfuse sinks; `python -m app.tracing <file>`
app/dashboard.py, .html  local dashboard (no models, localhost only)

app/ingestion/
  companies.py           the 10 companies (CIK, fiscal-year end)
  sec_downloader.py      10-K download, manifest, User-Agent and rate limit
  earnings_downloader.py 8-K Ex-99.1 download; maps releases to fiscal quarters; picks the real release
  html_parser.py         HTML -> page-aware blocks; strips EDGAR's SGML wrapper; page labels, furniture
  tables.py              cleans tables, renders Markdown
  sections.py            10-K Items; one "Earnings release" section with heading subsections
  chunker.py             section-aware chunks, tables whole or split with repeated headers
  models.py              Block, Page, FilingMeta, Chunk
  tokens.py              embedding-tokenizer token counts
  pipeline.py            10-K: chunks.jsonl, pages.jsonl, quality report
  earnings_pipeline.py   releases: chunks_earnings.jsonl, quality report; Tesla slide handling

app/retrieval/
  types.py               SearchFilters, effective_forms (the 10-K default), result types
  store.py               ChunkStore, filter masks, from_processed (10-Ks first)
  embedder.py            sentence-transformers + cache keyed by chunk id + text hash
  build_index.py         embeds whatever isn't cached
  dense.py               exact FAISS IndexFlatIP with ID selector
  pg_store.py            Postgres + pgvector backend and loader
  bm25.py                finance tokenizer, BM25Index, PartitionedBM25 (one index per form)
  hybrid.py              reciprocal rank fusion
  retriever.py           orchestration, batched rerank
  decompose.py           split_filters (company x year x quarter), interleave
  factory.py             build_retriever
  search_cli.py, smoke.py, index_benchmark.py

app/reranking/cross_encoder.py

app/agent/
  entities.py            rules: tickers, years, sections, quarters, guidance, period dates, fiscal_period_of
  analyze.py             QueryAnalyzer: filters, scope, follow-up rewrite and carry-over
  plan.py                intent, sub-queries, quotas, MD&A prior, execute_plan
  xbrl.py                company facts, 13 metrics, own-filing selection, series tables, detect_metrics
  graph.py               LangGraph agent, ConversationMemory, merge_filters, routing, build_agent

app/generation/
  llm.py                 providers, cache, retries, rate limiter, fallback
  schemas.py             Claim, GeneratedAnswer
  context.py             Source: prompt rendering and citations
  answer.py              prompts and rules, Answerer, generate and finalize
  verify.py              figure matching, citation repair, release checks
  columns.py             reads a release table's column periods
  ask_cli.py

app/evaluation/
  golden.py, metrics.py, build_golden.py, find_evidence.py     sets and scoring
  run_retrieval_eval.py, run_plan_eval.py, run_analyzer_eval.py, run_xbrl_eval.py, run_generation_eval.py, run_agent_eval.py
  judge.py, run_judge_eval.py, compare_judges.py, run_judge_sensitivity.py
  ragas_metrics.py, run_ragas_eval.py
  build_eval_report.py   generates reports/eval_v1.md
  check_gate.py          the CI gate, standard library only

app/api/main.py, schemas.py   FastAPI
app/agents/                   empty leftover package, safe to delete
frontend/src/                 App.tsx, api.ts, filters.ts, brand.ts, text.ts, components/{AnswerPanel,EvidenceCard,Filters,Aurora,Icons}.tsx
scripts/ui_screenshot.py      headless Chrome screenshot once a selector exists
scripts/audits/               column_claims.py, cross_release_columns.py, table_questions_larger_model.py
tests/                        one file per area; fakes and fixtures, no data, keys or network needed
```

## 9. How the important parts work

**Ingestion.** Filings come from SEC EDGAR HTML, not PDFs: stable URLs, structured tables, exact page breaks. Fiscal year is the year of the period end (NVDA FY2025 ended January 2025). Original 10-Ks only. Chunks never cross an Item, target 320 tokens, max 420 plus a context header, under the 512-token limit. 10-K: 17,602 chunks (14,975 text, 2,627 table). Releases: 5,571 (2,722 text, 2,849 table). Total 23,173. Pages: 4,826.

**Earnings releases.**
- An 8-K's `reportDate` is the announcement date, so the quarter comes from the company's own 10-Q/10-K period ends. Item 2.02 isn't only earnings (Tesla deliveries, NVIDIA's pre-announcement, an Alphabet blog post), so candidates are ranked and the first with an income statement wins.
- Exhibits are stored with an SGML wrapper that collapses a page into one block unless stripped.
- Tesla's exhibits are slide images over a hidden text layer: `normalize_slides` restores letter-spaced titles, splits flat statements into rows, and repeats the period header on every piece.
- Release chunks: `fiscal_quarter` set, page 0 and no labels (like XBRL facts, so they can't match a 10-K gold page), section "Earnings release".

**Retrieval.** Dense + BM25 -> RRF -> cross-encoder on the top 30. Exact search is deliberate: the benchmark in `docs/ARCHITECTURE.md` shows ANN saves ~0.3 ms of 1,500 ms and loses recall under filters; HNSW in pgvector past ~1M vectors. Filters: ticker, year, section, chunk type, quarter, form.
- **The 10-K is the default corpus.** `effective_forms()`: explicit forms, else releases if a quarter is set, else 10-K. `ChunkStore.mask` and `filter_sql` must stay in step.
- **One BM25 index per form:** IDF is a corpus statistic, so one index would let releases change every 10-K score, the cached answers and the baselines.
- **Plan:** one sub-query per company x year x quarter, quotas, round-robin interleave, a +0.05 soft MD&A prior on metric questions, 15 rerank candidates past 8 sub-queries when quarters are involved. Up to 12 text sources.

**Analyzer rules** (`entities.py`). Reads Q3, 3Q24, Q3'24, FY25, "third-quarter". "Quarterly revenue" and "each quarter" mean all four; "quarterly dividend" stays 10-K. "Three months ended <date>" converts with the fiscal calendar (a period ending in a month's first week counts for the month before). Release questions drop 10-K sections. Follow-ups keep the quarter. Refused early: years outside the corpus, and live market data.
- **Guidance searches only the previous quarter's release** (Q1's in the prior year's Q4). The quarter's own release states the *next* quarter's outlook, and searching both gave a wrong figure the verifier passed.

**XBRL.** Annual facts from the fiscal year's own 10-K (accession + period end + ~1-year duration, never the `fy` field), next to retrieved text, never instead of it: the filing text wins on definitions (Meta capex, Amazon cash capex, Apple buybacks differ from the GAAP line). 459 of 520 cells; the gaps are real absences. **Skipped on quarterly questions:** an annual total there is a wrong answer.

**Generation.** Structured JSON with `[S#]` markers, rendered to citations afterwards. `SYSTEM_PROMPT` stays fixed. These are appended only when relevant, so other prompts and their cache stay byte-identical: `XBRL_RULE`, `INTENT_RULES`, `RELEASE_RULE`, `QUARTERLY_TREND_RULE`. Repeated release citations collapse; 10-K answer text doesn't change.

**Verifier** (`verify.py`, `columns.py`). A claim is supported when it cites a provided source containing its figures, matched by value across units and rounding. Citation repair re-attributes a claim only when its figure sits next to its words in another provided source; invented figures are never rescued. Nothing verified means abstain. Release sources only, in addition:
- **Column check:** the figure must sit in the column of the period the claim names, or the release's own quarter if it names none. No verdict on percentages, small plain integers ("Model 3"), or claims about another period on purpose ("a year ago"). **A wrong column outweighs a table it can't read,** and citation repair must pass the same check.
- **Count on dollars:** "69,138 million iPhone units" can't rest on a dollar row, or a money table's row naming nothing counted.
- **Combined figures:** "Model Y" can't claim a "Model 3/Y" row. **Chart axes** aren't evidence.

**Memory.** An explicit per-thread turn list (last 6 exchanges, LRU over 1,000 threads) passed into a stateless graph, not a LangGraph checkpointer. A question naming its own company and year with no back-reference skips the LLM rewrite.

**API.** `GET /api/health`, `GET /api/meta`, `POST /api/search`, `POST /api/answer`, `POST /api/answer/stream` (SSE, one event per node; not token streaming, because answers are shown only after verification). UI filters override the analyzer field by field; scope refusals still come from the question. `/api/search` reads a quarter and year from the query so evidence matches the answer.

**UI.** React + Vite + TypeScript with hand-written glassmorphism CSS (the owner's choice over Streamlit). Filters, evidence cards, citation chips, live agent stages, URL state, phone layout. FastAPI serves `frontend/dist` at `/`.

**Dashboard.** A separate process that loads no models. Tokens come from the LLM cache files (a file's modified time is the call's time), so all history is covered with no tracing; failed calls and cache hits aren't counted, and copying the cache to another machine resets the dates. Logs: `--log` files and `data/logs/*.log`, by name from that list only. Daily limits shown are approximate, over a rolling 24 h. Remaining quota is only in the Groq console.

**Docker.** Multi-stage image (2.13 GB): CPU torch, no RAGAS or pytest. API + UI + pgvector; Ollama stays on the host. First start ~5 min (models), then ~20 s. A reranked search takes ~5 s on CPU in Docker vs ~1.5 s on Apple GPU, so native is the fast path.

**CI** (`.github/workflows/ci.yml`, no secrets): `test` (Python 3.11, CPU torch, pgvector service), `frontend` (Node 24, lint, build), `eval-gate`.

## 10. Evaluation

| Set | File | Contents |
|---|---|---|
| 10-K | `data/eval/golden_v0.jsonl` | 84 questions: lookup, numeric, trend, comparison, follow-up, 10 unanswerable. Page-level, quote-verified |
| Earnings | `data/eval/golden_earnings_v0.jsonl` | 60: numeric 30, lookup 7, trend 4, comparison 3, follow-up 2, unanswerable 14. Ids E01-E46, EU1-EU14. Tags include `table-reading`, `flat-table`, `guidance`, `date-form`, `near-miss`, `added-after-verifier-fix` |
| Hand labels | `data/eval/judge_labels_v0.jsonl` | 22 10-K answers, to validate the judge (0.86 exact, 1.00 correct vs not) |

Relevance: 10-K evidence by page; release evidence by quarter plus a quote in the chunk (`metrics._covers`). Validate with `python -m app.evaluation.build_golden --path <file>`. Write labels from a text search, never from the retriever.

**The gate reads committed reports, not fresh runs** (CI has no filings, models or quota). A change to retrieval or answers must regenerate the affected reports in the same commit, and they must be committed together with the code, or CI won't catch it or will fail.

**Gate** (`reports/gate.json`, `python -m app.evaluation.check_gate`):

| Check | Today | Floor |
|---|---|---|
| Retrieval recall@5 / MRR | 0.891 / 0.933 | >= 0.87 / 0.90 |
| Plan recall@10 / MRR | 0.966 / 0.927 | >= 0.95 / 0.91 |
| Agent false abstention | 0.041 | <= 0.06 |
| Agent abstention recall | 1.000 | >= 0.95 |
| Agent claim support | 0.965 | >= 0.94 |
| Agent citation hit incl. XBRL | 0.878 | >= 0.85 |
| Judged correctness, gpt-oss / qwen | 0.865 / 0.865 | >= 0.84 / 0.84 |
| Earnings retrieval recall@5 / MRR | 0.886 / 0.699 | >= 0.85 / 0.66 |
| Earnings plan recall@10 | 1.000 | >= 0.96 |
| Earnings false abstention | 0.065 | <= 0.09 |
| Earnings abstention recall | 1.000 | >= 0.90 |
| Earnings claim support | 0.984 | >= 0.94 |
| Earnings citation hit | 0.848 | >= 0.80 |
| Earnings correctness, gpt-oss / qwen | 0.870 / 0.867 | >= 0.83 / 0.83 |
| Judge catches deliberately wrong answers | 1.000 | >= 0.80 |

**Regenerating reports.** Check quota first; cached answers are free.

```bash
G=data/eval/golden_earnings_v0.jsonl
# Earnings
python -m app.evaluation.run_retrieval_eval --golden $G --no-ablations --out reports/retrieval_earnings_v0
python -m app.evaluation.run_plan_eval --golden $G --out reports/plan_earnings_v0
python -m app.evaluation.run_agent_eval --golden $G --configs agent_routed --out reports/agent_earnings_v0
python -m app.evaluation.run_judge_eval --golden $G --route --out reports/judge_earnings_v0
python -m app.evaluation.run_judge_eval --golden $G --route --judge-providers groq --judge-model qwen/qwen3.8-27b --out reports/judge_earnings_v0_qwen
python -m app.evaluation.run_judge_sensitivity
python -m app.evaluation.run_judge_sensitivity --judge-model qwen/qwen3.8-27b --out reports/judge_sensitivity_qwen
# 10-K
python -m app.evaluation.run_retrieval_eval                     # ~20 min; --no-ablations ~8 min
python -m app.evaluation.run_agent_eval --configs agent_routed --out reports/agent_v2     # ~5.5 min from cache
python -m app.evaluation.run_judge_eval --route --out reports/judge_v2
python -m app.evaluation.build_eval_report                      # reports/eval_v1.md
# Audits (no LLM)
PYTHONPATH=. python scripts/audits/column_claims.py
PYTHONPATH=. python scripts/audits/cross_release_columns.py     # read the "one value per release" line, not the first
```

**The regression check.** After touching retrieval, prompts or the verifier, run the 10-K agent eval to a scratch path and compare answers with `reports/agent_v2.json`: it must stay 84 of 84 with no LLM calls. Release-only changes should never move it.

**Column check audits** (the numbers in the earnings report): 1,365 of 2,849 tables readable across all 10 companies; 21,785 of 21,785 right-column claims accepted; 64,493 of 64,528 wrong-column claims rejected (the misses repeat a figure in another column). Cross-release agreement: 2,279 of 2,298 rows (99.2%) among rows with one value per release; the disagreements seen were restatements and stock splits. The first line that script prints (59.2%) counts rows that repeat under one name within a release, such as Amazon's per-segment "net sales", and isn't a column error.

**Reports** (`reports/`): `eval_v1`, `eval_earnings_v0` are the summaries. Others: `retrieval_v0/v1`, `plan_v0`, `analyzer_v0`, `xbrl_v0`, `generation_v0_ollama(_repair)`, `generation_v1_ollama/groq`, `agent_v0/v1/v2`, `judge_v0/v1/v1_strict/v1_qwen/v2/v2_qwen`, `judge_agreement_v1/v2`, `ragas_v0`, `index_benchmark`, plus the `*_earnings_v0` and `judge_sensitivity*` files.

## 11. Decisions and rejected experiments

Don't redo these without new evidence.

| Tried or chosen | Outcome |
|---|---|
| Prompt "never compute a percentage the sources don't state" | Rejected: 6 more abstentions, trend 0.542 -> 0.375. Prohibitions push a small model to abstain |
| Release prompt rule "report a figure only as the metric its source names" | Rejected: wrong answers unchanged, 9 others shifted, E25 lost its calendar note. Fixed in code instead |
| RAGAS factual correctness | Rejected as the metric: too literal ("$26,914 million" isn't "$26.91B"). Faithfulness agrees with the judge (Spearman 0.86) |
| Gemini as main LLM or judge | Dropped: slow, 503s and timeouts |
| Langfuse SDK | Not used: the HTTP API is small and the SDK pulls in OpenTelemetry. Langfuse keys remain optional |
| Langfuse vs local dashboard | The owner chose local |
| LangGraph checkpointer | Not used: stores every step's chunks and warns on custom dataclasses |
| ANN index | Not used: see `docs/ARCHITECTURE.md`, "Vector index choice" |
| Investor presentations (PDF) | Left out by the owner: most aren't on EDGAR |
| One BM25 index over both forms | Not used: would change every 10-K score |
| Streamlit | Not used: the owner wanted a glassmorphism UI |
| More verifier patches for E36 and E42 | Stopped on purpose: whack-a-mole on a model problem |
| Hand labels for earnings answers | Skipped when all answers were correct, since agreement would say nothing; deliberately wrong answers tested the judge instead |

## 12. What to do next (all optional)

**1. Earnings questions on the larger model** (recommended; it's the only item that fixes wrong answers users see):
1. Check quota on the dashboard. It needs ~90k gpt-oss tokens for ~25 new answers (the 14 table questions and 7 routed ones are cached), plus judge calls. Spread over two days if needed.
2. `python -m app.evaluation.run_agent_eval --golden data/eval/golden_earnings_v0.jsonl --configs agent_routed_releases --out reports/agent_earnings_v1`
3. `run_judge_eval --golden ... --route --route-releases --out reports/judge_earnings_v1`, and again with `--judge-providers groq --judge-model qwen/qwen3.8-27b --out reports/judge_earnings_v1_qwen`
4. Check the "Answers by" line for fallback, read qwen's verdict, and try fresh questions by hand: **fresh questions found every failure so far.**
5. If it holds: set `answer_route_releases` to true, point the gate at v1, raise its floors, update the README.

**2. A harder golden set:** "why" questions on the earnings side, and a reviewer other than the author.

**3. Column check coverage:** the 52% of unread tables; continuation chunks losing date headers (E42) would need a chunker change, which changes chunk ids and embeddings for those chunks, so plan for a rerun.

**4. Fewer tokens:** input is 92%, so the context budget is the lever. Measure `run_plan_eval`'s ctx recall at 2,000-3,000 tokens first, with no LLM calls. Real answers on both sets would cost ~300k tokens, and a change invalidates baselines. A smaller budget saves ~1,000 tokens per answer. Judging with one model is the cheapest eval saving.

**5. Data gaps:** local OCR for Tesla's image-only quarters; JPMorgan's Exhibit 99.2.

**Portfolio:** add the screenshot, then stop. If asked in an interview, the honest position is that the project was built with Claude Code, the owner directed it and should be able to explain its design, and the labels were AI-generated, checked in code, and not independently reviewed. Don't describe the golden sets as written by hand.

## 13. Gotchas

- **Silent fallback:** a routed run past quota continues on Ollama and produces a mixed report. Look at "Answers by". One outage once did this to 5 questions.
- **macOS: torch on CPU + FAISS in one process crashes or deadlocks** (each bundles `libomp`). `build_retriever` refuses `DEVICE=cpu` on macOS. Fine on MPS, Windows and Linux.
- **Long runs:** plug in and use `caffeinate -i`. A sleeping Mac stalled a generation for 15+ minutes. Windows throttles background jobs on battery: `Get-Process python | ? WorkingSet64 -gt 100MB | % { $_.PriorityClass = 'AboveNormal' }`.
- **Ollama:** small models under a JSON grammar sometimes never close the object, hence `num_predict`=1500.
- **Groq's daily cap** isn't in response headers; a daily-limit 429 fails over at once. Three per-minute 429s in a row give up, and rerunning fills the gap from cache. A first uncached call once hung with 0% CPU for 10+ minutes.
- **`python -m` must run from the repo root,** or `app` isn't found.
- **pgvector:** `load` won't change an existing table's dimensions, and `load_chunks` on an old table raises a message asking for a reload. Stop the API before evals: it holds models in memory.
- **Headless Chrome:** `--screenshot` fires before fetches settle and `--virtual-time-budget` hangs on this page, so use `scripts/ui_screenshot.py`.
- **Docker:** stop the host API first (port 8010). `docker compose down` keeps volumes `finrag_pgdata` and `finrag_hfcache`.
- **A test relied on a tie once** and failed only on CI's x86 runners; make fake reranker fixtures strict.
- **Keys:** they were once pasted into the tracked `.env.example` and moved before any commit. `.env` is chmod 600 on the MacBook. Never commit it; a Windows laptop needs its own.
- **GitHub push:** `gh` over HTTPS works on the MacBook (`gh auth setup-git`); the SSH key isn't registered. `gh` isn't installed on Windows.
- **What's gitignored:** `.env`, `data/raw`, `data/processed`, `data/indexes`, `data/cache`, `data/traces`, `data/logs`. `data/eval` and `reports/` are committed. Sizes here: raw 264 MB, processed 59 MB, indexes 35 MB, cache 4 MB (~1,100 calls, not reproducible without spending quota again).

## 14. Stale docs

These older notes haven't been brought up to date:
- `CLAUDE.md` opens with "over SEC 10-K filings" and suggests qwen/llama models; the project now covers releases and uses granite4.1:3b.
- `progress.md`, "Zero-cost stack": says Gemini is the main LLM and lists multimodal plans. Actual: Ollama first, Groq next, Gemini last, no multimodal.
- `progress.md`, "Environment notes": says no Ollama and no commits, both long out of date. Its dated sections are correct for their date; "Earnings evaluation v0" holds 35-question numbers, superseded by "Column check v0".
- `docs/ARCHITECTURE.md`'s pipeline and evaluation sections describe the 10-K flow; the earnings design is in its decisions table and `reports/eval_earnings_v0.md`. Its "Answer in one breath" numbers are for 17.6k vectors.
- `README.md` Phase rows quote the numbers of their time.

## 15. Links

- Repo: https://github.com/Mayanksingh2518/finrag (branch `main`)
- SEC EDGAR access rules: https://www.sec.gov/os/accessing-edgar-data
- Groq keys and quota: https://console.groq.com
