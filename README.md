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

# Evaluate retrieval against the golden set (84 questions) -> reports/retrieval_v0.md
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

API: `GET /api/health`, `GET /api/meta`, `POST /api/search` (schemas in `app/api/schemas.py`).

## Status

- [x] Phase 1: EDGAR downloader (40 filings, manifest with source URLs)
- [x] Phase 2: Parsing (pages, sections, tables) and chunking (17.6k chunks, quality report)
- [x] Phase 3: Indexing (embeddings + FAISS, BM25), hybrid retrieval, cross-encoder reranking (12/12 smoke queries in all modes; 1.3 s reranked p50 on Apple M4)
- [x] Phase 4: Evaluation harness v0 (84-question golden set, Recall@K/MRR/nDCG, ablations): hybrid + rerank recall@5 0.884, MRR 0.920 ([report](reports/retrieval_v0.md))
- [x] Phase 5: Grounded generation with verified page citations and abstention: local 3B model false abstention 0.054, citation hit 0.863, all unanswerable refused ([report](reports/generation_v1_ollama.md)); Groq gpt-oss-120b false abstention 0.014, citation hit 0.959 on all 84 questions ([report](reports/generation_v1_groq.md))
- [x] Phase 6: LangGraph agent (query analysis, retrieval plan, conversational memory, XBRL facts tool): with no gold filters it matches the gold-filter run on false abstention (0.054) and reaches citation hit 0.878 counting XBRL facts ([report](reports/agent_v0.md); [analyzer](reports/analyzer_v0.md), [plan](reports/plan_v0.md), [XBRL](reports/xbrl_v0.md))
- [ ] Phase 7: Full evaluation (RAGAS, Langfuse tracing, latency/cost) (in progress: LLM judge agrees with hand labels 0.86 and finds the agent's answers 0.730 correct ([report](reports/judge_v0.md)); XBRL series tables and intent prompt rules lift that to 0.777, trend 0.250 → 0.542 ([report](reports/judge_v1.md)); a second judge from another model family agrees 0.91 ([report](reports/judge_agreement_v1.md)); routing trend/comparison questions to gpt-oss-120b lifts it to 0.865 (trend 0.792, comparison 1.000 by the independent judge) with fewer abstentions ([report](reports/judge_v2_qwen.md), [agreement](reports/judge_agreement_v2.md)); RAGAS as a second opinion on 26 answers agrees on faithfulness (0.81 vs 0.81, Spearman 0.86) but its literal factual-correctness NLI rejects correct answers (f1 0.29 vs judge 0.81), so the judge stays the correctness metric ([report](reports/ragas_v0.md)); tracing and the final report left)
- [ ] Phase 8: Serving: FastAPI + glassmorphism React UI (search and answer UI done; streaming left)
- [ ] Phase 9: Postgres/pgvector, Docker Compose, CI eval gate
