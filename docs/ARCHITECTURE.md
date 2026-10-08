# FinRAG Architecture

## Scope

An agentic RAG system over SEC annual reports (Form 10-K) for 10 companies × 4 fiscal
years (FY2022–FY2025, 40 filings). It answers multi-company, multi-year questions with
page-level citations, refuses when evidence is insufficient, and is measured by an
evaluation harness with ablations.

**In scope (v1):** 10-K ingestion, hybrid retrieval, reranking, query analysis and
decomposition, conversational follow-ups, grounded generation with citations and
abstention, structured XBRL financial facts, offline evaluation, tracing, API, UI, Docker.

**Later:** earnings releases (8-K Ex-99.1), investor presentations (PDF), Pinecone/pgvector.

## Pipeline

```
                       ┌──────────────────────── Query Analyzer (LLM, structured output) ─────────────┐
User query + history → │ condense follow-up → extract {companies, fiscal_years, sections, metric}    │
                       │ classify intent: lookup | compare | trend | numeric | out_of_scope           │
                       │ decompose: "Compare MSFT vs AMZN cloud" → one sub-query per company × year   │
                       └──────────────────────────────────────────────────────────────────────────────┘
                                                    │
                     ┌──────────────────────────────┼──────────────────────────────┐
                     ▼                              ▼                              ▼
          Metadata filter                 Hybrid retrieval per sub-query    XBRL facts tool (numeric)
          (ticker, FY, section)           dense (FAISS) + BM25 → RRF        exact reported figures
                                                    │
                                          Cross-encoder reranker
                                                    │
                                Context selection (per-sub-query quotas, dedupe,
                                token budget, keep table chunks intact)
                                                    │
                                Generator (structured output: answer, claims, citations)
                                                    │
                                Grounding check: every claim cites a chunk and its figures
                                appear in a cited chunk; mis-cited claims re-attributed only
                                when the figure sits next to the claim's words; nothing
                                verified → abstain
                                                    │
                                Answer + [TICKER FY p.N] citations + confidence
```

## Key design decisions

| Decision | Why |
|---|---|
| SEC EDGAR HTML instead of IR-site PDFs | Canonical, permanent URLs; tables stay structured; page breaks are explicit CSS markers, so page numbers are exact. A generic PDF parser is added later for presentations. |
| Fiscal year = year of period end | Matches each company's own labeling (NVIDIA FY2025 ended Jan 2025, MSFT FY2025 ended Jun 2025). The analyzer maps "2025" to fiscal years and states the mismatch with calendar years. |
| Section-aware chunking (Item 1, 1A, 7, 8…) | Enables `section` filters ("risk factors" → Item 1A) and better chunk coherence. Tables are kept as whole Markdown chunks with a generated caption. |
| Hybrid dense + BM25 with RRF | Financial text is full of exact terms (segment names, "Intelligent Cloud", "cross-border volume") that dense retrieval misses; RRF needs no score calibration. |
| Cross-encoder reranker | Large precision gain at small k; cheap at this corpus size. |
| Decomposition for comparisons | One query for "MSFT vs AMZN" lets the bigger company crowd out the other. Per-entity sub-queries with quotas guarantee coverage. |
| XBRL company facts as a structured tool | Numbers like revenue growth should come from reported figures, not from an LLM reading a table. Text retrieval explains *why*; facts answer *how much*. |
| Abstention as a first-class output | The generator must cite chunks for every claim; uncited claims are dropped, and with no support it returns "insufficient evidence". Evaluated with unanswerable questions. |
| Verify figures in code, repair citations, judge prose later | Small local models often answer correctly but cite nothing or the wrong source. A deterministic checker (figures matched by value across units) accepts a claim when its figures appear in the cited chunk, or re-attributes it when they appear in the same sentence/row as the claim's words in another provided chunk; invented figures are never rescued. It cannot tell *whose* figure it is (a segment's net income vs the firm's) or check figure-free claims: that needs an LLM faithfulness judge (Phase 7). |
| Zero-cost, provider-agnostic models | Local bge embeddings and cross-encoder on CPU; Gemini free tier for generation with Groq and local Ollama as fallbacks, behind one LLM interface with caching and rate-limit backoff. No vendor lock-in, no spend. |
| Storage behind interfaces | FAISS + local files first, Postgres (metadata/chunks) + pgvector or Pinecone later, with no changes to retrieval logic. |

## Chunk metadata

`chunk_id, ticker, company, fiscal_year, form, filing_date, section (e.g. "Item 7"),
section_title, page_start, page_end, chunk_type (text|table), source_url, text`

## Evaluation

- Golden set (~80 questions) across categories: single lookup, multi-year trend,
  cross-company comparison, numeric, conversational follow-up, unanswerable.
  Each item: question, reference answer, gold (ticker, FY, page) evidence.
- Retrieval: Recall@K, MRR, nDCG against the gold pages.
- Generation: RAGAS faithfulness, answer relevancy, context precision/recall;
  citation accuracy; abstention precision/recall on unanswerable items.
- Ops: p50/p95 latency per stage, tokens/cost per query (Langfuse traces).
- Ablation table: BM25 / dense / hybrid / +rerank / +query analysis / +decomposition.
