# Retrieval evaluation v0

Golden set: 84 questions (74 answerable, 10 unanswerable, skipped here), 119 gold evidence items. Relevance is page-level: a chunk counts if it is from the gold filing and its pages overlap a gold page. Recall@k is the fraction of a question's evidence items (e.g. one per year in a trend) found in the top k.

## Modes

`+ decomposition` runs one sub-search per (company, fiscal year) in the gold filters and merges them round-robin (a preview of the Phase 6 query decomposition).

| Mode | Filters | recall@1 | recall@5 | recall@10 | hit@5 | mrr | ndcg@10 | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25 | gold | 0.373 | 0.697 | 0.819 | 0.797 | 0.579 | 0.620 | 0 | 1 |
| dense | gold | 0.538 | 0.828 | 0.902 | 0.919 | 0.764 | 0.777 | 8 | 12 |
| hybrid | gold | 0.579 | 0.860 | 0.926 | 0.959 | 0.794 | 0.805 | 7 | 8 |
| hybrid_rerank | gold | 0.707 | 0.884 | 0.922 | 0.986 | 0.920 | 0.877 | 2226 | 2631 |
| hybrid + decomposition | gold | 0.575 | 0.875 | 0.932 | 0.946 | 0.788 | 0.810 | 10 | 30 |
| hybrid_rerank + decomposition | gold | 0.704 | 0.901 | 0.966 | 0.959 | 0.905 | 0.902 | 1554 | 7060 |
| bm25 | none | 0.271 | 0.464 | 0.602 | 0.527 | 0.414 | 0.442 | 0 | 0 |
| dense | none | 0.410 | 0.726 | 0.841 | 0.797 | 0.641 | 0.671 | 8 | 13 |
| hybrid | none | 0.396 | 0.783 | 0.858 | 0.878 | 0.665 | 0.686 | 8 | 13 |
| hybrid_rerank | none | 0.694 | 0.884 | 0.905 | 0.986 | 0.909 | 0.866 | 2132 | 2664 |

## recall@5 by category

| Mode | Filters | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|---|
| bm25 | gold | 0.458 | 0.833 | 0.926 | 0.647 | 0.424 |
| dense | gold | 0.542 | 1.000 | 0.963 | 0.941 | 0.562 |
| hybrid | gold | 0.625 | 1.000 | 1.000 | 0.941 | 0.597 |
| hybrid_rerank | gold | 0.667 | 1.000 | 1.000 | 1.000 | 0.618 |
| hybrid + decomposition | gold | 0.667 | 1.000 | 1.000 | 0.941 | 0.646 |
| hybrid_rerank + decomposition | gold | 0.792 | 1.000 | 1.000 | 1.000 | 0.597 |
| bm25 | none | 0.292 | 0.667 | 0.741 | 0.235 | 0.236 |
| dense | none | 0.333 | 0.833 | 0.815 | 0.941 | 0.562 |
| hybrid | none | 0.375 | 1.000 | 0.926 | 0.882 | 0.618 |
| hybrid_rerank | none | 0.750 | 1.000 | 1.000 | 0.941 | 0.618 |

## mrr by category

| Mode | Filters | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|---|
| bm25 | gold | 0.472 | 0.771 | 0.787 | 0.342 | 0.459 |
| dense | gold | 0.737 | 0.792 | 0.818 | 0.803 | 0.601 |
| hybrid | gold | 0.711 | 1.000 | 0.872 | 0.767 | 0.635 |
| hybrid_rerank | gold | 0.845 | 1.000 | 0.963 | 0.897 | 0.889 |
| hybrid + decomposition | gold | 0.626 | 1.000 | 0.872 | 0.767 | 0.683 |
| hybrid_rerank + decomposition | gold | 0.831 | 1.000 | 0.963 | 0.897 | 0.811 |
| bm25 | none | 0.289 | 0.556 | 0.590 | 0.184 | 0.401 |
| dense | none | 0.521 | 0.688 | 0.617 | 0.775 | 0.601 |
| hybrid | none | 0.522 | 0.917 | 0.631 | 0.676 | 0.741 |
| hybrid_rerank | none | 0.854 | 1.000 | 0.938 | 0.882 | 0.889 |

## Reranker ablations (hybrid candidates, gold filters)

| Config | recall@1 | recall@5 | recall@10 | hit@5 | mrr | ndcg@10 | rerank p50 ms | rerank p95 ms |
|---|---|---|---|---|---|---|---|---|
| bge-reranker-base, 30 cand, len 512 (default) | 0.707 | 0.884 | 0.922 | 0.986 | 0.920 | 0.877 | 2220 | 2579 |
| bge-reranker-base, 30 cand, len 384 | 0.694 | 0.877 | 0.916 | 0.986 | 0.909 | 0.865 | 1900 | 2224 |
| bge-reranker-base, 50 cand, len 512 | 0.707 | 0.874 | 0.926 | 0.973 | 0.917 | 0.876 | 3620 | 4209 |
| ms-marco-MiniLM-L-6-v2, 30 cand, len 512 | 0.615 | 0.865 | 0.917 | 0.946 | 0.818 | 0.818 | 287 | 539 |
| ms-marco-MiniLM-L-6-v2, 50 cand, len 512 | 0.611 | 0.861 | 0.917 | 0.946 | 0.809 | 0.815 | 629 | 809 |
