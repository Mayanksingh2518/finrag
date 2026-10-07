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
pip install -r requirements.txt
cp .env.example .env            # set SEC_USER_AGENT to include your email

# Download 10-Ks from SEC EDGAR (cached and idempotent)
python -m app.ingestion.sec_downloader --years 2025                 # 10 filings
python -m app.ingestion.sec_downloader --years 2022 2023 2024 2025  # 40 filings

# Parse, section and chunk all filings -> data/processed/ (chunks, pages, quality report)
python -m app.ingestion.pipeline

pytest
```

## Status

- [x] Phase 1: EDGAR downloader (40 filings, manifest with source URLs)
- [x] Phase 2: Parsing (pages, sections, tables) and chunking (17.6k chunks, quality report)
- [ ] Phase 3: Indexing (embeddings + FAISS, BM25), hybrid retrieval, reranking
- [ ] Phase 4: Evaluation harness v0 (golden set, retrieval metrics, ablations)
- [ ] Phase 5: Grounded generation with citations and abstention
- [ ] Phase 6: LangGraph agent (query analysis, decomposition, memory, XBRL facts tool)
- [ ] Phase 7: Full evaluation (RAGAS, Langfuse tracing, latency/cost)
- [ ] Phase 8: FastAPI + Streamlit
- [ ] Phase 9: Postgres/pgvector, Docker Compose, CI eval gate
