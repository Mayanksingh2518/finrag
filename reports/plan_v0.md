# Retrieval plan evaluation v0

74 answerable questions, gold filters and gold standalone queries, hybrid_rerank (bge-reranker-base, 30 candidates per sub-query). ctx = chunks that fit the 3,500-token generation budget.

## Configurations

| Config | recall@5 | recall@10 | MRR | ctx recall | ctx coverage | ctx chunks | p50 ms | p95 ms | multi-entity p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.914 | 0.966 | 0.918 | 0.966 | 1.000 | 9.7 | 1666 | 8959 | 6119 / 9120 |
| v0 decomposition, k=10, batched rerank | 0.914 | 0.966 | 0.918 | 0.966 | 1.000 | 9.7 | 2355 | 7705 | 6271 / 7994 |
| plan quotas, k=10, no prior | 0.914 | 0.966 | 0.918 | 0.966 | 1.000 | 9.9 | 2414 | 9517 | 5330 / 10043 |
| plan quotas, k=10, MD&A prior 0.02 | 0.911 | 0.966 | 0.926 | 0.966 | 1.000 | 9.9 | 2826 | 9780 | 7173 / 10666 |
| plan quotas, k=10, MD&A prior 0.05 | 0.921 | 0.966 | 0.927 | 0.966 | 1.000 | 9.9 | 2699 | 8722 | 4514 / 8948 |
| plan quotas, k=10, MD&A prior 0.10 | 0.921 | 0.966 | 0.927 | 0.966 | 1.000 | 9.9 | 2469 | 8425 | 4931 / 8808 |
| v0 decomposition, k=5, batched rerank | 0.914 | 0.914 | 0.913 | 0.914 | 1.000 | 5.0 | 2459 | 7462 | 4799 / 7690 |
| plan quotas, k=5, MD&A prior 0.05 | 0.921 | 0.949 | 0.927 | 0.949 | 1.000 | 5.6 | 2457 | 8859 | 4862 / 8908 |

Latency columns above drift upward run by run (same device, one long process: p50 of the
single-entity questions, which no config changes, rose from 1.7 s to 2.8 s), so they don't compare
configs. Clean measurements below alternate the configs per question in a fresh process.

## Latency, clean (24 multi-entity questions, configs alternated per question)

| Reranking of the sub-queries (pool 30 each) | p50 ms | p95 ms | mean ms |
|---|---|---|---|
| sequential, one call per sub-query (v0) | 5393 | 11253 | 6799 |
| **batched, one call, batch size 16** | **4983** | **10426** | **6324** (-7%) |
| batched, batch size 32 | 5596 | 11425 | 6803 |
| batched, batch size 64 | 5885 | 11688 | 7318 |

| Rerank pool per sub-query (plan, prior 0.05) | recall@5 | ctx recall | MRR | p50 ms | p95 ms | mean ms |
|---|---|---|---|---|---|---|
| **30 (default)** | 0.757 | 0.896 | 0.848 | 6523 | 10905 | 7060 |
| 20 | 0.736 | 0.875 | 0.848 | 4288 | 7516 | 4814 |
| 15 | 0.726 | 0.865 | 0.848 | 3252 | 5434 | 3599 |

Labeling gap found in the review: T03's "loss" under the prior is partly unlabeled gold. META
FY2023 p.77 (MD&A segment table) states Reality Labs (16,120) / (13,717), the reference figures,
but T03's gold only covers the Item 1A sentence. Gold was not changed (adding labels only where the
new method retrieves would favour it).

## recall@5 by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.875 | 1.000 | 1.000 | 1.000 | 0.597 |
| v0 decomposition, k=10, batched rerank | 0.875 | 1.000 | 1.000 | 1.000 | 0.597 |
| plan quotas, k=10, no prior | 0.875 | 1.000 | 1.000 | 1.000 | 0.597 |
| plan quotas, k=10, MD&A prior 0.02 | 0.833 | 1.000 | 1.000 | 1.000 | 0.618 |
| plan quotas, k=10, MD&A prior 0.05 | 0.875 | 1.000 | 1.000 | 1.000 | 0.639 |
| plan quotas, k=10, MD&A prior 0.10 | 0.875 | 1.000 | 1.000 | 1.000 | 0.639 |
| v0 decomposition, k=5, batched rerank | 0.875 | 1.000 | 1.000 | 1.000 | 0.597 |
| plan quotas, k=5, MD&A prior 0.05 | 0.875 | 1.000 | 1.000 | 1.000 | 0.639 |

## ctx_recall by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.958 | 1.000 | 1.000 | 1.000 | 0.833 |
| v0 decomposition, k=10, batched rerank | 0.958 | 1.000 | 1.000 | 1.000 | 0.833 |
| plan quotas, k=10, no prior | 0.958 | 1.000 | 1.000 | 1.000 | 0.833 |
| plan quotas, k=10, MD&A prior 0.02 | 0.958 | 1.000 | 1.000 | 1.000 | 0.833 |
| plan quotas, k=10, MD&A prior 0.05 | 0.958 | 1.000 | 1.000 | 1.000 | 0.833 |
| plan quotas, k=10, MD&A prior 0.10 | 0.958 | 1.000 | 1.000 | 1.000 | 0.833 |
| v0 decomposition, k=5, batched rerank | 0.875 | 1.000 | 1.000 | 1.000 | 0.597 |
| plan quotas, k=5, MD&A prior 0.05 | 0.917 | 1.000 | 1.000 | 1.000 | 0.771 |

## mrr by category

| Config | comparison | follow_up | lookup | numeric | trend |
|---|---|---|---|---|---|
| v0 decomposition, k=10, sequential rerank | 0.831 | 1.000 | 0.981 | 0.926 | 0.811 |
| v0 decomposition, k=10, batched rerank | 0.831 | 1.000 | 0.981 | 0.926 | 0.811 |
| plan quotas, k=10, no prior | 0.831 | 1.000 | 0.981 | 0.926 | 0.811 |
| plan quotas, k=10, MD&A prior 0.02 | 0.887 | 1.000 | 0.981 | 0.926 | 0.802 |
| plan quotas, k=10, MD&A prior 0.05 | 0.892 | 1.000 | 0.981 | 0.926 | 0.805 |
| plan quotas, k=10, MD&A prior 0.10 | 0.892 | 1.000 | 0.981 | 0.926 | 0.805 |
| v0 decomposition, k=5, batched rerank | 0.819 | 1.000 | 0.981 | 0.926 | 0.792 |
| plan quotas, k=5, MD&A prior 0.05 | 0.892 | 1.000 | 0.981 | 0.926 | 0.805 |

## Questions that change: `v0 decomposition, k=10, sequential rerank` → `plan quotas, k=10, MD&A prior 0.05`

| Id | recall@5 | ctx recall | MRR | top 5 after |
|---|---|---|---|---|
| N03 | 1.00 → 1.00 | 1.00 → 1.00 | 1.00 → 0.50 | MSFT FY2025 p.38 Item 7 text; MSFT FY2025 p.35 Item 7 text; MSFT FY2025 p.85 Item 8 text; MSFT FY2025 p.39 Item 7 text; MSFT FY2025 p.39 Item 7 text |
| N14 | 1.00 → 1.00 | 1.00 → 1.00 | 0.50 → 1.00 | V FY2024 p.44 Item 7 text; V FY2024 p.44 Item 7 table; V FY2024 p.38 Item 7 table; V FY2024 p.44 Item 7 table; V FY2024 p.44 Item 7 text |
| T03 | 1.00 → 0.50 | 1.00 → 1.00 | 1.00 → 0.33 | META FY2022 p.70 Item 7 text; META FY2023 p.77 Item 7 text; META FY2025 p.26 Item 1A text; META FY2024 p.28 Item 1A text; META FY2023 p.75 Item 7 text |
| T04 | 0.00 → 0.25 | 0.25 → 0.25 | 0.11 → 0.20 | TSLA FY2022 p.37 Item 7 text; TSLA FY2023 p.39 Item 7 text; TSLA FY2025 p.5 Item 1 text; TSLA FY2024 p.5 Item 1 text; TSLA FY2022 p.32 Item 7 text |
| T05 | 0.25 → 0.50 | 0.50 → 0.50 | 0.50 → 1.00 | JPM FY2022 p.49 Item 7 text; JPM FY2025 p.49 Item 7 text; JPM FY2023 p.80 Item 8 text; JPM FY2024 p.297 Item 8 text; JPM FY2022 p.70 Item 7 text |
| T08 | 0.50 → 0.75 | 1.00 → 1.00 | 1.00 → 1.00 | MA FY2022 p.53 Item 7 text; MA FY2023 p.55 Item 7 text; MA FY2025 p.56 Item 7 text; MA FY2024 p.107 Item 8 text; MA FY2022 p.54 Item 7 text |
| T11 | 0.75 → 1.00 | 1.00 → 1.00 | 1.00 → 1.00 | AAPL FY2022 p.22 Item 7 text; AAPL FY2025 p.28 Item 7 text; AAPL FY2023 p.46 Item 8 text; AAPL FY2024 p.46 Item 8 text; AAPL FY2022 p.48 Item 8 text |
| C03 | 0.00 → 0.50 | 0.50 → 0.50 | 0.14 → 0.20 | V FY2025 p.46 Item 7 text; MA FY2025 p.6 Item 1 table; V FY2025 p.6 Item 1 table; MA FY2025 p.50 Item 7 table; MA FY2025 p.56 Item 7 text |
| C07 | 1.00 → 0.50 | 1.00 → 1.00 | 1.00 → 1.00 | JPM FY2025 p.49 Item 7 text; META FY2025 p.76 Item 7 table; JPM FY2025 p.82 Item 8 table; META FY2025 p.76 Item 7 text; JPM FY2025 p.68 Item 8 text |
| C10 | 0.50 → 0.50 | 1.00 → 1.00 | 0.33 → 1.00 | MA FY2025 p.56 Item 7 text; V FY2025 p.69 Item 8 text; MA FY2025 p.37 Item 1A text; V FY2025 p.25 Item 1A text; MA FY2025 p.20 Item 1 text |
