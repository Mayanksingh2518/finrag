# Retrieval evaluation: retrieval_v1

Golden set: 84 questions (74 answerable, 10 unanswerable, skipped here), 119 gold evidence items. Relevance is page-level: a chunk counts if it is from the gold filing and its pages overlap a gold page. Recall@k is the fraction of a question's evidence items (e.g. one per year in a trend) found in the top k.

## Modes

`+ decomposition` runs one sub-search per (company, fiscal year) in the gold filters and merges them round-robin (a preview of the Phase 6 query decomposition).

| Mode | Filters | recall@1 | recall@5 | recall@10 | hit@5 | mrr | ndcg@10 | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25 | gold | 0.393 | 0.711 | 0.832 | 0.811 | 0.599 | 0.637 | 0 | 0 |
| dense | gold | 0.619 | 0.828 | 0.909 | 0.919 | 0.810 | 0.814 | 7 | 8 |
| hybrid | gold | 0.626 | 0.867 | 0.939 | 0.959 | 0.825 | 0.832 | 7 | 8 |
| hybrid_rerank | gold | 0.734 | 0.891 | 0.929 | 0.986 | 0.933 | 0.890 | 1356 | 1761 |
| hybrid + decomposition | gold | 0.623 | 0.882 | 0.932 | 0.946 | 0.821 | 0.836 | 9 | 30 |
| hybrid_rerank + decomposition | gold | 0.731 | 0.914 | 0.966 | 0.959 | 0.918 | 0.915 | 2292 | 7991 |
| bm25 | none | 0.271 | 0.471 | 0.616 | 0.541 | 0.426 | 0.452 | 0 | 0 |
| dense | none | 0.477 | 0.753 | 0.855 | 0.824 | 0.691 | 0.712 | 8 | 10 |
| hybrid | none | 0.430 | 0.789 | 0.878 | 0.892 | 0.695 | 0.711 | 8 | 9 |
| hybrid_rerank | none | 0.721 | 0.884 | 0.919 | 0.986 | 0.925 | 0.883 | 1925 | 2316 |

## recall@5 by category

| Mode | Filters | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|---|
| bm25 | gold | 0.542 | 0.833 | 0.926 | 0.647 | 0.424 |
| dense | gold | 0.542 | 1.000 | 0.963 | 0.941 | 0.562 |
| hybrid | gold | 0.667 | 1.000 | 1.000 | 0.941 | 0.597 |
| hybrid_rerank | gold | 0.708 | 1.000 | 1.000 | 1.000 | 0.618 |
| hybrid + decomposition | gold | 0.708 | 1.000 | 1.000 | 0.941 | 0.646 |
| hybrid_rerank + decomposition | gold | 0.875 | 1.000 | 1.000 | 1.000 | 0.597 |
| bm25 | none | 0.333 | 0.667 | 0.741 | 0.235 | 0.236 |
| dense | none | 0.333 | 0.833 | 0.889 | 0.941 | 0.562 |
| hybrid | none | 0.417 | 1.000 | 0.926 | 0.882 | 0.618 |
| hybrid_rerank | none | 0.750 | 1.000 | 1.000 | 0.941 | 0.618 |

## mrr by category

| Mode | Filters | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|---|
| bm25 | gold | 0.556 | 0.771 | 0.805 | 0.342 | 0.459 |
| dense | gold | 0.737 | 0.875 | 0.889 | 0.861 | 0.601 |
| hybrid | gold | 0.753 | 1.000 | 0.901 | 0.826 | 0.635 |
| hybrid_rerank | gold | 0.845 | 1.000 | 0.981 | 0.926 | 0.889 |
| hybrid + decomposition | gold | 0.681 | 1.000 | 0.901 | 0.826 | 0.683 |
| hybrid_rerank + decomposition | gold | 0.831 | 1.000 | 0.981 | 0.926 | 0.811 |
| bm25 | none | 0.344 | 0.556 | 0.596 | 0.184 | 0.401 |
| dense | none | 0.521 | 0.771 | 0.693 | 0.843 | 0.601 |
| hybrid | none | 0.593 | 0.917 | 0.665 | 0.706 | 0.741 |
| hybrid_rerank | none | 0.854 | 1.000 | 0.963 | 0.912 | 0.889 |

## Reranker ablations (hybrid candidates, gold filters)

| Config | recall@1 | recall@5 | recall@10 | hit@5 | mrr | ndcg@10 | rerank p50 ms | rerank p95 ms |
|---|---|---|---|---|---|---|---|---|
| bge-reranker-base, 30 cand, len 512 (default) | 0.734 | 0.891 | 0.929 | 0.986 | 0.933 | 0.890 | 2231 | 2506 |
| bge-reranker-base, 30 cand, len 384 | 0.721 | 0.884 | 0.922 | 0.986 | 0.923 | 0.878 | 1776 | 1913 |
| bge-reranker-base, 50 cand, len 512 | 0.734 | 0.881 | 0.932 | 0.973 | 0.931 | 0.889 | 3514 | 4848 |
| ms-marco-MiniLM-L-6-v2, 30 cand, len 512 | 0.669 | 0.872 | 0.923 | 0.946 | 0.849 | 0.844 | 292 | 353 |
| ms-marco-MiniLM-L-6-v2, 50 cand, len 512 | 0.666 | 0.868 | 0.923 | 0.946 | 0.841 | 0.841 | 491 | 577 |
