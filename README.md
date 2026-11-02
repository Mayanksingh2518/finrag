# FinRAG: Financial Intelligence RAG Agent

[![CI](https://github.com/Mayanksingh2518/finrag/actions/workflows/ci.yml/badge.svg)](https://github.com/Mayanksingh2518/finrag/actions/workflows/ci.yml)

Ask questions about SEC filings and get answers with citations you can check, or a refusal when the evidence isn't there.
FinRAG is an agentic RAG system over 40 annual reports (10-K) and 160 quarterly earnings releases from 10 large-cap companies
(AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, V, MA), fiscal years 2022–2025. It runs at zero cost on local models and free tiers.

Every result below comes from a committed report, and a CI gate fails the build if a report drops below its floor.

## Results

| | Annual reports ([report](reports/eval_v1.md)) | Earnings releases ([report](reports/eval_earnings_v0.md)) |
|---|---|---|
| Golden set | 84 questions | 60 questions |
| Judged correctness, answerable questions | 0.865 | 0.870 |
| Unanswerable questions refused | 10 of 10 | 14 of 14 |
| Answerable questions wrongly refused | 0.041 | 0.065 |
| Retrieval recall@5 / MRR, with gold filters | 0.891 / 0.933 | 0.886 / 0.699 |

Correctness is graded by an LLM judge and cross-checked by a second model family. **The two columns aren't comparable:** the earnings set is mostly stated figures. Both sets and their labels were written alongside the system, not independently.

Known limits, measured and written up: the local 3B model sometimes misreads multi-period tables and can still give a wrong answer with a valid citation (a larger model got 14 of 14 such questions right in a small test,
and is behind a switch until it has a full evaluation). Details are in the [earnings report](reports/eval_earnings_v0.md).

## How it works

- **Retrieval:** dense embeddings and BM25 fused with RRF, then a cross-encoder reranker, with metadata filters and one sub-query per company, year and quarter.
- **Agent:** a LangGraph graph reads the question, keeps conversation memory, retrieves, looks up exact XBRL facts, generates, verifies, and retries wider when it has to abstain.
- **Verification in code:** every claim must cite a source that states its figures. On earnings tables the verifier also reads column headers, to reject a real figure taken from the wrong period.
- **Evaluation:** a golden set with quote-verified evidence, ablations, two LLM judges validated on hand labels and on deliberately wrong answers, and a regression gate in CI.
- **Serving:** FastAPI, a React UI with live agent progress, Postgres + pgvector (identical retrieval to FAISS), Docker Compose and GitHub Actions.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and its trade-offs.

## Quickstart

Python 3.11+. Everything downloaded or generated is reproducible, and SEC data is free.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv/Scripts/activate
pip install torch               # Windows/Linux CPU: add --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env            # set SEC_USER_AGENT to include your email

# Data (cached and idempotent)
python -m app.ingestion.sec_downloader --years 2022 2023 2024 2025       # 40 10-Ks, ~2 min
python -m app.ingestion.pipeline                                         # parse and chunk, ~1 min
python -m app.agent.xbrl --download                                      # XBRL company facts, ~45 MB
python -m app.ingestion.earnings_downloader --years 2022 2023 2024 2025  # 160 earnings releases, ~3 min
python -m app.ingestion.earnings_pipeline                                # parse and chunk
python -m app.retrieval.build_index                                      # embeddings (local; uses Apple GPU / CUDA if available)

pytest
```

**To get answers,** give it an LLM: a local one (`ollama pull granite4.1:3b`), a free [Groq key](https://console.groq.com/keys) in `.env`, or both. Search works without one. Trend and comparison questions go to Groq when a key is set.

```bash
# Search: BM25 / dense / hybrid / hybrid + reranker, with metadata filters
python -m app.retrieval.search_cli "Why did international transaction revenue change?" --tickers V --years 2025

# Ask the agent, as one conversation
python -m app.agent.graph --route "What was NVIDIA's revenue in fiscal 2025?" "And in Q3?"

# Evaluate retrieval against the golden sets -> reports/
python -m app.evaluation.run_retrieval_eval
python -m app.evaluation.run_retrieval_eval --golden data/eval/golden_earnings_v0.jsonl --no-ablations --out reports/retrieval_earnings_v0
python -m app.evaluation.check_gate            # the CI regression gate, over the committed reports
```

## Web app

A React + Vite + TypeScript UI over a FastAPI backend: cited answers that stream live progress per agent step, plus evidence search with company, year, quarter, document and section filters,
a retrieval-mode switch, rendered tables, per-stage scores and latency, and shareable URLs.

```bash
cd frontend && npm install && npm run build && cd ..   # once, or after UI changes
uvicorn app.api.main:app --port 8010                   # API + built UI at http://localhost:8010

# UI development with hot reload (API must be running on :8010)
cd frontend && npm run dev                             # http://localhost:5173
```

API: `GET /api/health`, `GET /api/meta`, `POST /api/search`, `POST /api/answer` (the LangGraph agent),
`POST /api/answer/stream` (the same as Server-Sent Events, one per agent step); schemas in `app/api/schemas.py`.

### Local dashboard

Token usage, logs and agent traces on one page, from plain files. It loads no models, so it can stay open during an eval.

```bash
python -m app.dashboard --log <file>   # http://127.0.0.1:8020
```

### With Docker (API + UI + Postgres/pgvector)

After the Quickstart's data steps (the container mounts `data/`; Ollama, if used, stays on the host):

```bash
docker compose up -d db && python -m app.retrieval.pg_store   # once: chunks + embeddings into Postgres
docker compose up --build                                     # http://127.0.0.1:8010
```

The first start downloads the embedding and reranker models (~5 min); later starts take ~20 s. In
the container the models run on CPU, so a reranked search takes ~5 s instead of ~1.5 s on Apple GPU.

## Status

- [x] Phase 1: EDGAR downloader (40 filings, manifest with source URLs)
- [x] Phase 2: Parsing (pages, sections, tables) and chunking (17.6k chunks, quality report)
- [x] Phase 3: Indexing (embeddings + FAISS, BM25), hybrid retrieval, cross-encoder reranking (12/12 smoke queries in all modes; 1.3 s reranked p50 on Apple M4)
- [x] Phase 4: Evaluation harness v0 (84-question golden set, Recall@K/MRR/nDCG, ablations): hybrid + rerank recall@5 0.884, MRR 0.920 ([report](reports/retrieval_v0.md)); 0.891 / 0.933 with the reviewed gold labels ([v1](reports/retrieval_v1.md))
- [x] Phase 5: Grounded generation with verified page citations and abstention: local 3B model false abstention 0.054, citation hit 0.863, all unanswerable refused ([report](reports/generation_v1_ollama.md)); Groq gpt-oss-120b false abstention 0.014, citation hit 0.959 on all 84 questions ([report](reports/generation_v1_groq.md))
- [x] Phase 6: LangGraph agent (query analysis, retrieval plan, conversational memory, XBRL facts tool): with no gold filters it matches the gold-filter run on false abstention (0.054) and reaches citation hit 0.878 counting XBRL facts ([report](reports/agent_v0.md); [analyzer](reports/analyzer_v0.md), [plan](reports/plan_v0.md), [XBRL](reports/xbrl_v0.md))
- [x] Phase 7: Full evaluation: **[summary report](reports/eval_v1.md)**. LLM judge validated on hand labels and by a second, independent judge; XBRL series tables, intent rules and routing trend/comparison questions to gpt-oss-120b lift judged correctness 0.730 → 0.865 (trend 0.250 → 0.792, comparison 0.667 → 1.000); RAGAS corroborates faithfulness but is too literal for correctness ([report](reports/ragas_v0.md)); per-turn tracing (JSONL, Langfuse) and per-node latency; vector index benchmark ([report](reports/index_benchmark.md))
- [x] Phase 8: Serving: FastAPI + glassmorphism React UI; answers come from the evaluated agent (routing, XBRL facts, conversation memory per thread, traces), stream live progress per agent step (SSE) and show how the question was read
- [x] Phase 9: Production: Postgres + pgvector backend with identical retrieval results to FAISS (`VECTOR_BACKEND=pgvector`); `docker compose up --build` runs API + UI + Postgres; GitHub Actions CI runs the test suite (incl. real Postgres), the UI lint/build and an eval regression gate over the committed reports ([gate](reports/gate.json))
- [x] Phase 10: Quarterly earnings releases (8-K Exhibit 99.1): 160 releases, 5.6k chunks, searched when a question names a quarter, with 10-K results unchanged (cached answers 84/84). **[Evaluation](reports/eval_earnings_v0.md)** on 60 questions: judged correctness 0.870, 14 of 14 refusals; the local model misreads some table columns, and a larger model got all 14 table questions right in a small test. Investor presentations left out: most aren't on EDGAR
