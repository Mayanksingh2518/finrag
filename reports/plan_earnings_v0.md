# Retrieval plan evaluation v0

33 answerable questions, gold filters and gold standalone queries, hybrid_rerank (bge-reranker-base, 30 candidates per sub-query). ctx = chunks that fit the 3,500-token generation budget.

## Configurations

| Config | recall@5 | recall@10 | MRR | ctx recall | ctx coverage | ctx chunks | p50 ms | p95 ms | multi-entity p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.924 | 1.000 | 0.823 | 1.000 | 1.000 | 9.5 | 2337 | 11177 | 8178 / 11810 |
| v0 decomposition, k=10, batched rerank | 0.924 | 1.000 | 0.823 | 1.000 | 1.000 | 9.5 | 2617 | 10194 | 5713 / 10680 |
| plan quotas, k=10, no prior | 0.924 | 1.000 | 0.823 | 1.000 | 1.000 | 9.5 | 2264 | 8407 | 5619 / 9105 |
| plan quotas, k=10, MD&A prior 0.02 | 0.924 | 1.000 | 0.823 | 1.000 | 1.000 | 9.5 | 2205 | 7987 | 5179 / 8537 |
| plan quotas, k=10, MD&A prior 0.05 | 0.924 | 1.000 | 0.823 | 1.000 | 1.000 | 9.5 | 2018 | 8022 | 4820 / 8389 |
| plan quotas, k=10, MD&A prior 0.10 | 0.924 | 1.000 | 0.823 | 1.000 | 1.000 | 9.5 | 1932 | 7204 | 4719 / 7634 |
| v0 decomposition, k=5, batched rerank | 0.924 | 0.924 | 0.818 | 0.924 | 1.000 | 5.0 | 1940 | 7204 | 4811 / 7724 |
| plan quotas, k=5, MD&A prior 0.05 | 0.924 | 0.947 | 0.818 | 0.947 | 1.000 | 5.5 | 2011 | 7477 | 5058 / 7941 |

## recall@5 by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.667 | 1.000 | 1.000 | 0.941 | 0.875 |
| v0 decomposition, k=10, batched rerank | 0.667 | 1.000 | 1.000 | 0.941 | 0.875 |
| plan quotas, k=10, no prior | 0.667 | 1.000 | 1.000 | 0.941 | 0.875 |
| plan quotas, k=10, MD&A prior 0.02 | 0.667 | 1.000 | 1.000 | 0.941 | 0.875 |
| plan quotas, k=10, MD&A prior 0.05 | 0.667 | 1.000 | 1.000 | 0.941 | 0.875 |
| plan quotas, k=10, MD&A prior 0.10 | 0.667 | 1.000 | 1.000 | 0.941 | 0.875 |
| v0 decomposition, k=5, batched rerank | 0.667 | 1.000 | 1.000 | 0.941 | 0.875 |
| plan quotas, k=5, MD&A prior 0.05 | 0.667 | 1.000 | 1.000 | 0.941 | 0.875 |

## ctx_recall by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| v0 decomposition, k=10, batched rerank | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, no prior | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, MD&A prior 0.02 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, MD&A prior 0.05 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| plan quotas, k=10, MD&A prior 0.10 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| v0 decomposition, k=5, batched rerank | 0.667 | 1.000 | 1.000 | 0.941 | 0.875 |
| plan quotas, k=5, MD&A prior 0.05 | 0.833 | 1.000 | 1.000 | 0.941 | 0.938 |

## mrr by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.667 | 0.750 | 1.000 | 0.773 | 0.875 |
| v0 decomposition, k=10, batched rerank | 0.667 | 0.750 | 1.000 | 0.773 | 0.875 |
| plan quotas, k=10, no prior | 0.667 | 0.750 | 1.000 | 0.773 | 0.875 |
| plan quotas, k=10, MD&A prior 0.02 | 0.667 | 0.750 | 1.000 | 0.773 | 0.875 |
| plan quotas, k=10, MD&A prior 0.05 | 0.667 | 0.750 | 1.000 | 0.773 | 0.875 |
| plan quotas, k=10, MD&A prior 0.10 | 0.667 | 0.750 | 1.000 | 0.773 | 0.875 |
| v0 decomposition, k=5, batched rerank | 0.667 | 0.750 | 1.000 | 0.765 | 0.875 |
| plan quotas, k=5, MD&A prior 0.05 | 0.667 | 0.750 | 1.000 | 0.765 | 0.875 |

## Questions that change: `v0 decomposition, k=10, sequential rerank` → `plan quotas, k=10, MD&A prior 0.05`

| Id | recall@5 | ctx recall | MRR | top 5 after |
|---|---|---|---|---|
