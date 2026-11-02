# Retrieval plan evaluation v0

27 answerable questions, gold filters and gold standalone queries, hybrid_rerank (bge-reranker-base, 30 candidates per sub-query). ctx = chunks that fit the 3,500-token generation budget.

## Configurations

| Config | recall@5 | recall@10 | MRR | ctx recall | ctx coverage | ctx chunks | p50 ms | p95 ms | multi-entity p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.870 | 0.963 | 0.768 | 0.963 | 1.000 | 9.4 | 1615 | 6246 | 4153 / 6963 |
| v0 decomposition, k=10, batched rerank | 0.870 | 0.963 | 0.768 | 0.963 | 1.000 | 9.4 | 1841 | 6725 | 4715 / 7438 |
| plan quotas, k=10, no prior | 0.870 | 0.963 | 0.768 | 0.963 | 1.000 | 9.5 | 1967 | 7037 | 4619 / 7626 |
| plan quotas, k=10, MD&A prior 0.02 | 0.870 | 0.963 | 0.768 | 0.963 | 1.000 | 9.5 | 1967 | 7148 | 4840 / 7731 |
| plan quotas, k=10, MD&A prior 0.05 | 0.870 | 0.963 | 0.768 | 0.963 | 1.000 | 9.5 | 1963 | 7042 | 4895 / 7541 |
| plan quotas, k=10, MD&A prior 0.10 | 0.870 | 0.963 | 0.768 | 0.963 | 1.000 | 9.5 | 1918 | 7185 | 3990 / 8108 |
| v0 decomposition, k=5, batched rerank | 0.870 | 0.870 | 0.759 | 0.870 | 1.000 | 5.0 | 1420 | 5193 | 3438 / 5508 |
| plan quotas, k=5, MD&A prior 0.05 | 0.870 | 0.880 | 0.759 | 0.880 | 1.000 | 5.6 | 1800 | 7308 | 5905 / 8189 |

## recall@5 by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.333 | 1.000 | 1.000 | 0.923 | 0.875 |
| v0 decomposition, k=10, batched rerank | 0.333 | 1.000 | 1.000 | 0.923 | 0.875 |
| plan quotas, k=10, no prior | 0.333 | 1.000 | 1.000 | 0.923 | 0.875 |
| plan quotas, k=10, MD&A prior 0.02 | 0.333 | 1.000 | 1.000 | 0.923 | 0.875 |
| plan quotas, k=10, MD&A prior 0.05 | 0.333 | 1.000 | 1.000 | 0.923 | 0.875 |
| plan quotas, k=10, MD&A prior 0.10 | 0.333 | 1.000 | 1.000 | 0.923 | 0.875 |
| v0 decomposition, k=5, batched rerank | 0.333 | 1.000 | 1.000 | 0.923 | 0.875 |
| plan quotas, k=5, MD&A prior 0.05 | 0.333 | 1.000 | 1.000 | 0.923 | 0.875 |

## ctx_recall by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| v0 decomposition, k=10, batched rerank | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, no prior | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, MD&A prior 0.02 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, MD&A prior 0.05 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, MD&A prior 0.10 | 0.667 | 1.000 | 1.000 | 1.000 | 1.000 |
| v0 decomposition, k=5, batched rerank | 0.333 | 1.000 | 1.000 | 0.923 | 0.875 |
| plan quotas, k=5, MD&A prior 0.05 | 0.333 | 1.000 | 1.000 | 0.923 | 0.938 |

## mrr by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.367 | 0.750 | 1.000 | 0.742 | 0.875 |
| v0 decomposition, k=10, batched rerank | 0.367 | 0.750 | 1.000 | 0.742 | 0.875 |
| plan quotas, k=10, no prior | 0.367 | 0.750 | 1.000 | 0.742 | 0.875 |
| plan quotas, k=10, MD&A prior 0.02 | 0.367 | 0.750 | 1.000 | 0.742 | 0.875 |
| plan quotas, k=10, MD&A prior 0.05 | 0.367 | 0.750 | 1.000 | 0.742 | 0.875 |
| plan quotas, k=10, MD&A prior 0.10 | 0.367 | 0.750 | 1.000 | 0.742 | 0.875 |
| v0 decomposition, k=5, batched rerank | 0.333 | 0.750 | 1.000 | 0.731 | 0.875 |
| plan quotas, k=5, MD&A prior 0.05 | 0.333 | 0.750 | 1.000 | 0.731 | 0.875 |

## Questions that change: `v0 decomposition, k=10, sequential rerank` → `plan quotas, k=10, MD&A prior 0.05`

| Id | recall@5 | ctx recall | MRR | top 5 after |
|---|---|---|---|---|
