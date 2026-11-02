# Retrieval plan evaluation v0

46 answerable questions, gold filters and gold standalone queries, hybrid_rerank (bge-reranker-base, 30 candidates per sub-query). ctx = chunks that fit the 3,500-token generation budget.

## Configurations

| Config | recall@5 | recall@10 | MRR | ctx recall | ctx coverage | ctx chunks | p50 ms | p95 ms | multi-entity p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.880 | 1.000 | 0.699 | 1.000 | 1.000 | 9.5 | 2122 | 7941 | 5472 / 8872 |
| v0 decomposition, k=10, batched rerank | 0.880 | 1.000 | 0.699 | 1.000 | 1.000 | 9.5 | 2172 | 6649 | 5341 / 8597 |
| plan quotas, k=10, no prior | 0.880 | 1.000 | 0.699 | 1.000 | 1.000 | 9.5 | 2234 | 7511 | 5988 / 9504 |
| plan quotas, k=10, MD&A prior 0.02 | 0.880 | 1.000 | 0.699 | 1.000 | 1.000 | 9.5 | 2273 | 6917 | 5493 / 8758 |
| plan quotas, k=10, MD&A prior 0.05 | 0.880 | 1.000 | 0.699 | 1.000 | 1.000 | 9.5 | 2260 | 7074 | 5620 / 9150 |
| plan quotas, k=10, MD&A prior 0.10 | 0.880 | 1.000 | 0.699 | 1.000 | 1.000 | 9.5 | 2240 | 6862 | 5500 / 8833 |
| v0 decomposition, k=5, batched rerank | 0.880 | 0.880 | 0.687 | 0.880 | 1.000 | 5.0 | 2149 | 6737 | 5453 / 8603 |
| plan quotas, k=5, MD&A prior 0.05 | 0.880 | 0.897 | 0.687 | 0.897 | 1.000 | 5.4 | 1440 | 4177 | 3852 / 8090 |

## recall@5 by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.667 | 1.000 | 1.000 | 0.867 | 0.875 |
| v0 decomposition, k=10, batched rerank | 0.667 | 1.000 | 1.000 | 0.867 | 0.875 |
| plan quotas, k=10, no prior | 0.667 | 1.000 | 1.000 | 0.867 | 0.875 |
| plan quotas, k=10, MD&A prior 0.02 | 0.667 | 1.000 | 1.000 | 0.867 | 0.875 |
| plan quotas, k=10, MD&A prior 0.05 | 0.667 | 1.000 | 1.000 | 0.867 | 0.875 |
| plan quotas, k=10, MD&A prior 0.10 | 0.667 | 1.000 | 1.000 | 0.867 | 0.875 |
| v0 decomposition, k=5, batched rerank | 0.667 | 1.000 | 1.000 | 0.867 | 0.875 |
| plan quotas, k=5, MD&A prior 0.05 | 0.667 | 1.000 | 1.000 | 0.867 | 0.875 |

## ctx_recall by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| v0 decomposition, k=10, batched rerank | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, no prior | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, MD&A prior 0.02 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, MD&A prior 0.05 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, MD&A prior 0.10 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| v0 decomposition, k=5, batched rerank | 0.667 | 1.000 | 1.000 | 0.867 | 0.875 |
| plan quotas, k=5, MD&A prior 0.05 | 0.833 | 1.000 | 1.000 | 0.867 | 0.938 |

## mrr by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.667 | 0.750 | 1.000 | 0.605 | 0.875 |
| v0 decomposition, k=10, batched rerank | 0.667 | 0.750 | 1.000 | 0.605 | 0.875 |
| plan quotas, k=10, no prior | 0.667 | 0.750 | 1.000 | 0.605 | 0.875 |
| plan quotas, k=10, MD&A prior 0.02 | 0.667 | 0.750 | 1.000 | 0.605 | 0.875 |
| plan quotas, k=10, MD&A prior 0.05 | 0.667 | 0.750 | 1.000 | 0.605 | 0.875 |
| plan quotas, k=10, MD&A prior 0.10 | 0.667 | 0.750 | 1.000 | 0.605 | 0.875 |
| v0 decomposition, k=5, batched rerank | 0.667 | 0.750 | 1.000 | 0.586 | 0.875 |
| plan quotas, k=5, MD&A prior 0.05 | 0.667 | 0.750 | 1.000 | 0.586 | 0.875 |

## Questions that change: `v0 decomposition, k=10, sequential rerank` → `plan quotas, k=10, MD&A prior 0.05`

| Id | recall@5 | ctx recall | MRR | top 5 after |
|---|---|---|---|---|
