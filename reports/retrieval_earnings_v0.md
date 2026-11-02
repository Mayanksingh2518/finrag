# Retrieval evaluation: retrieval_earnings_v0

Golden set: 47 questions (33 answerable, 14 unanswerable, skipped here), 48 gold evidence items. Relevance is page-level: a chunk counts if it is from the gold filing and its pages overlap a gold page. Recall@k is the fraction of a question's evidence items (e.g. one per year in a trend) found in the top k.

## Modes

`+ decomposition` runs one sub-search per (company, fiscal year) in the gold filters and merges them round-robin (a preview of the Phase 6 query decomposition).

| Mode | Filters | recall@1 | recall@5 | recall@10 | hit@5 | mrr | ndcg@10 | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25 | gold | 0.311 | 0.720 | 0.841 | 0.788 | 0.523 | 0.582 | 0 | 0 |
| dense | gold | 0.561 | 0.871 | 0.909 | 0.939 | 0.748 | 0.772 | 7 | 11 |
| hybrid | gold | 0.553 | 0.894 | 0.947 | 0.939 | 0.731 | 0.781 | 7 | 8 |
| hybrid_rerank | gold | 0.614 | 0.932 | 0.992 | 0.970 | 0.823 | 0.861 | 1313 | 1582 |
| hybrid + decomposition | gold | 0.561 | 0.924 | 0.962 | 0.970 | 0.756 | 0.794 | 8 | 29 |
| hybrid_rerank + decomposition | gold | 0.614 | 0.924 | 1.000 | 0.970 | 0.823 | 0.865 | 1568 | 6142 |
| bm25 | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0 | 0 |
| dense | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 9 | 9 |
| hybrid | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 8 | 9 |
| hybrid_rerank | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1752 | 2889 |

## recall@5 by category

| Mode | Filters | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|---|
| bm25 | gold | 0.333 | 0.500 | 1.000 | 0.824 | 0.188 |
| dense | gold | 0.667 | 1.000 | 1.000 | 0.941 | 0.438 |
| hybrid | gold | 0.667 | 1.000 | 1.000 | 1.000 | 0.375 |
| hybrid_rerank | gold | 0.833 | 1.000 | 1.000 | 0.941 | 0.812 |
| hybrid + decomposition | gold | 0.833 | 1.000 | 1.000 | 1.000 | 0.500 |
| hybrid_rerank + decomposition | gold | 0.667 | 1.000 | 1.000 | 0.941 | 0.875 |
| bm25 | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dense | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid_rerank | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## mrr by category

| Mode | Filters | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|---|
| bm25 | gold | 0.722 | 0.571 | 0.750 | 0.442 | 0.300 |
| dense | gold | 0.444 | 0.750 | 0.929 | 0.766 | 0.583 |
| hybrid | gold | 0.722 | 0.750 | 0.929 | 0.727 | 0.394 |
| hybrid_rerank | gold | 0.667 | 0.750 | 1.000 | 0.773 | 0.875 |
| hybrid + decomposition | gold | 0.733 | 0.750 | 0.929 | 0.727 | 0.592 |
| hybrid_rerank + decomposition | gold | 0.667 | 0.750 | 1.000 | 0.773 | 0.875 |
| bm25 | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| dense | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid_rerank | none | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
