# Retrieval evaluation: retrieval_earnings_v0

Golden set: 35 questions (27 answerable, 8 unanswerable, skipped here), 42 gold evidence items. Relevance is page-level: a chunk counts if it is from the gold filing and its pages overlap a gold page. Recall@k is the fraction of a question's evidence items (e.g. one per year in a trend) found in the top k.

## Modes

`+ decomposition` runs one sub-search per (company, fiscal year) in the gold filters and merges them round-robin (a preview of the Phase 6 query decomposition).

| Mode | Filters | recall@1 | recall@5 | recall@10 | hit@5 | mrr | ndcg@10 | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25 | gold | 0.306 | 0.657 | 0.843 | 0.741 | 0.508 | 0.565 | 0 | 0 |
| dense | gold | 0.500 | 0.787 | 0.889 | 0.852 | 0.697 | 0.724 | 7 | 10 |
| hybrid | gold | 0.454 | 0.870 | 0.935 | 0.926 | 0.661 | 0.725 | 7 | 8 |
| hybrid_rerank | gold | 0.546 | 0.861 | 0.954 | 0.926 | 0.765 | 0.804 | 1230 | 1450 |
| hybrid + decomposition | gold | 0.463 | 0.907 | 0.935 | 0.963 | 0.692 | 0.734 | 8 | 30 |
| hybrid_rerank + decomposition | gold | 0.546 | 0.870 | 0.963 | 0.926 | 0.768 | 0.810 | 1347 | 5090 |
| bm25 | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0 | 0 |
| dense | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 8 | 9 |
| hybrid | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 9 | 10 |
| hybrid_rerank | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1367 | 1609 |

## recall@5 by category

| Mode | Filters | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|---|
| bm25 | gold | 0.333 | 0.500 | 1.000 | 0.769 | 0.188 |
| dense | gold | 0.500 | 1.000 | 1.000 | 0.846 | 0.438 |
| hybrid | gold | 0.667 | 1.000 | 1.000 | 1.000 | 0.375 |
| hybrid_rerank | gold | 0.333 | 1.000 | 1.000 | 0.923 | 0.812 |
| hybrid + decomposition | gold | 0.833 | 1.000 | 1.000 | 1.000 | 0.500 |
| hybrid_rerank + decomposition | gold | 0.333 | 1.000 | 1.000 | 0.923 | 0.875 |
| bm25 | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dense | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid_rerank | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## mrr by category

| Mode | Filters | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|---|
| bm25 | gold | 0.722 | 0.571 | 0.750 | 0.421 | 0.300 |
| dense | gold | 0.389 | 0.750 | 1.000 | 0.678 | 0.583 |
| hybrid | gold | 0.722 | 0.750 | 1.000 | 0.586 | 0.394 |
| hybrid_rerank | gold | 0.333 | 0.750 | 1.000 | 0.742 | 0.875 |
| hybrid + decomposition | gold | 0.733 | 0.750 | 1.000 | 0.586 | 0.592 |
| hybrid_rerank + decomposition | gold | 0.367 | 0.750 | 1.000 | 0.742 | 0.875 |
| bm25 | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dense | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid_rerank | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
