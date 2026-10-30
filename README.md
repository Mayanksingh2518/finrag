# FinRAG: Financial Intelligence RAG Agent

Agentic retrieval-augmented generation over SEC 10-K filings for 10 large-cap companies
(AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, V, MA) across fiscal years 2022–2025.
It answers cross-company and multi-year questions with page-level citations and abstains
when the evidence doesn't support an answer.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.

## Quickstart

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install torch               # Windows/Linux CPU: add --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env            # set SEC_USER_AGENT to include your email

# Download 10-Ks from SEC EDGAR (cached and idempotent)
python -m app.ingestion.sec_downloader --years 2025                 # 10 filings
python -m app.ingestion.sec_downloader --years 2022 2023 2024 2025  # 40 filings

# Parse, section and chunk all filings -> data/processed/ (chunks, pages, quality report)
python -m app.ingestion.pipeline

# Embed chunks for dense retrieval (local bge-small; uses Apple GPU / CUDA if available)
python -m app.retrieval.build_index

# Search: BM25 / dense / hybrid / hybrid + reranker, with metadata filters
python -m app.retrieval.search_cli "Why did international transaction revenue change?" --tickers V --years 2025

# Evaluate retrieval against the golden set (84 questions) -> reports/retrieval_v1.md
python -m app.evaluation.build_golden          # resolve gold pages from quotes + validate
python -m app.evaluation.run_retrieval_eval    # all modes, filters on/off, reranker ablations

pytest
```

## Web app

A glassmorphism web UI (React + Vite + TypeScript) over a FastAPI backend: search with
company/year/section filters, retrieval-mode switch, per-entity decomposition, evidence cards
with page citations, rendered tables, per-stage scores and latency, and shareable URLs.

```bash
cd frontend && npm install && npm run build && cd ..   # once, or after UI changes
uvicorn app.api.main:app --port 8010                   # API + built UI at http://localhost:8010

# UI development with hot reload (API must be running on :8010)
cd frontend && npm run dev                             # http://localhost:5173
```

API: `GET /api/health`, `GET /api/meta`, `POST /api/search`, `POST /api/answer` (the LangGraph agent),
`POST /api/answer/stream` (the same as Server-Sent Events, one per agent step); schemas in `app/api/schemas.py`.

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
- [ ] Phase 9: Postgres/pgvector, Docker Compose, CI eval gate (built: pgvector backend with identical retrieval results to FAISS; `docker compose up` runs API + UI + Postgres; GitHub Actions runs tests with Postgres, the UI build and an eval regression gate over the committed reports; first CI run pending)
