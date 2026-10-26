# Generation evaluation v0

Models: `openai/gpt-oss-120b` (84) (providers: {'groq': 84}). Retrieval: hybrid_rerank, k=10, gold filters, automatic per-entity decomposition; source budget 3500 tokens. 84 questions, 0 errors.

| Metric | Value | Meaning |
|---|---|---|
| Abstention recall | 1.000 | unanswerable questions correctly refused |
| Abstention precision | 0.909 | refusals that were on unanswerable questions |
| False abstention rate | 0.014 | answerable questions refused |
| Citation hit | 0.959 | a verified citation lands on a gold page |
| Evidence recall | 0.884 | gold evidence items covered by verified citations |
| Claim support | 0.966 | claims passing the citation/number verifier |
| Figure recall | 0.653 | reference-answer figures present in the answer |
| LLM latency | p50 1091 ms, p95 1728 ms | provider call only (excludes free-tier rate-limit waits) |
| Retrieval latency | p50 1669 ms | hybrid + rerank (+ decomposition) |
| Tokens | 307,188 | prompt + completion, whole run |

Confidence distribution: {'high': 65, 'medium': 8, 'none': 11}

## By category

| Category | n | Abstained | Citation hit | Evidence recall | Claim support | Figure recall |
|---|---|---|---|---|---|---|
| comparison | 12 | 0 | 0.917 | 0.750 | 0.944 | 0.818 |
| follow_up | 6 | 1 | 0.833 | 0.833 | 1.000 | 0.667 |
| lookup | 27 | 0 | 0.963 | 0.963 | 1.000 | 0.588 |
| numeric | 17 | 0 | 1.000 | 1.000 | 1.000 | 0.588 |
| trend | 12 | 0 | 1.000 | 0.701 | 0.847 | 0.681 |
| unanswerable | 10 | 10 | n/a | n/a | n/a | n/a |

## Questions to review

| Id | Issue | Answer / reason |
|---|---|---|
| L06 | figures 0.33 | Microsoft employed approximately 228,000 full-time employees as of June 30, 2025. [MSFT FY2025 p.9] |
| L14 | figures 0.50 | Meta's Family of Apps had an average of 3.58 billion daily active people in December 2025. [META FY2025 p.61][META FY2025 p.65-66] |
| L20 | citation miss | JPMorgan's Standardized CET1 capital ratio requirement at the end of 2025 was 11.5% [JPM FY2025 p.293]. |
| L22 | figures 0.50 | Visa accrued $906 million for the interchange multidistrict litigation in fiscal 2023 [V FY2023 p.35-36][V FY2023 p.95]. |
| L24 | figures 0.33 | Mastercard’s 2025 net‑revenue increase was driven primarily by organic growth in its payment network (≈12% growth) and its value‑added services and solutions (≈23% growth), with additional contributions from acquisitions |
| N01 | figures 0.50 | Apple's total net sales in fiscal 2023 were $383.3 billion [AAPL FY2023 p.20][AAPL FY2023 p.34-35]. |
| N02 | figures 0.33 | Apple spent $34,550 million on research and development in fiscal 2025 [AAPL FY2025 p.24][AAPL FY2025 p.29]. |
| N03 | figures 0.50 | Microsoft Cloud revenue was $168.9 billion in fiscal 2025 [MSFT FY2025 p.85]. |
| N04 | figures 0.50 | NVIDIA's total revenue for fiscal 2025 was $130.5 billion. [NVDA FY2025 p.38][NVDA FY2025 p.52] |
| N05 | figures 0.50 | NVIDIA's Data Center revenue in fiscal 2023 was $15.01 billion [NVDA FY2023 p.38][NVDA FY2023 p.86]. |
| N07 | figures 0.50 | Google Search & other generated $224,532 million in 2025, i.e., about $224.5 billion [GOOGL FY2025 p.60][GOOGL FY2025 p.33]. |
| N08 | figures 0.50 | Meta's total revenue in 2025 was $200.97 billion [META FY2025 p.102]. |
| N11 | figures 0.50 | Tesla delivered approximately 1.64 million consumer vehicles in 2025. [TSLA FY2025 p.31] |
| N12 | figures 0.33 | JPMorgan Chase reported net income of $57.0 billion for 2025 [JPM FY2025 p.47][JPM FY2025 p.165]. |
| N13 | figures 0.50 | JPMorgan's firmwide net interest income in 2024 was $92.6 billion [JPM FY2024 p.54][JPM FY2024 p.68]. |
| N14 | figures 0.50 | Visa's net revenue in fiscal 2024 was $35,926 million [V FY2024 p.71][V FY2024 p.44][V FY2024 p.38][V FY2024 p.44]. |
| N15 | figures 0.33 | Mastercard reported net revenue of $22,237 million for 2022 [MA FY2022 p.66][MA FY2022 p.53]. |
| N16 | figures 0.50 | Amazon's cash capital expenditures were $48.1 billion in 2023. [AMZN FY2023 p.22-23] |
| T01 | figures 0.50 | Microsoft's Azure growth rate fell from 45% in fiscal 2022 to 34% in fiscal 2025, a decline of 11 percentage points. [MSFT FY2022 p.45][MSFT FY2025 p.39-40] |
| T04 | figures 0.25 | In 2022 Tesla delivered 1,313,851 consumer vehicles [TSLA FY2022 p.32]. The 2025 vehicle delivery figure is not provided in the available sources. |
| T05 | figures 0.25 | JPMorgan Chase's net income increased from $37.7 billion in 2022 to $57.0 billion in 2025, a rise of $19.3 billion. [JPM FY2022 p.47][JPM FY2025 p.47] |
| T06 | figures 0.33 | NVIDIA's total revenue grew from $26.91 billion in fiscal 2022 to $130.5 billion in fiscal 2025, an increase of $103.59 billion (about 385%). [NVDA FY2022 p.31][NVDA FY2025 p.38] |
| T07 | figures 0.75 | Visa's net revenue grew 11% from fiscal 2022 ($29,310 million) to 2023 ($32,653 million) [V FY2023 p.40], 10% from 2023 to 2024 ($35,926 million) [V FY2024 p.44][V FY2024 p.38], and 11% from 2024 to 2025 ($40,000 million |
| T09 | figures 0.33 | Microsoft Cloud revenue grew from $111.6 billion in fiscal 2023 to $168.9 billion in fiscal 2025, an increase of $57.3 billion or about 51% [MSFT FY2023 p.40][MSFT FY2025 p.35]. |
| T10 | figures 0.75 | Google Cloud revenue increased by $6.8 billion from 2022 to 2023, by $10.1 billion from 2023 to 2024, and by $15.5 billion from 2024 to 2025. [GOOGL FY2023 p.36][GOOGL FY2024 p.37][GOOGL FY2025 p.34] |
| C03 | citation miss | Mastercard’s net revenue grew 16% in fiscal 2025, while Visa’s net revenue growth rate is not disclosed in the provided sources. [MA FY2025 p.50][V FY2025 p.45-46] |
| C04 | figures 0.67 | Mastercard’s net revenue grew 12% in fiscal 2024, while Visa’s net revenue grew 10% in fiscal 2024. [MA FY2024 p.47][V FY2024 p.38][V FY2024 p.44] |
| C07 | figures 0.50 | Meta earned more net income in 2025, reporting $60,458 million versus JPMorgan Chase’s $4,520 million. [META FY2025 p.92][JPM FY2025 p.80] |
| C12 | figures 0.50 | NVIDIA’s fiscal 2024 revenue grew 126% year‑over‑year to $60.9 billion, while JPMorgan Chase’s fiscal 2024 net revenue grew 9% year‑over‑year to $70.1 billion. [NVDA FY2024 p.36][JPM FY2024 p.79] |
| F05 | false abstention | The provided sources give only qualitative descriptions (mid‑single digit percentage) of China’s contribution to Data Center revenue and do not state a specific share percentage for fiscal year 2024. |
