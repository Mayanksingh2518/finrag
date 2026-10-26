# FinRAG Progress

Single source of truth for project state. Update this file at the end of every work session.

## Current status

- **Last completed:** Phase 6 (LangGraph agent), finished with step 5, the agent-mode eval
  (`reports/agent_v0.md`): with **no gold filters or rewrite**, the agent matches the gold-filter v1
  run on false abstention (0.054 = 0.054) and figure recall (0.573 vs 0.583), and beats it on
  citation hit counting XBRL (0.878 vs 0.863); abstention recall drops 1.000 → 0.900 (U04).
- **In progress:** Phase 7 (full evaluation): steps 1-2 done. LLM judge (`reports/judge_v0.md`,
  agrees with hand labels 0.86 / 1.00); trend fixes (`reports/judge_v1.md`): XBRL series table +
  intent prompt rules + live-data scope rule lift judged correctness 0.730 → 0.777 (all answerable),
  **trend 0.250 → 0.542**, abstention recall 0.900 → 1.000.
  Phase 8 started early (FastAPI + React UI; streaming and `/api/ask` left).
  Phase 8 started early (FastAPI + React UI over retrieval and answers; streaming left).
- **Next up:** Phase 7 step 3: **run** the Groq routing eval (code, tests and a second judge are ready;
  needs a fresh gpt-oss-120b daily quota, i.e. 2026-10-27 or later), see "Next task in detail".
- **Resume here (2026-10-26, evening):** Phase 7 steps 1-2 committed (4202399). Not committed yet:
  model routing (`FinRAGAgent(routed_llm=...)`, `--route` flags), the second judge (`--judge-model`,
  `compare_judges.py`, `reports/judge_v1_qwen.*`, `judge_agreement_v1.md`). Groq gpt-oss-120b: ~160k
  of 200k used on 2026-10-26; qwen3.8-27b: ~90k used (separate per-model quota).
- **Disk nearly full (MacBook, 2026-10-26):** 2.2 GB free (was 4.2 GB at the start of the day) of 228 GB (98%). Free space before
  long evals or model pulls; Ollama models are several GB each.
- **Disk/memory warning (MacBook, 16 GB RAM):** the disk once filled because swap grew to 10 GB
  while the API server, an eval, tests and Ollama all held models at once. Run one model-loading
  process at a time and stop the API server during evals.
- **Active machine:** MacBook M4 (setup done 2026-10-07: venv, data, embedding cache)
- **Last updated:** 2026-10-26 (Phase 7 step 3 prepared: routing + second judge)

## Phase checklist

- [x] **Phase 1: Data acquisition.** EDGAR 10-K downloader, 40 filings (10 companies × FY2022–2025), manifest
- [x] **Phase 2: Parsing and chunking.** 17,602 chunks (14,975 text / 2,627 table), 0 over the 512-token limit, all core items found in all 40 filings, 96.8% of chunks carry a printed page number
- [x] **Phase 3: Indexing and retrieval.** Local bge-small embeddings + FAISS, BM25, RRF hybrid, metadata filters, bge-reranker-base cross-encoder; 12/12 smoke queries in all 4 modes; 33 tests
- [x] **Phase 4: Evaluation v0.** 84-question golden set (quote-verified pages), Recall@K / MRR / nDCG, 4 modes × filters on/off, reranker ablations, decomposition preview; hybrid_rerank recall@5 0.884, MRR 0.920; 48 tests
- [x] **Phase 5: Grounded generation.** Structured output, page citations, citation verifier with context-checked repair, abstention, confidence; Ollama granite4.1:3b false abstention 0.054, citation hit 0.863, abstention recall 1.000; Groq gpt-oss-120b false abstention 0.014, citation hit 0.959 (84 q); 92 tests
- [x] **Phase 6: LangGraph agent.** Rule-based analyzer + LLM follow-up rewrite, retrieval plan (quotas, MD&A prior), XBRL company-facts tool, LangGraph graph with memory and a widen retry; agent with no gold filters: false abstention 0.054 (= gold-filter run), citation hit incl. XBRL 0.878, figure recall 0.573; 158 tests
- [ ] **Phase 7: Full evaluation.** LLM judge done (agrees with hand labels 0.86; agent correctness 0.771 answered, trend 0.250); trend fixes lift judged correctness 0.730 → 0.777 (trend 0.250 → 0.542); next: model routing, RAGAS, Langfuse tracing, latency/cost per stage
- [ ] **Phase 8: Serving.** FastAPI + React/Vite glassmorphism UI (user's choice over Streamlit). Done: `/api/health`, `/api/meta`, `/api/search`, search UI with filters, citations, tables, latency. `/api/answer` with the answer panel (live-tested 2026-10-08). Left: streaming answers
- [ ] **Phase 9: Production.** Postgres + pgvector (Pinecone optional), Docker Compose, CI with eval regression gate
- [ ] **Phase 10: Expansion.** Earnings releases (8-K Ex-99.1), investor presentations (PDF parser)

## Next task in detail: Phase 7 (full evaluation)

Goal: measure what the deterministic verifier can't (whether an answer is *right*), trace every
stage, and fix what that shows. Zero cost: free-tier judge, every call cached.

1. ~~LLM judge~~ **done 2026-10-26** (`app/evaluation/judge.py`; see "Judge v0" below).
2. ~~Trend answers~~ **done 2026-10-26** (see "Trend fixes v1" below).
3. **Model routing for trend/comparison (next: run it)**. Built and tested 2026-10-26 (see "Routing
   and second judge" below); only the run is left, on a fresh gpt-oss-120b daily quota:
   ```bash
   # 1. routed answers (24 trend/comparison questions by gpt-oss-120b, ~85k tokens) judged by gpt-oss (~40k)
   python -m app.evaluation.run_judge_eval --route --out reports/judge_v2
   # 2. same answers judged by qwen (no self-preference; separate quota; generation now cached)
   python -m app.evaluation.run_judge_eval --route --judge-providers groq --judge-model qwen/qwen3.8-27b \
       --out reports/judge_v2_qwen
   # 3. agent metrics (abstention, citations, latency) for the routed config, all cached by now
   python -m app.evaluation.run_agent_eval --configs agent_routed --out reports/agent_v2
   python -m app.evaluation.compare_judges reports/judge_v2.json reports/judge_v2_qwen.json \
       --out reports/judge_agreement_v2.md
   ```
   Decide with **qwen's** scores (v1_qwen → v2_qwen) and check gpt-oss agrees in direction: keep
   routing if trend/comparison improve without new abstentions. If Groq hits its daily cap mid-run,
   the routed LLM falls back to Ollama for the rest (those answers equal v1's): rerun the next day,
   everything done so far is cached. Record Groq latency per routed question (it is not cached on the
   first run) and the serving cost: the free tier allows ~50 routed questions/day for the app.
4. **RAGAS** as a second opinion on the same records, only if it runs within the free tiers.
5. **Tracing**: Langfuse callback on the graph + LLM calls (per-node latency, tokens). **Needs the
   user's keys** (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` in `.env`); a no-op
   without them.
6. Report `reports/eval_v1.md`: ablation table (BM25 / dense / hybrid / +rerank / +analysis / +plan /
   +XBRL) with retrieval and judged answer metrics, latency p50/p95 per node.

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

- Source = SEC EDGAR HTML, not IR-site PDFs (stable URLs, structured tables, exact page breaks).
- `fiscal_year` = year of the period end (matches company labels: NVDA FY2025 ended 2025-01-26).
- Original 10-K only; 10-K/A excluded.
- Dependencies are added to `requirements.txt` phase by phase.
- Build eval v0 (Phase 4) before generation so retrieval tuning is measured.
- Multi-entity questions use per-(company, year) decomposition with per-entity quotas (Phase 4 data).
- Trend/comparison prompts get intent rules and an XBRL series table with directions computed in
  code; prohibitive wording ("never compute...") was tested and rejected (more abstentions).
- Live market data (current share price, market cap now) is out of scope at the analyzer.
- Model routing by plan intent: trend/comparison to Groq gpt-oss-120b (local fallback), everything else
  local. A routed run is judged by a second model family (qwen3.8-27b on Groq) because the default judge
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
