# FinRAG Progress

Single source of truth for project state. Update this file at the end of every work session.

## Current status

- **Phase 8 done 2026-10-30:** `/api/answer` runs the routed agent; `/api/answer/stream` sends a
  Server-Sent Event per agent node, and the UI shows the stages live (reading → retrieving + XBRL →
  generating with <model> → verifying) with a fallback to the plain endpoint.
- **Last completed:** Phase 9 (production), 2026-10-30. Postgres + pgvector backend (identical to
  FAISS, 740/740); `docker compose up --build` (API + UI + Postgres); GitHub Actions CI green
  (run 41048182690: 209 tests incl. real Postgres, frontend lint + build, eval gate 10/10). CI badge in
  the README.
- **In progress:** Phase 10: earnings releases are built and evaluated (`reports/eval_earnings_v0.md`, 47 questions: correctness 0.970, abstention
  recall 1.000). Known gap: an answer can take the wrong period column (E29). Investor presentations not started, so the phase stays unticked.
- **Next up:** a column check in the verifier. See "Next task in detail".
- **Resume here (2026-11-02):** step 5 is uncommitted in the working tree, along with parts of step 4; the user commits. The dashboard may still be running
  on :8020 (`pkill -f app.dashboard`). Main Postgres volume: still needs `python -m app.retrieval.pg_store` with `VECTOR_BACKEND=pgvector`.
- **Retrieval v1 (2026-10-30):** full retrieval eval rerun with the reviewed gold labels
  (`reports/retrieval_v1`, ~20 min): hybrid_rerank recall@5 0.891, MRR 0.933 (gold filters), 0.884 /
  0.925 (none); reranker ablations unchanged in ranking (bge-reranker-base 30 cand / 512 still best).
  The gate and `eval_v1` now read retrieval_v1; eval_v1's prose numbers are computed from the report.
- **Disk (MacBook, 2026-10-27):** 127 GB free again (was 2.2 GB on 2026-10-26).
- **Disk/memory warning (MacBook, 16 GB RAM):** the disk once filled because swap grew to 10 GB
  while the API server, an eval, tests and Ollama all held models at once. Run one model-loading
  process at a time and stop the API server during evals.
- **Active machine:** MacBook M4 (setup done 2026-10-07: venv, data, embedding cache)
- **Last updated:** 2026-11-02 (Phase 10 step 5: relabelled-figure checks; golden set extended to 47)

## Phase checklist

- [x] **Phase 1: Data acquisition.** EDGAR 10-K downloader, 40 filings (10 companies × FY2022–2025), manifest
- [x] **Phase 2: Parsing and chunking.** 17,602 chunks (14,975 text / 2,627 table), 0 over the 512-token limit, all core items found in all 40 filings, 96.8% of chunks carry a printed page number
- [x] **Phase 3: Indexing and retrieval.** Local bge-small embeddings + FAISS, BM25, RRF hybrid, metadata filters, bge-reranker-base cross-encoder; 12/12 smoke queries in all 4 modes; 33 tests
- [x] **Phase 4: Evaluation v0.** 84-question golden set (quote-verified pages), Recall@K / MRR / nDCG, 4 modes × filters on/off, reranker ablations, decomposition preview; hybrid_rerank recall@5 0.884, MRR 0.920; 48 tests
- [x] **Phase 5: Grounded generation.** Structured output, page citations, citation verifier with context-checked repair, abstention, confidence; Ollama granite4.1:3b false abstention 0.054, citation hit 0.863, abstention recall 1.000; Groq gpt-oss-120b false abstention 0.014, citation hit 0.959 (84 q); 92 tests
- [x] **Phase 6: LangGraph agent.** Rule-based analyzer + LLM follow-up rewrite, retrieval plan (quotas, MD&A prior), XBRL company-facts tool, LangGraph graph with memory and a widen retry; agent with no gold filters: false abstention 0.054 (= gold-filter run), citation hit incl. XBRL 0.878, figure recall 0.573; 158 tests
- [x] **Phase 7: Full evaluation.** LLM judge validated on hand labels (0.86-1.00) and by a second judge family (0.94); trend fixes + routing trend/comparison to gpt-oss-120b: judged correctness 0.730 → 0.865 (trend 0.792, comparison 1.000); RAGAS corroborates faithfulness (Spearman 0.86), rejected for correctness; tracing (JSONL + Langfuse) with per-node p50/p95; vector index benchmark; summary `reports/eval_v1.md`; 189 tests
- [x] **Phase 8: Serving.** FastAPI + React/Vite glassmorphism UI (user's choice over Streamlit): search with filters, citations, tables, latency; answers from the routed LangGraph agent (UI filters as per-field overrides, XBRL facts as sources, per-thread memory, traces) streamed as per-node progress events (SSE) with a plain-endpoint fallback; read-as line, intent/model/steps pills; 195 tests
- [x] **Phase 9: Production.** Postgres + pgvector backend (identical retrieval to FAISS, `VECTOR_BACKEND=pgvector`), Docker Compose (API + UI + Postgres; CPU torch, host Ollama), GitHub Actions CI (tests with a pgvector service, UI lint/build, eval regression gate over committed reports); retrieval eval refreshed with the reviewed gold (v1: recall@5 0.891, MRR 0.933); 209 tests
- [ ] **Phase 10: Expansion.** Earnings releases (8-K Ex-99.1), investor presentations (PDF parser)

## Next task in detail: Phase 10 (expansion: earnings releases)

Goal: answer questions about quarterly results ("What did NVIDIA report for Q3 FY2025 data center
revenue?", "How did Apple's quarterly revenue trend in fiscal 2025?") from earnings press releases,
with the same citations, verification and abstention. Zero cost: SEC EDGAR only (earnings releases are
filed as 8-K Exhibit 99.1, Item 2.02; stable URLs, same User-Agent rule as Phase 1).

1. ~~Downloader~~ **done 2026-10-30** (see "Earnings releases v0" below).
2. ~~Parse + chunk~~ **done 2026-11-02** (see "Earnings release chunks v0" below).
3. ~~Retrieval + analyzer~~ **done 2026-11-02** (see "Earnings release retrieval v0" below).
4. ~~Golden set extension~~ **done 2026-11-02** (see "Earnings evaluation v0" below).
5. ~~Metric-relabelling answers~~ **done 2026-11-02** (see "Relabelled figures v0" below).
6. **Column check in `verify.py` (next "go").** E29: "Tesla produced 440,808 vehicles in Q1 2024" takes the year-ago column of a five-quarter row; the verifier passes it because the
   figure is in the source. For release sources, read the period header of a table or flat row, find the column of the quarter the claim names, and reject a figure that
   matches only another column. Flat Tesla rows repeat a header on every piece (`Q1-2023 ... Q1-2024 YoY`), so start there, then Markdown tables (`Q3 FY25 | Q2 FY25 | Q3 FY24`). Beware
   claims that name the other period on purpose ("up from 18,120 a year ago"), rows with a footnote, tables with quarter and year-to-date columns, and answers that
   name no period (use the chunk's quarter only if the plan asked for one quarter). Keep it only if E29 improves with no false abstentions on the golden set (cached, no LLM calls) and 84/84 on the 10-K set.
   Also tighten the count check: `| Mac | 7,949 |` has no `$` on its row, and "sold N iPads" isn't a listed noun. Test with fresh questions, not only the golden set; that's what found E29.
7. **Then ask the user** about investor presentations (PDF parser; most aren't on EDGAR), or closing Phase 10 without them. Also open: a free
   context-budget test (the user asked how to reduce tokens): `run_plan_eval`'s ctx recall at 2,000-3,000 tokens needs no LLM; only run real
   answers at the best budget, since it would cost ~300k tokens across both golden sets.

## Relabelled figures v0 (Phase 10 step 5, MacBook M4, 2026-11-02)

`verify.py`, release sources only (`_row_fits`, `_relabelled`; also applied in citation repair): a figure stated as a count ("69,138 million iPhone units") can't rest on a row where it has
a `$`, and one product can't claim a combined row ("Model Y" on `Model 3/Y deliveries`). A prompt rule had failed first (step 4). EU6 and EU7 now abstain, no false abstentions, 10-K answers 84/84 identical.

**Fresh questions found a new failure.** 12 questions written after the fix (6 answerable, 6 not, now in the golden set, tag `added-after-verifier-fix`): 6 of 6 refused and 5 of 6 answered correctly, but
**E29 "Tesla produced 440,808 vehicles in Q1 2024" (high confidence) is the year-ago column; the answer is 433,371**. Both judges graded it incorrect. The set had scored 1.000 only because its traps
happened to pass. Limits of the new checks: Mac and iPad were refused for other reasons (wrong source; no citation), since `| Mac | 7,949 |` has no `$` on its row and "iPads" isn't a listed noun.

Now, 47 questions: correctness 0.970 / 0.969 (qwen 32 graded, E33 JSON 400), abstention recall 14/14, false abstention 0/33, citation hit 0.939, retrieval 0.932 / 0.823, plan recall@10 1.000. Abstention floor in the gate raised to 0.90. The "Earnings evaluation v0" numbers below are from the 35-question stage.

## Earnings evaluation v0 (Phase 10 step 4, MacBook M4, 2026-11-02)

Summary for readers: `reports/eval_earnings_v0.md`. `data/eval/golden_earnings_v0.jsonl`: 35 questions (27 answerable, 8 not), written from
grep over release text, never from the retriever. Release evidence has no pages: `GoldEvidence.fiscal_quarter`, and a chunk covers an item when it is
from that release and contains a quote (`metrics._covers`, `validate_release_quotes`). `filters_ok` now also checks quarter and document type. 10-K
matching is unchanged. `check_gate`: `retrieval@<report>:` and `plan@<report>:` read other reports; 10 new checks, 20/20 pass.

| Metric | Result |
|---|---|
| False abstention | 0 / 27 |
| Abstention recall | **0.75** (EU6, EU7 answered) |
| Judged correctness | 1.000 gpt-oss (27); 1.000 qwen (25, E14 and E17 failed with Groq JSON 400) |
| Filters correct | 27 / 27 |
| Citation hit / evidence recall | 0.926 / 0.926 (0.741 / 0.704 before widening quotes) |
| Retrieval recall@5 / MRR (gold filters) | 0.917 / 0.826 |
| Plan recall@10 / ctx recall | 1.000 / 1.000 |
| Uncached p50 / p95 | 20.9 s / 46.1 s (first run; the final report came from cache, so it shows none) |

Reading:
- **1.000 is not better than the 10-K set's 0.865.** These are mostly stated figures with no "why" questions, by one author. Traps passed on these
  questions (JPM reported vs adjusted, comparative columns in flat Tesla tables), but it is a small set.
- **Judge sensitivity** (`run_judge_sensitivity.py`): an all-correct score shows nothing unless the judge can say no. 6 answers made wrong with
  figures really in the source (other period's column, annual total, adjusted figure, next quarter's outlook): gpt-oss 6/6 incorrect, qwen 4/4 graded.
- **EU6, EU7:** real failures the verifier passes. Rejected experiment: a release-only prompt rule ("report a figure only as the metric its source
  names... abstain") left both wrong, changed 9 other answers slightly and lost E25's note that both quarters ended in December. Reverted; answers
  35/35 back to the first run from cache.
- **Labels were changed after seeing results:** other locations of the same fact added to quotes (each read in the text), E15's reference corrected (19.2%
  is in the release). This raises citation and retrieval metrics; not a blind review. E15 and E27 still miss citation hit, not diagnosed. Hand labels
  weren't written: with every answer correct, agreement would say nothing, so sensitivity replaced them.
- qwen's Groq JSON mode fails on some inputs (HTTP 400); the first run fell back to Gemini on 2 questions, so the final run is Groq-only.
- Tesla Q3 2022 and Q1 2023 figures are "unanswerable" under a quarter filter, but the FY2023 Q2 release shows them as comparatives.

## Dashboard v0 (user request, MacBook M4, 2026-11-02)

`python -m app.dashboard --log <file>`, http://127.0.0.1:8020 (`app/dashboard.py`, `app/dashboard.html`). The user chose a
local page over Langfuse Cloud. A separate process that loads no models (test), so it can stay open during an eval.
Refreshes every 5 s. Localhost only: logs and traces hold questions and answers, and there is no login.

- **Tokens come from the LLM cache, not from tracing:** each cache file is one successful provider call, and its modified
  time is when the call happened, so all history is covered with no new instrumentation, judge and RAGAS runs included.
  Not counted: failed calls (429s, timeouts) and cache hits. Copying the cache to another machine resets the dates.
- **Limits shown are approximate:** ~200k tokens/day per Groq model, from this project's runs, over a rolling 24 h. Groq's real
  window and remaining quota are only in its console.
- **Logs:** `--log` files and `data/logs/*.log`, requested by name from that list only (test: paths and `..` give 404).
- **Traces:** latest turns from `data/traces/*.jsonl`. `TRACE_FILE=data/traces/app.jsonl` added to `.env`. Judge runs aren't
  traced, so they appear under tokens and logs, not under turns.
- Checked in a browser at desktop and phone widths; the phone view first overflowed sideways (fixed). 8 chart colors pass the
  palette validator on the page's surface. First reading: 1.19M hosted tokens (589 calls), 1.13M local (348 calls).

## Earnings release retrieval v0 (Phase 10 step 3, MacBook M4, 2026-11-02)

The corpus is `chunks.jsonl` + `chunks_earnings.jsonl` (`ChunkStore.from_processed`; 10-Ks first, so their rows
don't move). `build_index` embedded only the 5,571 new chunks (58 s). 23,173 chunks.

- **10-K is the default.** `SearchFilters` gains `fiscal_quarters` and `forms`; `effective_forms()`: explicit forms,
  else releases if a quarter is set, else 10-K. `ChunkStore.mask` and `filter_sql` both apply it.
- **One BM25 index per form** (`PartitionedBM25`): IDF and average length are corpus statistics, so one index
  would let number-heavy releases change every 10-K score, and with it the cached answers and eval baselines.
- **Analyzer rules** (`entities.py`): Q3, 3Q24, Q3'24, FY25, "third-quarter", "quarterly revenue" / "each quarter" (all
  four; "quarterly dividend" stays 10-K), "earnings release", "three months ended <date>" (converted with the
  company's fiscal calendar; a quarter ending in a month's first week counts for the month before). 10-K Item
  sections are dropped on release questions. Follow-ups keep the quarter.
- **Guidance:** a quarter's outlook is searched only in the **previous** quarter's release (Q1's in the prior year's
  Q4). The first version searched both, and the live run answered NVIDIA's Q4 FY2025 outlook with **$43.0B, which is
  the Q1 FY2026 outlook; the verifier passed it because the figure is in the source**. Now $37.5B. Q1 FY2026 guidance is
  answerable (Q4 FY2025 release), Q2 FY2026 is refused.
- **XBRL is skipped on release questions:** facts are annual totals. Plan: 4 sub-queries per company-year, intent
  trend (routed to gpt-oss-120b), rerank pool 15 past 8 sub-queries when quarters are involved.
- **Prompts:** `RELEASE_RULE` and `QUARTERLY_TREND_RULE` are appended only with release sources (test: a 10-K prompt
  equals the old one).
- **Verifier repair for releases** (`_in_release_context`): the live run falsely abstained on Tesla's Q2 2024
  deliveries and NVIDIA's Q3 net income (right figures, wrong or no citation). Rows don't repeat company and period,
  and "Net income was..." has too few content words for the normal repair. For release sources the test is the
  exact figure in a row naming the claim's metric, by 5-character stem. Invented figures and rows about something
  else are still rejected (tests). 10-K sources go through the old code.
- **API/UI:** `fiscal_quarters` / `forms` on search and answer; `/api/search` reads a quarter and year from the query so
  evidence matches the answer. UI: Document and Fiscal quarter filters, scope line, example. Repeated release citations
  collapse (several chunks share one label); 10-K answer text is untouched.

| Verified on real data | Result |
|---|---|
| Retrieval eval vs `reports/retrieval_v1` (per question: top hits + metrics) | **740/740 identical**; 0.891 / 0.933 |
| Routed agent vs `reports/agent_v2`, LLM cache | **84/84 answers identical**, also after the verifier change |
| pgvector vs FAISS on the merged corpus (scratch db) | 23,173 round trip; 35/35 filtered searches same order |
| Hand-picked quarterly retrieval | 12/12: right release, expected figure in the top 10 (rank 1-6) |
| 14 live answers, 2 models | correct figures, right abstentions (below) |
| Browser (driven over CDP) | chip, scope line, Q3 pill, evidence card render |

Live answers: NVDA Q3 FY2025 data center $30.8B; AAPL Q1 FY2025 $124.3B; JPM Q4 2024 $14.0B; TSLA Q2 2024 443,956; NVDA
Q3 net income $19,309M; AAPL FY2025 by quarter 124.3 / 95.4 / 94.0 / 102.5; V FY2024 by quarter 8.6 / 8.8 / 8.9 / 9.6.
Abstained correctly: TSLA Q3 2022 revenue (image-only), AAPL guidance (it gives none). Refused: Q2 FY2026. Annual NVDA FY2025
still answers from XBRL ($130,497M).

Limits, not measured yet (step 4 has no numbers behind these):
- 12 + 14 hand-picked questions are a smoke test, not a metric. Figures were compared with source tables by eye.
- NVDA vs MSFT "Q2 FY2025" compares different calendar quarters (July vs December 2024) without saying so, and its
  derived difference is an unverified claim (2/3 verified). Rule 9 mentions fiscal years, not quarters.
- A citation names the release, not a place in it; the link opens the whole exhibit.
- Figures rank up to 6th for "total revenue" (statement tables score below narrative), inside k=10 but a risk for smaller budgets.
- Multi-year quarterly questions (16+ sub-queries) exceed the 12-source cap, so some quarters drop. Not tested live.
- Latency: single-quarter retrieval 1.3-1.7 s, four quarters 3.1-4.7 s, same as a yearly trend.

## Earnings release chunks v0 (Phase 10 step 2, MacBook M4, 2026-11-02)

`app/ingestion/earnings_pipeline.py` (`python -m app.ingestion.earnings_pipeline`, ~7 s):
`data/processed/chunks_earnings.jsonl` + `earnings_quality_report.{json,md}`.

| 160 releases | Value |
|---|---|
| Chunks | 5,571 (2,722 text / 2,849 table), 33 per release (11-71) |
| Over the 512-token limit | 0 (max 459) |
| Chunks with no heading above them | 196 |
| Releases with statements only as images | 5 (Tesla, below) |

- **SGML wrapper:** every exhibit is stored as `<DOCUMENT><TYPE>...<TEXT><html>`. lxml nested the whole page
  in the inline `<document>` tag, so each release parsed as **one text block with no tables**.
  `strip_sgml_wrapper` runs in `parse_filing` only for content starting with `<DOCUMENT>`.
- **Model:** `Chunk.fiscal_quarter` and `FilingMeta.fiscal_quarter` (None for a 10-K); doc id
  `NVDA-FY2025-Q3-EX-99.1`; one section "Earnings release", nearest heading as subsection; pages 0 and no
  labels, like XBRL facts, so a release chunk can't match a 10-K gold page in the evals. Citation
  `[NVDA Q3 FY2025 release]` in `Source`, the API `Hit` and the UI (chip, card pill). pgvector gains the
  column; `schema_sql` adds it to older tables on load, and `load_chunks` on an old table asks for a reload.
- **Tesla is a slide deck:** one image per slide over a hidden white 1pt text layer, so no tables and one
  flat block per slide. `normalize_slides` restores letter-spaced titles ("F I N A N C I A L ..."; prose
  "Outlook" stays), splits statements into rows and packs them into table blocks that **each repeat the
  period header** (`Q2-2023`, `3Q-2020`, `30-Jun-23`, `2021 2022 2023` in Q4 annual tables). Two of these
  formats were missed at first; a search for figure-heavy text chunks caught them. Rows are positional:
  columns are read by order, not by cell. 7 figure-heavy Tesla text chunks remain; the ones inspected are
  capacity tables and chart text. A slide with no known title inherits the previous slide's subsection.
- **Correction to step 1:** "all 160 exhibits contain an income statement" was a check on words, not figures.
  **Tesla FY2022 Q1-Q4 and FY2023 Q1 have their tables only in the images** (0-4 comma-grouped numbers in
  the text layer vs 569+ from FY2023 Q2): prose survives, the statements don't. Flagged as `figures_missing`.
  Free fix if wanted: local OCR of `exhibit0NN.jpg`. Not done.
- **Verified on real data:**
  - 10-K path: all 40 filings re-chunked in memory: 17,602 chunks equal `chunks.jsonl` field by field, so
    cached embeddings and LLM prompts stay valid. `chunks.jsonl` itself wasn't rewritten.
  - Figures kept: of 36,151 comma-grouped figures in the raw exhibits, 15 aren't in the chunks, all JPM and
    all a footnote digit glued to the next number by the raw-text comparison ("Auto1" + "15,627"; the digits
    after the glue are in the chunks). No real loss.
  - XBRL vs Q4 release, revenue + net income, 10 companies x 4 years: 75/80 in the chunks. The 5 misses are
    absent from the raw exhibit too: Tesla FY2022 (2, images) and JPM revenue FY2022/2023/2025 (3: the
    narrative release doesn't state annual revenue in that form; JPM's statements are in Exhibit 99.2, which
    isn't downloaded).
  - Not verified: quarterly figures against an independent source (XBRL here is annual), retrieval or answers
    over these chunks (step 3), and the citation chip in a browser (lint/build only).
- Tests: 12 new (`tests/test_earnings_pipeline.py`) + an old-schema upgrade test. 227 passing with
  `PG_TEST_DSN` set; without it 225 + 2 skipped. UI lint and build pass.

## Earnings releases v0 (Phase 10 step 1, MacBook M4, 2026-10-30)

`app/ingestion/earnings_downloader.py` (`python -m app.ingestion.earnings_downloader --years 2022 2023
2024 2025`, ~2-3.5 min): 160 releases, 16 per company, all of FY2022-2025, into
`data/raw/sec/<ticker>/8-K/FY<y>_Q<q>_EX-99.1.htm` + `data/raw/sec/manifest_earnings.json` (separate from
the 10-K `manifest.json`, which the pipeline reads; `EarningsReleaseRef` = `FilingRef` + `fiscal_quarter`,
`report_date` = period end, `primary_document` = the exhibit).

- **Quarter mapping:** an 8-K's `reportDate` is the announcement date, so the period comes from the
  company's own 10-Q/10-K period ends in the same submissions feed: the latest one before the filing
  date (within 120 days). Fiscal year = the year the fiscal year ends (same rule as the 10-K corpus);
  quarter = days since the previous fiscal-year end / 91.3, or Q4 when the period is a 10-K date.
  Checked: Apple Q1 FY2022 = 2021-12-25, Microsoft Q1 FY2022 = 2021-09-30, NVIDIA Q1 FY2022 = 2021-05-02,
  Visa Q1 FY2022 = 2021-12-31.
- **Choosing the release:** Item 2.02 isn't only earnings. Tesla files quarterly deliveries reports
  under 2.02 (with 7.01 until 2022, then plain 2.02 + 9.01), NVIDIA pre-announced Q2 FY2023 revenue on
  2022-08-08, Alphabet filed a blog post (2.02 + 8.01) before its Q1 2023 release. Candidates are ranked
  (no items beyond 2.02/9.01 first, then earliest) and, when there is more than one, the first whose
  Exhibit 99.1 has an income statement (net income/earnings/loss + "diluted") wins. 18 periods had a
  choice (16 Tesla, NVIDIA Q2 FY2023, Alphabet Q1 FY2023); all now pick the real release. The first
  version (earliest filing) picked Tesla's deliveries reports, caught by their filing dates (~3 days
  after quarter end vs Tesla's ~20th-of-month earnings).
- **Verified:** all 160 exhibits contain income statement wording (figures: see the correction in "Earnings release chunks v0"); spot checks against the text: NVIDIA Q4
  FY2025 revenue $39.3 billion, Apple Q1 FY2025 revenue $124.3 billion, JPMorgan Q4 2024 net income
  $14.0 billion. Exhibit lookup reads the filing's `-index.htm` table (EX-99.1 row's document).
- Tests (5): fiscal mapping on NVIDIA's and Apple's calendars, candidate ranking/lag/year filters, content
  choice with a fake fetch (preliminary vs release; single candidate unchecked; fallback warning),
  exhibit lookup, manifest merge. 213 passing + 1 skipped.

## CI v0 (Phase 9 step 3, MacBook M4, 2026-10-30)

- `.github/workflows/ci.yml` (push to main, pull requests; read-only token; no secrets):
  `test` (Python 3.11, CPU torch, requirements, pytest; `pgvector/pgvector:pg17` service container with
  `PG_TEST_DSN`, so the real-Postgres round trip runs instead of skipping), `frontend` (Node 24, npm ci,
  lint, build), `eval-gate` (`python -m app.evaluation.check_gate`, standard library only).
- `app/evaluation/check_gate.py` + `reports/gate.json`: 10 checks over committed reports (retrieval
  recall@5 / MRR, plan recall@10 / MRR, agent false abstention / abstention recall / claim support /
  citation hit incl. XBRL, judged correctness by both judges), thresholds a little below eval_v1. A
  missing report, missing metric or NaN fails. Writes a markdown table to the run's step summary.
  Today: 10/10 pass. 9 tests (incl. "committed reports pass the committed gate").
- What the gate can't do: it checks committed results, not a fresh run (CI has no filings, models or
  LLM quota). A change to retrieval code that isn't followed by a regenerated report isn't caught; the
  discipline is "regenerate the affected report in the same PR", and the gate then enforces the floor.
- First GitHub run (2026-10-30): eval-gate (5 s) and frontend (16 s) green; `test` (1.5 min) failed
  1/209: `test_plan_applies_section_prior_before_the_quota_cut` relied on a tie (two chunks of equal
  length under the length-based fake reranker; `sorted` then keeps first-stage candidate order, which
  differed on GitHub's x86 runners vs ARM locally). Fixed by making the fixture's Item 7 text longer, so
  the reranker strictly prefers Item 8 and the +0.5 MD&A prior must overturn it, which is what the test
  claims. An emulated linux/amd64 dry run timed out in pip (32 min under emulation), so the fix is
  verified by reading the code path (all candidates reranked before the cut) and on ARM, not on x86 yet.
- Dry run: the files CI would check out (no `.env`, no data) in `python:3.11-slim` with a pgvector
  container: 209 passed (5 min incl. installs). Frontend `npm ci` + build already ran on Linux in the
  Docker image build; lint passes locally.

## Docker v0 (Phase 9 step 2, MacBook M4, 2026-10-30)

- `Dockerfile`: node 24 stage builds `frontend/dist`; python 3.11-slim with the CPU torch wheel and
  `requirements.txt` minus ragas / langchain-community / pytest (eval/test only; a test checks the API
  imports none of them); runs as uid 1000; healthcheck on `/api/health`. Image 2.13 GB; build 3 min.
  `.dockerignore` keeps `.env`, data, reports, tests, node_modules out (verified: no `.env` or data in
  the image).
- `docker-compose.yml`: `api` (pgvector backend via `db:5432`, `DEVICE=cpu`, `.env` as optional
  env_file, `OLLAMA_BASE_URL=http://host.docker.internal:11434`, `./data` mounted for XBRL / LLM cache /
  traces, `hfcache` volume for models, 127.0.0.1:8010) + `db` (step 1).
- Verified: first start 320 s (downloads bge-small + bge-reranker-base into the volume), warm restart
  17 s; health 17,602 chunks; searches 4.9-6.1 s (reranker 4.8-6.0 s on 10 CPU threads; dense 18-22 ms in
  pgvector); host Ollama reachable from the container; an uncached streamed answer (Tesla FY2022
  revenue, XBRL fact $81,462 million, 1/1 verified) in 24.9 s (retrieve 6.4 s, generate 18.4 s); the LLM
  cache write to the mounted `data/` worked as uid 1000; UI screenshot from the container rendered the
  answer. Memory: api 1.1 GB, db 78 MB. `docker compose down` afterwards (volumes kept).
- Linux CPU torch + faiss in one process: no crash (the OpenMP problem is macOS-only).
- The CPU reranker is the cost of containers on a Mac (no MPS in Docker): ~3-4x slower retrieval.
  Running the API natively stays the fast path for demos; compose is the reproducible path.

## pgvector v0 (Phase 9 step 1, MacBook M4, 2026-10-30)

- `app/retrieval/pg_store.py`: one table `chunks` (row = position in `chunks.jsonl`, every `Chunk`
  field, `embedding vector(384)`), btree indexes on ticker / fiscal_year / section / chunk_type, a
  `corpus_meta` table (embedding model, dims, count, index type). `python -m app.retrieval.pg_store`
  loads chunks + cached embeddings with COPY in one transaction (17,602 rows, 54 MB, 20 s; idempotent;
  `--hnsw` for an approximate index). `PgVectorIndex.search(query, k, mask, filters)` keeps
  `DenseIndex`'s contract (rows + inner products); filters become `WHERE col = ANY(...)`.
- `VECTOR_BACKEND=faiss|pgvector` (default faiss), `DATABASE_URL` (default localhost:5433). In pgvector
  mode `build_retriever` loads chunks from Postgres (BM25 and the reranker still run in memory) and
  refuses to start if the stored embedding model differs from the configured one. The retriever passes
  `filters` next to the mask to the dense index (FAISS ignores them).
- `docker-compose.yml`: `db` service (pgvector/pgvector:pg17, 656 MB image, volume, healthcheck,
  bound to 127.0.0.1:5433; dev-only password).
- Verification: chunks from Postgres == `chunks.jsonl` (all 17,602); dense top-10 identical in order
  for 168 golden searches (84 × unfiltered/gold filters), max score diff 3e-7; retrieval eval
  (`--no-ablations`) identical per question and mode, 740/740, FAISS vs pgvector. Dense latency in
  the eval: FAISS 0.2 / 0.4 ms, pgvector 4.9 ms filtered / 45 ms unfiltered (p95 13.5 / 53 ms).
- Tests: SQL building with a fake connection, schema/Chunk sync, and a real round trip vs FAISS when
  `PG_TEST_DSN` points at a scratch database (`createdb -U finrag finrag_test` in the container;
  never the main db: the load replaces the table). 198 passing + 1 skipped without it.
- Side finding: the same eval with today's gold labels gives hybrid_rerank recall@5 0.891 / MRR 0.933
  (gold filters) and 0.884 / 0.925 (none); `reports/retrieval_v0` (0.884 / 0.920) predates the Phase 5
  gold review and was never rerun.

## Streaming v0 (Phase 8 step 2, MacBook M4, 2026-10-30)

- `FinRAGAgent.stream()` yields an `AgentEvent` (node, update, elapsed ms) per finished node from
  LangGraph `stream(stream_mode=["updates", "values"])`, then the `AgentTurn`; `run`, `ask` and
  `stream_ask` all consume it (one code path for trace, memory, user filters). `answer_model(intent)`
  names the model that will answer before generation starts.
- `POST /api/answer/stream` (SSE): `step` events (analyze: read-as query, filters, in_scope; retrieve:
  hits, intent, answer_model; xbrl: fact citations; generate: model, sources; verify: claims/verified/
  abstained), then `answer` (the `/api/answer` body, shared `answer_response`) or `error` (LLM failure
  → 502 detail). 503/422 are plain HTTP errors before streaming starts. The turn runs in its own thread
  feeding a queue: Starlette iterates sync generators on varying pool threads, and the trace contextvar
  must open and close in one thread; a disconnecting client doesn't cut a turn short.
- Not token streaming: answers are structured JSON shown only after verification.
- UI: `answerApi.stream` (fetch + ReadableStream; `EventSource` can't POST) with fallback to
  `/api/answer` on 404 / network error / a stream that ends without an answer. The answer panel's
  skeleton became a stage list with live details and times.
- Live check: an uncached Tesla FY2024 revenue question streamed analyze at 4 ms, xbrl 33 ms, retrieve
  1.5 s, generate 13.6 s, verify, answer, arriving in real time (curl timestamps). Screenshots: desktop
  and phone mid-generation ("Generating with granite4.1:3b" active), refusal, completed answer; all 5
  UI answers used the stream endpoint (0 fallbacks).

## API on the agent v0 (Phase 8 step 1, MacBook M4, 2026-10-30)

- `/api/answer` builds a `FinRAGAgent` at startup (production: XBRL store, routed Groq LLM when
  `ANSWER_ROUTE` (default on) and a Groq key exist, trace sinks from settings; tests: fakes only, never
  data, keys or trace settings). `LockedRetriever` serializes only the model calls (search /
  search_many), so one request's LLM call overlaps another's retrieval.
- Filters: the UI's selected filters override the analyzer's per field (`merge_filters`); unset fields
  come from the question. Scope refusals still come from the question (a filter can narrow an
  answerable question, not make an unanswerable one answerable).
- Request: optional `thread_id` (`[A-Za-z0-9_-]`, ≤100) → `agent.ask` with per-thread memory; `decompose`
  is ignored (the plan decomposes). Response adds `standalone_query`, `filters`, `intent`, `steps`, `facts`,
  `thread_id`; XBRL sources come back as hits with section "XBRL" and stage `xbrl`.
- UI: per-session thread id (a ref, so "New conversation" doesn't re-ask), "Read as …" / scope line,
  intent, model, XBRL fact count and agent-step pills, XBRL citations as dashed chips, out-of-scope
  refusals titled "Outside what the filings cover." Answer header wraps at phone width (was clipped).
- Live check (:8010, one thread): Apple Services lookup 1.3 s (cached); NVIDIA FY2022-25 revenue trend
  routed to gpt-oss-120b, 4 XBRL facts as one series table, 5/5 claims verified, 4.5 s (cached); follow-up
  "And what was its net income in fiscal 2025?" rewritten to NVIDIA FY2025, answered from the XBRL fact
  ($72,880 million) in 19.3 s (rewrite 6.4 s incl. Ollama warm-up, generation 11.5 s); "Microsoft's
  current stock price" refused at analyze in 3 ms.
- In the browser, the page's search and answer queue on the same model lock, so an answer's total
  includes waiting for the search (trend: 6.1 s vs 4.5 s alone).

## Tracing v0 (Phase 7 step 5, MacBook M4, 2026-10-30)

`app/tracing.py`. One `Trace` per agent turn in a contextvar: `FinRAGAgent` wraps every node in a
`span`, and `LLM.generate` calls `record_generation` (schema name, provider, model, tokens, cached,
the provider call's latency, failed attempts), so nothing is passed down through the answerer,
analyzer or judge, and judge/RAGAS calls are traced too when run inside a trace. LangGraph's parallel
branches (retrieve ∥ xbrl) run in a thread pool that copies the context, so they land in the same trace
(test). An open trace is reused by nested ones: `run_agent_eval` opens one per question tagged with id,
config and category; the agent adds steps, intent, model, abstained.

Sinks: `AgentTurn.trace` (always); `TRACE_FILE` JSONL (`python -m app.tracing <file>` prints per-node
p50/p95 and calls/tokens per model); **Langfuse** via its public ingestion API (trace-create,
span-create per node, generation-create per LLM call under its node's span; Basic auth; 207 errors
raise) when both keys are set. No Langfuse SDK: the HTTP API is small and the v3 SDK brings OpenTelemetry.
A failing sink logs a warning and never breaks an answer (test). `build_agent` reads sinks from
settings; tests and eval runners build agents without sinks unless asked.

Real run (`TRACE_FILE=data/traces/agent_v2.jsonl python -m app.evaluation.run_agent_eval --configs
agent_routed --out <scratch>`): 84 traces, 0 uncached LLM calls, **84/84 answers identical to agent_v2**.

| Node (cached LLM run) | n | p50 ms | p95 ms |
|---|---|---|---|
| retrieve | 79 | 1,522 | 8,559 |
| xbrl | 79 | 0 | 27 |
| analyze / generate / verify | 84 / 79 / 79 | ≤2 | ≤3 |

| Retrieve by plan intent | n | p50 ms | max ms |
|---|---|---|---|
| lookup | 13 | 1,138 | 1,954 |
| numeric | 41 | 1,429 | 2,615 |
| comparison | 13 | 4,464 | 5,185 |
| trend | 12 | 6,586 | 10,348 |

| LLM (provider latency from the cache entries) | Calls | Prompt tok | Completion tok | p50 ms | p95 ms |
|---|---|---|---|---|---|
| GeneratedAnswer / granite4.1:3b | 53 | 171,893 | 3,144 | 15,625 | 19,780 |
| GeneratedAnswer / gpt-oss-120b (routed) | 26 | 97,450 | 8,295 | 1,833 | 36,088 |
| StandaloneQuestion / granite4.1:3b (rewrites) | 6 | 803 | 145 | 1,087 | 1,588 |

Reading:
- Uncached end-to-end ≈ retrieval + provider call: local answers ~17 s p50 (generation is 90% of it);
  routed (trend/comparison) answers ~6-8 s p50, and there **retrieval is the larger part** (trend 6.6 s: one reranked
  sub-query per company-year, 30 candidates each). Cheapest lever if latency matters: a smaller
  rerank pool for sub-queries of multi-entity plans (Phase 4 measured 15 vs 30 at -0.03 context recall
  on all queries; untested per sub-query).
- gpt-oss p95 36 s is a few slow Groq calls (reasoning on long trend contexts), not rate-limit waits:
  those are outside `latency_ms`, inside the node span.
- Tokens per answer: ~3.3k local, ~4.1k routed; the routed number sets the free-tier capacity (~200k/day).

## RAGAS v0 (Phase 7 step 4, MacBook M4, 2026-10-29)

`app/evaluation/ragas_metrics.py` + `python -m app.evaluation.run_ragas_eval` (`reports/ragas_v0.md`).
RAGAS 0.4.3 collection metrics run through FinRAG's own `LLM` layer: `RagasLLM` implements RAGAS's
`InstructorBaseRagasLLM` (`agenerate(prompt, PydanticModel)`) over `LLM.generate`, so every call is
cached, rate limited and strict-schema, with no OpenAI client. Model: Groq qwen3.8-27b (wrote no
answer). Metrics: `Faithfulness` vs the cited sources (2 calls) and `FactualCorrectness` vs the
reference (4 calls), the latter reported as precision, **coverage** (reference claims the answer
entails: the judge's correctness counterpart) and RAGAS's own f1. RAGAS's "recall" mode was not used:
it's tp / (tp + fn) with tp from the precision direction.

**Cost decided the sample:** 6 calls and ~5k tokens per question, ~30 s each under Groq's per-minute
limit; all 74 answered questions = ~400k tokens (2 days of qwen quota) and ~40 min. Run on a stratified
26: L01-L10, three judged not correct (L13, L17, L22), N01 N04 N12 N16, T01 T06 T09 T12, C02 C05 C10, F01 F05.

| 26 answers (routed v2) | RAGAS | Judge (qwen, judge_v2_qwen) |
|---|---|---|
| Faithfulness to cited sources | 0.813 | 0.808 (Spearman **0.86**, MAE 0.08) |
| Correctness | coverage 0.500 / f1 **0.294** / precision 0.302 | **0.808** |
| Spearman vs judge correctness | coverage 0.55 / f1 0.27 | |

| Judge grade | n | RAGAS coverage | RAGAS f1 |
|---|---|---|---|
| correct | 20 | 0.62 | 0.35 |
| partially_correct | 2 | 0.33 | 0.38 |
| incorrect | 4 | **0.00** | 0.00 |

Reading:
- **Faithfulness: RAGAS corroborates the judge.** Same mean, 0.86 rank correlation. It confirms the
  judge's citation finding on L01/L02 (correct answer, cited page doesn't state it). One clear split:
  T12 (Meta capex), RAGAS 0.00 vs judge 1.00.
- **Factual correctness: rejected as a correctness metric.** RAGAS never passes a judge-incorrect
  answer (4/4 score 0), but scores correct answers 0.35 f1 because its NLI is literal: "$26,914 million"
  isn't entailed by "$26.91B", "228,000 … in 2025" doesn't entail "(June 2025)", and correct extra
  detail (prior-year growth) counts as a false positive (T06 f1 0.18, C05 coverage 0.00, L03 0.00: all
  correct). 12 of 26 correctness disagreements of ≥0.5, all RAGAS stricter. Fixing that means rewriting
  its prompts, i.e. rebuilding the judge. The judge (validated on hand labels) stays the correctness
  metric, with RAGAS faithfulness as an independent corroboration.
- Install: ragas 0.4.3 needs `langchain-community<0.4` (it imports a module removed in 0.4); it also
  downgrades tenacity 9 → 8.5 and rich 15 → 13 (instructor pins). All 178 tests pass.
- Ops: long trend answers hit Groq's per-minute 429 three times in a row (T01, T09), and `LLM` gives
  up after 3 retries; rerunning the same command filled them (everything else came from the cache).
  The first uncached smoke once hung with 0% CPU for 10+ min (likely a stalled connection; a rerun was fine).

## Routing v2 results (Phase 7 step 3, MacBook M4, 2026-10-27)

Routed agent: trend/comparison (by plan intent) answered by Groq gpt-oss-120b, the rest by granite4.1:3b
("Answers by: granite4.1:3b (53), openai/gpt-oss-120b (26)": 24 routed + L27's usual fallback + U05,
an unanswerable two-company question planned as a comparison, correctly abstained). Same answers judged twice:

| Judged correctness | v1 gpt-oss | **v2 gpt-oss** | v1 qwen | **v2 qwen** |
|---|---|---|---|---|
| All answerable (abstention = 0) | 0.777 | **0.865** | 0.764 | **0.865** |
| Answered | 0.821 | 0.901 | - | 0.901 |
| trend (12) | 0.542 | **0.792** | 0.542 | **0.792** |
| comparison (12) | 0.667 | **0.958** | 0.625 | **1.000** |
| lookup / numeric / follow-up | unchanged (same local answers) | | | |
| Hand-label agreement (10 still valid) | 0.91 | 0.90 / 1.00 | 1.00 | 1.00 / 1.00 |

| Agent metrics | v1 (`agent_v1`) | **v2 routed** (`agent_v2`) |
|---|---|---|
| False abstention | 0.054 | **0.041** |
| Abstention recall | 1.000 | 1.000 |
| Figure recall | 0.612 | **0.653** |
| Citation hit incl. XBRL | 0.865 | 0.878 |
| Claim support (verifier) | 0.942 | 0.965 |

- **Decision: keep routing.** The independent judge (qwen) and the generator's own model (gpt-oss)
  agree on every category score within 0.04; judges agree 0.94 exact / 0.96 binary on the v2 answers
  (`judge_agreement_v2.md`), so self-preference isn't driving the gain. No new abstentions.
- **Latency** (Groq, uncached, net of rate-limit waits; retrieval + answer + judge call): p50 ~9 s,
  p95 ~20 s over 22 routed questions (local 3B generation alone was p50 ~18 s). The logged ~45 s per
  question was mostly `TokenRateLimiter` waiting for Groq's ~8k tokens/minute window.
- **Serving cost on the free tier**: ~3.5k tokens per routed answer → ~55 routed questions/day on the
  200k daily quota and ~2/minute on the TPM limit; past that the local model answers (v1 quality).
  The API doesn't use the agent yet (it calls `Answerer` directly): wiring `build_agent(route=True)`
  into `/api/answer` is Phase 8 work.
- **Network outage mid-run**: 5 routed calls (C06-C10) hit `ConnectError` and silently fell back to
  Ollama; caught from the log, rerun the same command (only those 5 reached Groq). Reports now print
  "Answers by" / "Judge" model counts (`answer_model`, `judge_model` per record) so a mixed run is
  visible; the hardcoded "granite4.1:3b answers" title is gone.
- Agent report: title uses the output name; "End-to-end p50 (uncached)" no longer counts analyzer
  refusals (they showed as 0.7 ms when everything else was cached).

## Routing and second judge (Phase 7 step 3 prep, MacBook M4, 2026-10-26)

- **Routing**: `FinRAGAgent(routed_llm=..., routed_intents=("trend", "comparison"))`; `_generate`
  picks the routed `Answerer` by the plan's intent (same prompts and intent rules). `build_agent(route=True)`
  builds it with `llm_providers="groq,ollama"`, so Groq's daily cap falls back to the local model.
  `python -m app.agent.graph --route ...`, `run_agent_eval --configs agent_routed`,
  `run_judge_eval --route`. Not run yet: gpt-oss-120b's daily quota was used by the judge runs.
- **Why a second judge**: routed answers would come from gpt-oss-120b, the same model as the judge,
  and LLM judges favour their own outputs. Gemini was tried first as the independent judge and failed
  again (HTTP 503 and read timeouts on 2 of 2 calls, ~4 min each). Groq's free limits are per model,
  so `run_judge_eval --judge-model qwen/qwen3.8-27b` judges with a different model family on its own
  quota (~1.3k tokens/call). Models on this key: gpt-oss-120b, gpt-oss-20b, qwen3.8-27b, allam-2-7b
  and speech/guard models.
- **Judge agreement** (`reports/judge_agreement_v1.md`, `compare_judges.py`), same 70 v1 answers:

  | | gpt-oss-120b judge | qwen3.8-27b judge |
  |---|---|---|
  | Correctness, all answerable | 0.777 | 0.764 |
  | trend / comparison | 0.542 / 0.667 | 0.542 / 0.625 |
  | Agreement with the 11 still-valid hand labels | 0.91 | 1.00 |

  Exact agreement between judges 0.91, correct vs not-correct 0.93. Disagreements are strictness on
  secondary details (L20, L22, C11, T05: qwen stricter) and one real miss each way: qwen calls T06's
  wrong "342.6%" overall growth correct, gpt-oss calls L26 incorrect where the label says partial.
  Conclusion: either judge alone is usable for category-level metrics; per-question verdicts need both.

## Trend fixes v1 (Phase 7 step 2, MacBook M4, 2026-10-26)

Three changes, judged with the same judge (`python -m app.evaluation.run_judge_eval --out
reports/judge_v1`; only changed answers cost judge tokens: 42,847):
- **XBRL series table** (`xbrl.series_chunk`, `fact_chunks`): on trend/comparison questions a
  company's metric over 2+ years becomes one table (year, period, value, YoY change, direction word
  computed in code: up / down / flat within ±1%), cited as `[XBRL JPM Net income FY2022-FY2025]`.
- **Intent prompt rules** (`answer.INTENT_RULES`, appended only for the plan's trend/comparison
  intent, so other prompts and their cache entries are unchanged): one line per year, oldest first,
  directions from the figures, a one-year change is not a CAGR; for comparisons, each figure first,
  then a comparison checked against the numbers.
- **Live-data scope rule** (analyzer `live_data` scope): a live-time cue (current, today, right now,
  live...) plus a market quantity (stock/share price, market cap, trading at) is refused before
  retrieval. "Current liabilities", "current market position", "current valuation allowance" stay in
  scope (tests).

| Judged correctness | v0 | **v1** | v1 strict (rejected) |
|---|---|---|---|
| All answerable (abstention = 0) | 0.730 | **0.777** | 0.736 |
| Answered | 0.771 | 0.821 | 0.838 |
| trend (12) | 0.250 | **0.542** | 0.375 |
| comparison (12) | 0.667 | 0.667 | 0.583 |
| numeric / lookup / follow-up | 0.941 / 0.815 / 0.833 | unchanged (same prompts, cached) | unchanged |

| Agent metrics (`reports/agent_v1.md`) | v0 | v1 |
|---|---|---|
| False abstention | 0.054 | 0.054 |
| Abstention recall | 0.900 | **1.000** (U04 refused at analyze) |
| Figure recall | 0.573 | **0.612** |
| Citation hit incl. XBRL | 0.878 | 0.865 |
| Claim support (verifier) | 0.975 | 0.942 |

Reading:
- Trend fixed where the model now lists every year (T01, T02, T03, T05, T09 → correct). Still wrong:
  T06 computes "342.6%" over FY2022-25 (it's +384.9%), T04/T07 mis-copy figures, T10 misses 2022
  (likely retrieval), T11 is the buyback definition case.
- Comparison is flat: C06 and C10 improve to partial, C02 (correct in v0) now abstains because the
  model computes a 31% Google Cloud growth rate no source states and the verifier rejects the claim.
- **Rejected experiment** (`reports/judge_v1_strict.md`): adding "never compute a percentage the
  sources don't state" made the 3B model abstain on 6 more questions (T01, T04, T05, T06, C02, C06):
  answered-only correctness rose (0.838) but all-answerable fell (0.736). Prohibitions push a small
  model into abstaining; reverted. The remaining errors look like model capacity: next step routes
  trend/comparison to the 120B model.
- Judge agreement on the 11 labelled answers still identical to v0: 0.91 exact / 1.00 (labels
  describe v0 answers, so changed answers are excluded from the agreement now).
- L27 (lookup) has been answered by Groq since v0: Ollama returned invalid JSON and the LLM layer
  fell back. Unchanged between runs, cached.
- Latency was not re-measured (everything came from cache); v0's p50 ~18 s for generation stands.

## Judge v0 (Phase 7 step 1, MacBook M4, 2026-10-26)

`app/evaluation/judge.py` + `python -m app.evaluation.run_judge_eval` (`reports/judge_v0.md`):
one Groq gpt-oss-120b call per answered question (Gemini fallback; never the 3B model that
answered) with the question, the reference answer, the candidate answer and **only the cited
sources** (~1.6k tokens/call; 70 calls = 98,920 tokens, half of Groq's daily 200k). Returns
correctness (correct / partially / incorrect, with missing and contradicted reference facts) and
per-claim faithfulness in meaning. Abstentions are scored by rule (no call). The runner re-runs the
agent from the LLM cache and checks every answer equals `agent_v0` (all 84 matched).

**Validation first:** 22 answers labelled by reading reference vs answer
(`data/eval/judge_labels_v0.jsonl`, labelled by Claude Code, review welcome): exact agreement
0.86, correct-vs-not 1.00. The 3 disagreements are partial-vs-incorrect boundary cases (T06 judged
partial although it flags the "CAGR" claim; L26 and C06 judged harsher than the label). Judge
errors seen: T11 "FY2025 figure lacks a source" (it is cited), C10 possibly too strict on a
Mastercard figure the reference doesn't mention.

| Agent answers (granite4.1:3b) | Value |
|---|---|
| Correctness, answered (70) | 0.771 (50 correct, 8 partial, 12 incorrect) |
| Correctness, all answerable (abstention = 0) | 0.730 |
| Judge faithfulness (claims, in meaning) | 0.842 |
| Verifier claim support (figures only) | 0.975 |

| Category | Correctness | Faithfulness |
|---|---|---|
| numeric | 0.941 | 0.941 |
| follow_up | 0.833 | 1.000 |
| lookup | 0.815 | 0.821 |
| comparison | 0.667 | 0.879 |
| **trend** | **0.250** | 0.630 |

Reading:
- **17 answers pass the verifier and are judged not correct**: the verifier's blind spot measured.
  Wrong direction (T04, T05, T07), wrong comparison (C05), wrong year for a figure (N16, L17),
  mislabel (T06), fabricated or mismatched figures (C06, T01), and dropped years (T02, T03, T09, T10).
- Faithfulness < correctness on lookups: right answers citing a page that doesn't state the fact
  (L01 cites p.24, the drivers are on another page; L08, L20). Citation quality, not answer quality.
- Trend is the worst category by far; the context usually has every year (retrieval/XBRL), so the
  fix is on the generation side (Phase 7 step 2).
- Hand labels were written by the same assistant that wrote the judge prompt: a real limit. The
  user reviewing the 22 labels (5 minutes) would make the validation independent.

## Agent eval v0 (Phase 6 step 5, MacBook M4, 2026-10-26)

`python -m app.evaluation.run_agent_eval` (`reports/agent_v0.md`, ~45 min on granite4.1:3b; the
no-XBRL pass reuses cached prompts). All 84 questions through `FinRAGAgent.run(question,
history)`: analyzer filters and rewrites, retrieval plan, XBRL. Baseline: v1 with gold filters
and the gold rewrite, v0 decomposition, same model.

| Metric | gold filters (v1) | **agent** | agent, no XBRL |
|---|---|---|---|
| False abstention | 0.054 | **0.054** | 0.095 |
| Abstention recall | 1.000 | 0.900 | 0.900 |
| Citation hit (gold page) | 0.863 | 0.689 | 0.824 |
| Citation hit incl. XBRL | - | **0.878** | 0.824 |
| Figure recall | 0.583 | 0.573 | 0.553 |
| Claim support | 0.978 | 0.975 | 0.985 |
| Filters compatible with gold | - | 1.000 | 1.000 |
| LLM p50 / p95 ms | 18,166 / 21,662 | 17,629 / 24,604 | 17,053 / 21,321 |

Reading:
- **The agent loses nothing against gold filters** on false abstention and nearly nothing on
  figure recall. Without XBRL it would be clearly worse (0.095): the facts rescue N12, T05, T06 and
  C03, the trend/comparison questions retrieval kept missing. Comparison figure recall 0.667 → 0.773.
- Gold-page citation hit drops 0.863 → 0.689 *because* the model cites the exact facts instead of
  pages (18 of the 26 questions with facts cite one); counting a verified XBRL citation that states a
  reference figure, 0.878.
- **Costs of XBRL:** T12 (Meta capex 2024 → 2025) now abstains: facts ($37.26B / $69.69B purchases
  of PP&E) and text ($39.23B / $72.22B incl. finance leases) disagree and the 3B model gives up.
  T11 (Apple buybacks) answers with XBRL cash paid instead of the program totals, despite the rule.
  N09/F06 (Meta capex) follow the rule and use the text's $72.22B. N16 uses the text but picks
  2022's $58.3B for 2023: a meaning error the verifier can't see.
- **U04 ("Microsoft's current stock price") answered:** the agent filters to MSFT (v1 gave
  unanswerable questions no filters), retrieval finds the Item 5 buyback table and granite
  "estimates" the price from the $376.90 average repurchase price. Needs a live-market-data scope
  rule (Phase 7 step 4).
- Granite's trend prose is weak even with the right facts (T05 "decreased from $37.7 billion to
  $57.0 billion"; T06 calls FY2025 YoY growth a "CAGR"). The verifier only checks figures, so
  these pass: this is what the Phase 7 judge must measure.
- Latency: generation dominates (p50 ~18 s on the 3B model); retrieval p50 ~1.3-2 s; the analyzer
  costs ~1 s only on the 6 follow-ups that need a rewrite.

## Agent graph v0 (Phase 6 step 4, MacBook M4, 2026-10-26)

`app/agent/graph.py` (`python -m app.agent.graph "Q1" "follow-up" ...` runs one conversation):

```
START → analyze ─out of range→ refuse → respond → END
          └in corpus→ retrieve ∥ xbrl → generate → verify → respond
                                generate ─no sources→ respond
                                verify ─abstained under a section filter (once)→ widen → retrieve ∥ xbrl
```

- `retrieve` = `make_plan` + `execute_plan` on the analyzer's standalone query and filters;
  `xbrl` = `detect_metrics` + `lookup_many` (only when the question names company, metric and year;
  at most 8 facts). They run in the same LangGraph step; `generate` joins them, puts the facts first
  (score 1.0) and allows 12 text sources besides.
- `Answerer` was split into `generate()` + module-level `finalize()` (verify, abstain, render) so the
  graph has separate generate/verify nodes; `answer_from_hits` behaves exactly as before. The XBRL
  prompt rule (text wins on definitions) is appended to the system prompt **only** when facts are in
  the context, so v1 prompts and their LLM cache entries are unchanged.
- Memory: `ConversationMemory` (thread id → turns, last 6 exchanges, LRU over 1,000 threads),
  passed into the graph as `history`. Not LangGraph's checkpointer: it would store every node's
  chunks per thread and warns on every custom dataclass (blocked in a future langgraph version).
- Analyzer fixes found in the real run: (1) an out-of-range year asked mid-conversation ("Apple's
  iPhone sales in fiscal 2018" after a Meta question) inherited FY2025 instead of being refused;
  the range check now runs before the follow-up path. (2) Every question after the first in a
  thread paid an LLM rewrite (~1 s, plus Groq quota); a question that names its own company and year
  and has no back-reference (its/that/they, "And ...?", "How about") is now standalone. Analyzer
  eval unchanged (tickers 1.000, years 0.905, sections 1.000; 4/10 unanswerable refused, 0
  answerable refused): the golden follow-ups all lack a company or a year.

Real conversation (Ollama granite4.1:3b, reranker on mps):

| Turn | Path | Result | Total |
|---|---|---|---|
| NVIDIA revenue FY2022→2025 | 4 XBRL facts + text | answered, high; but calls 114.2% (FY2025 YoY) a "CAGR" | 24.5 s (retrieval 4.8 s, first query warm-up) |
| "And what was its net income in fiscal 2025?" | rewrite → NVDA FY2025, 1 fact | $72,880 million, high | 13.5 s |
| Visa vs Mastercard FY2025 growth | 2 facts | Mastercard 16% vs Visa 11.3%, high | 17.2 s |
| Meta capex 2025 | 1 fact (PP&E $69.69B) + text | **$72.22B from the text** (definition rule worked) | 13.3 s |
| Apple iPhone fiscal 2018 | (before the fix: inherited FY2025) | generator abstained; now refused at analyze | 14.0 s |

Generation dominates latency (11-20 s on the 3B model); analyze ≈ 1 s only when a rewrite runs.
Verifier limit seen again: it checks figures, not their meaning (the "CAGR" label passes because
114.2% is in the source); that's the Phase 7 faithfulness judge's job.

## XBRL tool v0 (Phase 6 step 3, MacBook M4, 2026-10-26)

`app/agent/xbrl.py`: SEC companyfacts JSON per company (`python -m app.agent.xbrl --download`,
~45 MB for 10 companies under `data/raw/xbrl/`, gitignored), 13 metrics, each a priority list of
us-gaap concepts (revenue: `Revenues` → `RevenueFromContractWithCustomerExcludingAssessedTax` →
`RevenuesNetOfInterestExpense` → `SalesRevenueNet`; net income: `NetIncomeLoss` → `ProfitLoss`, for
Mastercard; equity: Visa uses the incl.-NCI concept; cash: JPM's `CashAndDueFromBanks`).

Fact selection (the part that matters): only facts from the fiscal year's own 10-K (`accn` from the
manifest), period end within 7 days of the manifest's report date, duration 340-380 days (flow) or
an instant (balance sheet). The `fy` field is **not** used: it's the filing's year, so comparatives
inside a 10-K carry the wrong label. The same filing's prior-year value gives the YoY change, which
is what makes growth questions answerable and is split-safe (NVDA FY2025 EPS $2.94 vs prior $1.19,
both split-adjusted; across filings it would be $11.93 → $2.94). Fallback: when the filing tags none
of the concepts, use the next 10-K's comparative and mark the fact `comparative` (NVDA FY2022-23
capex was tagged with a custom `nvda:` concept, which companyfacts omits).

Coverage: 459/520 cells. Every gap is a real absence, not a bug: banks have no operating income /
gross profit / R&D (JPM), Tesla doesn't buy back stock, Amazon had no buybacks in FY2025 and
doesn't report gross profit or R&D as such, Visa tags EPS per share class only.

`detect_metrics(question)`: regex per metric plus a segment guard (Data Center, AWS, Services,
iPhone, cloud, China, customers, deliveries... → no facts: XBRL has the company total only).

Golden set (`python -m app.evaluation.run_xbrl_eval`, rule-based analyzer filters, no gold filters,
figures matched with the verifier's number matching):

| Category | Answerable | Tool fires | Gold figures covered |
|---|---|---|---|
| numeric | 17 | 11 | 17/23 |
| trend | 12 | 6 | 22/28 |
| comparison | 12 | 6 | 14/16 |
| lookup + follow-up | 33 | 3 | 2/5 |
| **all** | 74 | 26 | **55/72 (76%)** |

All 4 targeted retrieval misses are fully covered: T05 JPM net income (8/8 figures incl. growth),
T06 NVDA revenue (6/6), T07/T08 Visa/Mastercard growth rates (4/4 each), C03 (2/2 GAAP figures).
The 17 uncovered figures are the honest limit:
- **Definition mismatch (5 questions, the risk to handle in step 4):** Meta capex "including
  principal payments on finance leases" ($72.22B vs XBRL purchases of PP&E $69.69B: N09, T12, F06),
  Amazon "cash capex" net of proceeds/incentives ($48.1B vs $52.7B gross: N16), Apple buybacks
  ($90.2B program total vs $89.4B cash paid: T11). XBRL is right about its line item; the question
  means the company's definition. Hence "XBRL is an extra source, text wins on definitions".
- Non-GAAP: currency-neutral growth ("15% currency-neutral"), share of sales (8% of net sales).
- EPS in N12's answer when the question only asks net income.

Side fix found on the way: the verifier didn't read "$37.7B"/"$450M" as scaled numbers (only
"billion"/"bn"), so a correct claim written that way failed as `unsupported_number`. It now accepts
`B`/`M` attached to the digits (not after a space: "Item 7 B" stays 7). This can only turn failures
into passes; the v1 generation reports predate it.

## Groq baseline v1 (Phase 5, completed 2026-10-14)

`openai/gpt-oss-120b`, same prompt/verifier/retrieval as Ollama v1, `reports/generation_v1_groq.md`.
Run over two days (Groq's 200k-token daily cap stopped day 1 at 53 questions; cached answers were
reused on 2026-10-14). All 84 questions, 0 errors, 307k tokens in total.

| Model (84 q) | False abst. | Abst. recall | Citation hit | Evidence recall | Claim support | Figure recall | LLM p50 |
|---|---|---|---|---|---|---|---|
| Groq gpt-oss-120b | **0.014** | 1.000 | **0.959** | **0.884** | 0.966 | **0.653** | 1.1 s |
| Ollama granite4.1:3b | 0.054 | 1.000 | 0.863 | 0.797 | 0.978 | 0.583 | 18 s |

The big model cites properly, so the verifier's repair matters less; the 3B model is ~9 points
behind on grounding but fully offline. Its only false abstention (F05) is defensible: the filing
gives China's data-center share only as "mid-single digit percentage". Trend is Groq's weak spot
(evidence recall 0.701): T04 "the 2025 delivery figure is not provided", T05 only endpoint years,
C03 "Visa's growth not disclosed". These are **retrieval** misses: those entities' gold pages rank
4-19 in their own sub-search, behind Item 1/Item 8 chunks (Phase 6 step 2 diagnostic).
Figure recall stays ~0.6-0.65 because references often contain secondary figures ("up 4%") that a
correct short answer omits; the LLM judge in Phase 7 should replace it as the correctness metric.

Live UI test (API on :8010, `LLM_PROVIDERS=ollama`): a lookup (TSLA deliveries) renders with
medium confidence and the "Citation added by the verifier" note; Azure vs AWS is withheld with
"Figure not found in the cited page: $168.9 billion"; Netflix (not in corpus) abstains. Screenshots
were checked in headless Chrome. Gotcha: `--virtual-time-budget` hangs on this page (pending
fetches/animations); use `--timeout=12000` instead.

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
- CI gates committed eval results (`reports/gate.json`), not fresh runs: the eval needs filings, local
  models and LLM quota that CI doesn't have. Regenerate an affected report in the same change.
- Postgres + pgvector is an alternative backend with identical results (`VECTOR_BACKEND=pgvector`, exact
  search, filters in SQL); FAISS stays the default for zero-setup local runs and tests.
- Vector search is exact FAISS `IndexFlatIP` (no IVF/PQ/HNSW/ScaNN/DiskANN), benchmarked on our data
  (`reports/index_benchmark.md`): 0.36 ms per query vs 1.5 s retrieval (reranker); recall 1.0 under
  company/year filters, where HNSW ef 16 / IVF nprobe 1 drop to 0.87 / 0.59; HNSW in pgvector past ~1M vectors. Full reasoning and an interview answer: `docs/ARCHITECTURE.md`, "Vector index choice".

- Source = SEC EDGAR HTML, not IR-site PDFs (stable URLs, structured tables, exact page breaks).
- `fiscal_year` = year of the period end (matches company labels: NVDA FY2025 ended 2025-01-26).
- Original 10-K only; 10-K/A excluded.
- Dependencies are added to `requirements.txt` phase by phase.
- Build eval v0 (Phase 4) before generation so retrieval tuning is measured.
- Multi-entity questions use per-(company, year) decomposition with per-entity quotas (Phase 4 data).
- Trend/comparison prompts get intent rules and an XBRL series table with directions computed in
  code; prohibitive wording ("never compute...") was tested and rejected (more abstentions).
- Live market data (current share price, market cap now) is out of scope at the analyzer.
- Tracing is backend-neutral (`app/tracing.py`, contextvar trace, JSONL + Langfuse ingestion API), not
  the Langfuse SDK or LangChain callbacks: it covers LLM calls outside LangGraph (judge, RAGAS) and works
  with no account.
- RAGAS is a second opinion, not the metric: its faithfulness agrees with the judge (Spearman 0.86),
  its factual correctness is too literal for 10-K answers (rounding, dates, extra detail) and was
  rejected as the correctness metric. RAGAS calls go through FinRAG's cached `LLM`, never an OpenAI client.
- Model routing by plan intent: trend/comparison to Groq gpt-oss-120b (local fallback), everything else
  local. Kept after the v2 run (judged correctness 0.764 → 0.865 by the independent judge). A routed run is judged by a second model family (qwen3.8-27b on Groq) because the default judge
  is the generator's own model. Gemini dropped as a judge: free tier too unreliable (503/timeouts).
- Agent memory is an explicit per-thread turn list passed into a stateless LangGraph graph, not a
  checkpointer (see "Agent graph v0"). Standalone questions mid-conversation skip the LLM rewrite.
- XBRL facts come only from the fiscal year's own 10-K (accession + period end + ~1-year duration;
  never the `fy` field); YoY change from the same filing. They are added next to retrieved text,
  never instead of it (company definitions differ from GAAP line items). See "XBRL tool v0".
- Retrieval plan: MD&A section prior +0.05 for metric questions (soft, never a filter); rerank pool
  stays 30 per sub-query (15 halves latency for -0.03 context recall). See "Retrieval plan v0".

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
- Docker (Phase 9): `docker compose up --build` = API + UI + Postgres (models on CPU inside: reranked
  search ~5 s). First start ~5 min (model download into the `hfcache` volume), then ~20 s. Stop the
  host API first (port 8010). `docker compose down` when done (RAM; volumes are kept).
- Postgres (Phase 9): `docker compose up -d db` (Docker Desktop must be running), host port 5433,
  data in the `pgdata` volume. Load or refresh with `python -m app.retrieval.pg_store`. Scratch db
  for the integration test: `finrag_test`. Stop with `docker compose stop db` when not needed (RAM).
- Web app: API on **port 8010** (port 8000 on the MacBook is taken by another local app).
  Node 24 / npm 11 on the MacBook. Startup loads the retriever and runs one warm-up search
  (~15-20 s); reranked searches take ~1.3-2.5 s, plain hybrid ~10 ms.
- UI checks: `python scripts/ui_screenshot.py URL out.png WIDTH HEIGHT SELECTOR` (Chrome DevTools,
  waits for the selector, e.g. `.answer__text, .answer__abstain`; emulates phone widths directly).
  Chrome's `--screenshot` now fires before the page's fetches settle (captures the loading state), and
  `--virtual-time-budget` hangs on this page.

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
- **2026-10-08 (MacBook M4):** Groq gpt-oss-120b baseline: 52/84 questions before the daily cap
  (false abstention 0.000, citation hit 0.981 vs Ollama 0.058 / 0.882 on the same questions).
  Live-tested `/api/answer` and the answer panel (repaired note, withheld answer, abstention).
  Ticked Phase 5; planned Phase 6.
- **2026-10-08 (MacBook M4):** Phase 6 step 1: query analyzer (`app/agent/`): rule-based
  companies/years/sections, follow-up carry-over + LLM standalone rewrite, early out-of-range
  refusal; `run_analyzer_eval.py`. Analyzer filters match gold retrieval (recall@5 0.914 both,
  MRR 0.908 vs 0.918); 4/10 unanswerable refused early, 0 false refusals. +20 tests (112 total).
  Groq retry added one question (53/84). Not committed yet.
- **2026-10-14 (MacBook M4):** Groq baseline v1 finished on a fresh daily quota (84/84, 0 errors:
  false abstention 0.014, citation hit 0.959, evidence recall 0.884). Phase 6 step 2: retrieval plan
  (`app/agent/plan.py`: intent, sub-queries, quotas, MD&A prior; `Retriever.search_many` batched
  reranking with `score_pairs`; `run_plan_eval.py`, `reports/plan_v0.md`). Prior 0.05: recall@5
  0.914 → 0.921, MRR 0.918 → 0.927, trend recall@5 0.597 → 0.639; quotas at k=5: context recall
  0.914 → 0.949. Batching -7% latency only; the rerank pool size is the real latency knob. +11 tests
  (123 total). Not committed yet.
- **2026-10-26 (MacBook M4):** Phase 6 step 3: XBRL company-facts tool (`app/agent/xbrl.py`:
  download + cache, 13 metrics with concept fallbacks, own-filing fact selection, next-10-K
  comparative fallback, YoY change, facts as chunks/sources, `detect_metrics`), coverage CLI,
  `run_xbrl_eval` (`reports/xbrl_v0.md`: 459/520 cells, 55/72 gold figures where it fires).
  Verifier now reads `$37.7B`/`$450M`. `Source` formats XBRL citations. Real-data NVDA fixture;
  148 tests passing. Disk at 98% (4.2 GB free).
- **2026-10-26 (MacBook M4):** Phase 6 step 4: LangGraph agent (`app/agent/graph.py`: analyze →
  refuse | retrieve ∥ xbrl → generate → verify → respond, widen retry, `ConversationMemory`, CLI),
  `Answerer` split into generate/finalize, XBRL prompt rule only with facts, `langgraph` added to
  requirements. Real 5-turn run on granite4.1:3b found two analyzer bugs (out-of-range year inherited
  mid-conversation; LLM rewrite on standalone questions), both fixed with tests. Analyzer report
  regenerated (it was overwritten by a `--no-retrieval` run; numbers unchanged). 157 tests passing.
- **2026-10-26 (MacBook M4):** Phase 6 step 5, Phase 6 done: `run_agent_eval` (agent vs agent without
  XBRL vs the gold-filter v1 baseline; XBRL-aware citation hit; definition-mismatch table; a
  `--limit` run writes `agent_v0_smoke` so it can't overwrite the report). Agent = gold filters on
  false abstention (0.054), citation hit incl. XBRL 0.878; found U04 live-price leak and the T11/T12
  definition conflicts. Analyzer report regenerated, identical. 158 tests passing.
- **2026-10-26 (MacBook M4):** Phase 7 step 1: LLM judge (`judge.py`: correctness vs reference +
  per-claim faithfulness, Groq gpt-oss-120b, cited sources only), `run_judge_eval` (rule-scored
  abstentions, answers re-run from cache and checked against agent_v0, label agreement, "passed the
  verifier but wrong" table), 22 hand labels. Judge agrees 0.86 / 1.00 with labels; agent answers
  0.771 correct (answered), trend 0.250; 17 verifier-passed answers are wrong. 161 tests passing.
- **2026-10-26 (MacBook M4):** Phase 7 step 2: XBRL series table, trend/comparison intent rules,
  live-data scope rule (+11 tests, 172 passing). Judged correctness 0.730 → 0.777, trend 0.250 → 0.542,
  abstention recall 1.000. A stricter rule variant was measured and rejected (judge_v1_strict).
  Judge label agreement now only counts answers identical to v0. Background runs were killed once by
  a Claude Code restart; rerun from cache.
- **2026-10-26 (MacBook M4, evening):** Phase 7 step 3 prepared (gpt-oss quota spent, run deferred):
  intent-based model routing in the graph and eval runners, `--judge-model` for a second Groq judge,
  `compare_judges.py`. Gemini failed again as a judge (503/timeouts). qwen3.8-27b judged all v1
  answers: agrees with gpt-oss 0.91 exact / 0.93 binary and with the still-valid labels 11/11.
  174 tests passing.
- **2026-10-27 (MacBook M4):** Phase 7 step 3 run: routed judge eval (gpt-oss judge), a network outage
  made 5 routed calls fall back to Ollama, rerun filled them; qwen judge on the same answers; agent_v2;
  judge_agreement_v2. Judged correctness 0.764 → 0.865 (qwen), trend 0.792, comparison 1.000, false
  abstention 0.041: routing kept. Judge reports now record answering and judge models; agent report
  title and uncached latency fixed. Groq latency net of rate-limit waits p50 ~9 s. 174 tests passing.
- **2026-10-29 (MacBook M4):** Phase 7 step 4: RAGAS second opinion. `ragas_metrics.py` (RAGAS 0.4.3
  collection metrics over FinRAG's cached `LLM` via an `InstructorBaseRagasLLM` adapter; factual
  correctness split into precision / coverage / f1), `run_ragas_eval.py` (vs judge_v2_qwen, rank
  correlation, per-grade means, disagreements), 4 tests (178 passing). Full run stopped at the user's
  request (too slow on the free tier, ~30 s/question); 26-question stratified sample instead.
  Faithfulness agrees with the judge (0.813 vs 0.808, Spearman 0.86); factual correctness rejects
  correct answers (f1 0.294 vs 0.808). Judge kept as the correctness metric.
- **2026-10-30 (MacBook M4):** Phase 7 step 5: tracing. `app/tracing.py` (contextvar traces, node spans,
  LLM generations recorded in `LLM.generate`, JSONL + Langfuse ingestion sinks, p50/p95 summary CLI),
  graph nodes traced, `AgentTurn.trace`, `run_agent_eval` traces per question, Langfuse settings in
  config/.env.example, `data/traces/` gitignored, 5 tests (183 passing). Traced routed run: 84/84
  answers identical, retrieval p50 1.5 s but trend 6.6 s / comparison 4.5 s. No Langfuse keys yet:
  export tested against a mock only.
- **2026-10-30 (MacBook M4):** vector index comparison for interviews: `app/retrieval/index_benchmark.py`
  (Flat, IVF-Flat, IVF-SQ8, IVF-PQ, PQ, HNSW, LSH on the real 17.6k vectors and 84 golden queries,
  recall@10 unfiltered and under gold filters), `reports/index_benchmark.md`, and a "Vector index
  choice" section in `docs/ARCHITECTURE.md` comparing every index family. Exact search 0.36 ms; ANN
  filtered recall is the weak spot. 184 tests passing.
- **2026-10-30 (MacBook M4):** Phase 7 step 6, Phase 7 done: `build_eval_report.py` (retrieval ablation from
  per-question metrics, matches retrieval_v0.md; answer ablation v1 → agent → XBRL → trend fixes → routing
  with both judges; per-category judged correctness; evaluator agreement incl. judge-vs-judge computed with
  `compare_judges`; latency/cost from traces; known limits) → `reports/eval_v1.md`, 5 tests (189 passing).
  Checking the narrative against the data corrected two claims (T11 is now correct; v0/v2 headline
  compares judges explicitly).
- **2026-10-30 (MacBook M4):** Phase 8 step 1: `/api/answer` runs the routed agent (`LockedRetriever`,
  `merge_filters` for UI filters, `thread_id` memory, XBRL facts as sources, read-as/intent/steps/facts in
  the response), `answer_route` setting, UI thread id + "New conversation" + read-as line + XBRL chips,
  `scripts/ui_screenshot.py`. 5 new API tests (193 passing). Live check of lookup, routed trend, follow-up
  rewrite + XBRL, live-price refusal; screenshots desktop/phone found and fixed a clipped header on phones.
- **2026-10-30 (MacBook M4):** Phase 8 step 2, Phase 8 done: `FinRAGAgent.stream`/`stream_ask` (run and ask
  built on it), `/api/answer/stream` SSE endpoint with per-node payloads, shared `answer_response`, UI
  streaming client with fallback and a live stage list; 2 streaming tests (195 passing). Live-checked with
  curl timestamps and screenshots (desktop, phone, refusal, completed answer).
- **2026-10-30 (MacBook M4):** Phase 9 step 1: Postgres + pgvector backend (`pg_store.py`: schema, COPY
  loader, chunk loading, `PgVectorIndex`; `VECTOR_BACKEND`/`DATABASE_URL` settings; `docker-compose.yml`
  db service; filters passed to the dense index). Retrieval identical to FAISS (740/740 per question and
  mode, 168/168 dense top-10). 4 tests incl. a real-Postgres round trip (198 passing + 1 skipped). Found
  retrieval_v0 predates the gold review (current gold: recall@5 0.891, MRR 0.933).
- **2026-10-30 (MacBook M4):** Phase 9 step 2: `Dockerfile` (node build + python slim, CPU torch, serving
  deps only, non-root, healthcheck), `.dockerignore`, compose `api` service (pgvector, host Ollama, data
  and model volumes). Verified health, search, a streamed uncached answer, cache writes, UI screenshot;
  image 2.13 GB, cold start 320 s / warm 17 s, CPU rerank ~5 s. Import-boundary test (199 passing + 1 skipped).
  README: Docker run instructions and the answer endpoints.
- **2026-10-30 (MacBook M4):** Phase 9 step 3: GitHub Actions CI (tests with a pgvector service, frontend
  lint/build, eval gate), `check_gate.py` + `reports/gate.json` (10 checks, 10/10 pass), 9 gate tests
  (208 passing + 1 skipped locally; 209 in the clean-container dry run incl. pgvector). Not pushed: the gh
  token needs the `workflow` scope.
- **2026-10-30 (MacBook M4):** while blocked on the `workflow` scope: retrieval eval rerun with the reviewed
  gold (`retrieval_v1`: recall@5 0.891, MRR 0.933), gate and eval_v1 switched to it (10/10 pass), report
  title from the output name, eval_v1 prose numbers computed instead of hard-coded. 208 passing + 1 skipped.
- **2026-10-30 (MacBook M4):** first CI run on GitHub: gate + frontend green, 1 test failed on x86 only
  (tie broken by candidate order); fixture changed to remove the tie. 208 passing + 1 skipped locally.
- **2026-10-30 (MacBook M4):** CI green on GitHub after the tie fix (run 41048182690: 209 passed incl. the
  pgvector integration test, frontend, gate 10/10). Phase 9 done: README CI badge, Phase 10 planned
  (earnings releases from 8-K Ex-99.1).
- **2026-10-30 (MacBook M4):** Phase 10 step 1: earnings release downloader (8-K Item 2.02 Ex-99.1, fiscal
  quarter from 10-Q/10-K period ends, content check among several 2.02 8-Ks). 160/160 releases; Tesla's
  deliveries reports and NVIDIA's preliminary revenue 8-K caught and excluded. 5 tests (213 passing).
  CLAUDE.md setup gains the download line.
- **2026-10-30 (MacBook M4):** demo run for the user: native API on :8010 (health 17,602 chunks; streamed
  NVIDIA FY2022-25 revenue trend answered by gpt-oss-120b, 4 XBRL facts, 5/5 verified; UI screenshot ok),
  then stopped. Earnings releases are downloaded but not yet searchable (Phase 10 step 2-3).
- **2026-11-02 (MacBook M4):** Phase 10 step 2: `earnings_pipeline.py`, 5,571 chunks from 160 releases, 0 over
  the token limit. Fixed the SGML wrapper (each release parsed as one block) and Tesla's flat slide text
  (period header repeated on every piece). 10-K chunks unchanged (17,602 equal). Found that 5 Tesla releases
  have statements only as images, correcting step 1's claim. 227 tests with real Postgres. Not committed.
- **2026-11-02 (MacBook M4):** Phase 10 step 3: releases merged (23,173 chunks), quarter/form filters, one BM25 per form,
  analyzer rules, no XBRL on quarterly questions, release prompt rules and citation repair, API + UI filters. 10-K path
  unchanged: retrieval 740/740, answers 84/84. A live run caught a wrong guidance figure the verifier passed, fixed. 265 tests + 2 skipped
  without Postgres; those 2 passed on a scratch db before the last API-only edit. pgvector parity on a scratch db; main db not reloaded. Not committed.
- **2026-11-02 (MacBook M4):** Phase 10 step 4: earnings golden set (35), evals, two judges, judge sensitivity test, 10 new gate checks. No false
  abstentions, correctness 1.000 on easy questions, abstention recall 0.75 (2 confident wrong answers); a prompt fix was tried and reverted. Local dashboard
  added at the user's request (`python -m app.dashboard`). 281 tests pass + 2 skipped without Postgres; those 2 pass on a scratch db. Gate 20/20. Not committed.
- **2026-11-02 (MacBook M4):** Phase 10 step 5: verifier checks for relabelled figures fixed EU6 and EU7. 12 fresh questions found a new wrong answer (E29, wrong period column), now in the golden set: correctness 0.970, abstention recall 1.000 on 47 questions. 10-K answers 84/84. Gate 20/20. Not committed.
