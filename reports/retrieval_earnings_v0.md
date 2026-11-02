# Retrieval evaluation: retrieval_earnings_v0

Golden set: 60 questions (46 answerable, 14 unanswerable, skipped here), 61 gold evidence items. Relevance is page-level: a chunk counts if it is from the gold filing and its pages overlap a gold page. Recall@k is the fraction of a question's evidence items (e.g. one per year in a trend) found in the top k.

## Modes

`+ decomposition` runs one sub-search per (company, fiscal year) in the gold filters and merges them round-robin (a preview of the Phase 6 query decomposition).

| Mode | Filters | recall@1 | recall@5 | recall@10 | hit@5 | mrr | ndcg@10 | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25 | gold | 0.245 | 0.734 | 0.864 | 0.783 | 0.466 | 0.549 | 0 | 0 |
| dense | gold | 0.489 | 0.842 | 0.891 | 0.891 | 0.672 | 0.714 | 8 | 8 |
| hybrid | gold | 0.484 | 0.902 | 0.962 | 0.935 | 0.673 | 0.742 | 7 | 8 |
| hybrid_rerank | gold | 0.462 | 0.886 | 0.995 | 0.913 | 0.699 | 0.768 | 1289 | 1523 |
| hybrid + decomposition | gold | 0.489 | 0.924 | 0.973 | 0.957 | 0.691 | 0.751 | 8 | 30 |
| hybrid_rerank + decomposition | gold | 0.462 | 0.880 | 1.000 | 0.913 | 0.699 | 0.771 | 2358 | 7477 |
| bm25 | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0 | 0 |
| dense | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 9 | 10 |
| hybrid | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 8 | 9 |
| hybrid_rerank | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 2216 | 3304 |

## recall@5 by category

| Mode | Filters | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|---|
| bm25 | gold | 0.333 | 0.500 | 1.000 | 0.800 | 0.188 |
| dense | gold | 0.667 | 1.000 | 1.000 | 0.867 | 0.438 |
| hybrid | gold | 0.667 | 1.000 | 1.000 | 0.967 | 0.375 |
| hybrid_rerank | gold | 0.833 | 1.000 | 1.000 | 0.867 | 0.812 |
| hybrid + decomposition | gold | 0.833 | 1.000 | 1.000 | 0.967 | 0.500 |
| hybrid_rerank + decomposition | gold | 0.667 | 1.000 | 1.000 | 0.867 | 0.875 |
| bm25 | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dense | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid_rerank | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## mrr by category

| Mode | Filters | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|---|
| bm25 | gold | 0.722 | 0.571 | 0.750 | 0.389 | 0.300 |
| dense | gold | 0.444 | 0.750 | 0.929 | 0.642 | 0.583 |
| hybrid | gold | 0.722 | 0.750 | 0.929 | 0.640 | 0.394 |
| hybrid_rerank | gold | 0.667 | 0.750 | 1.000 | 0.605 | 0.875 |
| hybrid + decomposition | gold | 0.733 | 0.750 | 0.929 | 0.640 | 0.592 |
| hybrid_rerank + decomposition | gold | 0.667 | 0.750 | 1.000 | 0.605 | 0.875 |
| bm25 | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dense | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid_rerank | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
