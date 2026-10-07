# Generation evaluation v0

Models: `granite4.1:3b` (84) (providers: {'ollama': 84}). Retrieval: hybrid_rerank, k=10, gold filters, automatic per-entity decomposition; source budget 3500 tokens. 84 questions, 0 errors.

| Metric | Value | Meaning |
|---|---|---|
| Abstention recall | 1.000 | unanswerable questions correctly refused |
| Abstention precision | 0.294 | refusals that were on unanswerable questions |
| False abstention rate | 0.324 | answerable questions refused |
| Citation hit | 0.527 | a verified citation lands on a gold page |
| Evidence recall | 0.464 | gold evidence items covered by verified citations |
| Claim support | 0.911 | claims passing the citation/number verifier |
| Figure recall | 0.467 | reference-answer figures present in the answer |
| LLM latency | p50 17523 ms, p95 24632 ms | provider call only (excludes free-tier rate-limit waits) |
| Retrieval latency | p50 2463 ms | hybrid + rerank (+ decomposition) |
| Tokens | 274,887 | prompt + completion, whole run |

Confidence distribution: {'high': 41, 'medium': 7, 'none': 34, 'low': 2}

## By category

| Category | n | Abstained | Citation hit | Evidence recall | Claim support | Figure recall |
|---|---|---|---|---|---|---|
| comparison | 12 | 4 | 0.583 | 0.417 | 0.812 | 0.561 |
| follow_up | 6 | 2 | 0.333 | 0.333 | 1.000 | 0.417 |
| lookup | 27 | 8 | 0.481 | 0.481 | 0.928 | 0.451 |
| numeric | 17 | 5 | 0.588 | 0.588 | 1.000 | 0.451 |
| trend | 12 | 5 | 0.583 | 0.361 | 0.776 | 0.451 |
| unanswerable | 10 | 10 | n/a | n/a | n/a | n/a |

## Questions to review

| Id | Issue | Answer / reason |
|---|---|---|
| L01 | citation miss | Apple's Services net sales increased in fiscal 2025 primarily due to higher net sales from advertising, the App Store and cloud services [AAPL FY2025 p.24]. |
| L03 | figures 0.50 | Apple had approximately 166,000 full-time equivalent employees at the end of fiscal 2025. [AAPL FY2025 p.4] |
| L04 | citation miss | Azure and other cloud services revenue grew 34% in fiscal 2025 [MSFT FY2025 p.35]. |
| L05 | false abstention | None of the answer's claims could be verified against the cited sources. |
| L06 | figures 0.33 | 125,000 [MSFT FY2025 p.9] |
| L08 | false abstention | None of the answer's claims could be verified against the cited sources. |
| L09 | false abstention | None of the answer's claims could be verified against the cited sources. |
| L10 | figures 0.50 | Amazon employed approximately 1,576,000 full-time and part-time employees at the end of 2025 [AMZN FY2025 p.4]. |
| L11 | citation miss | AWS sales increased 19% in 2024, primarily driven by increased customer usage, partially offset by pricing changes tied to long-term contracts. Changes in foreign exchange rates positively impacted operating income by $2 |
| L13 | citation miss | Google Cloud revenue growth in 2025 was primarily driven by an increase in revenues, partially offset by increases in usage costs for technical infrastructure and employee compensation expenses [GOOGL FY2025 p.36]. |
| L14 | figures 0.50 | 3.58 billion daily active people (DAP) in December 2025 [META FY2025 p.61] |
| L16 | false abstention | None of the answer's claims could be verified against the cited sources. |
| L17 | false abstention | None of the answer's claims could be verified against the cited sources. |
| L20 | citation miss | The Standardized CET1 capital ratio requirement at the end of 2025 was 14.6% [JPM FY2025 p.47]. |
| L21 | false abstention | None of the answer's claims could be verified against the cited sources. |
| L22 | citation miss | Visa accrued $906 million for the interchange multidistrict litigation in fiscal 2023. [V FY2023 p.95] |
| L23 | false abstention | None of the answer's claims could be verified against the cited sources. |
| L24 | figures 0.33 | Mastercard's net revenue growth in 2025 was driven primarily by organic growth in its payment network (12% increase) and value-added services and solutions (23% increase), with additional contributions from acquisitions  |
| L25 | false abstention | None of the answer's claims could be verified against the cited sources. |
| N01 | citation miss | Apple's total net sales in fiscal 2023 were $383.3 billion [AAPL FY2023 p.20]. |
| N02 | figures 0.33 | Apple spent $34,550 million on research and development in fiscal 2025. [AAPL FY2025 p.24] |
| N03 | figures 0.50 | Microsoft Cloud revenue in fiscal 2025 was $168.9 billion [MSFT FY2025 p.35]. |
| N04 | figures 0.50 | Revenue for fiscal year 2025 was $130.5 billion [NVDA FY2025 p.38]. |
| N05 | false abstention | None of the answer's claims could be verified against the cited sources. |
| N07 | figures 0.50 | Google Search & other generated $224,532 million in revenue in 2025 [GOOGL FY2025 p.33]. |
| N08 | citation miss | Total revenue in 2025 was $200.97 billion [META FY2025 p.60]. |
| N11 | false abstention | None of the answer's claims could be verified against the cited sources. |
| N12 | figures 0.33 | Net income for 2025 was $57.0 billion [JPM FY2025 p.47]. |
| N13 | false abstention | None of the answer's claims could be verified against the cited sources. |
| N14 | figures 0.50 | Visa's net revenue in fiscal 2024 was $35,926 million. [V FY2024 p.44] |
| N15 | false abstention | None of the answer's claims could be verified against the cited sources. |
| N16 | false abstention | None of the answer's claims could be verified against the cited sources. |
| T01 | false abstention | None of the answer's claims could be verified against the cited sources. |
| T04 | false abstention | None of the answer's claims could be verified against the cited sources. |
| T05 | false abstention | None of the answer's claims could be verified against the cited sources. |
| T06 | figures 0.33 | Revenue grew from $26.91 billion in fiscal 2022 to $130.5 billion in fiscal 2025. This represents an increase of approximately 342% over the three-year period. [NVDA FY2022 p.31] [NVDA FY2025 p.38] |
| T08 | figures 0.50 | Net revenue growth increased from 18% in 2022 [MA FY2022 p.53] to 16% in 2025 [MA FY2025 p.56]. |
| T09 | figures 0.83 | Microsoft Cloud revenue grew from $111.6 billion in fiscal 2023 to $137.7 billion in fiscal 2024, and then to $168.9 billion in fiscal 2025. [MSFT FY2025 p.85] Revenue, classified by significant product and service offer |
| T10 | false abstention | None of the answer's claims could be verified against the cited sources. |
| T11 | figures 0.75 | Apple repurchased 90.2 billion shares in 2022 [AAPL FY2022 p.46], 95.0 billion shares in 2024 [AAPL FY2024 p.44], and 89.3 billion shares in 2025 [AAPL FY2025 p.44-45]. |
| T12 | false abstention | None of the answer's claims could be verified against the cited sources. |
| C01 | false abstention | None of the answer's claims could be verified against the cited sources. |
| C02 | false abstention | None of the answer's claims could be verified against the cited sources. |
| C03 | figures 0.67 | Visa grew net revenue faster in fiscal 2025 (23% increase on a currency-neutral basis) compared to Mastercard, which increased by 16% (or 15% on a currency-neutral basis). [MA FY2025 p.50] [MA FY2025 p.56] |
| C04 | citation miss | Visa's net revenue grew 10% in 2024, while Mastercard's net revenue increased 12% (currency-neutral basis 13%). [V FY2024 p.44] [MA FY2024 p.47] |
| C07 | false abstention | None of the answer's claims could be verified against the cited sources. |
| C10 | false abstention | None of the answer's claims could be verified against the cited sources. |
| C12 | figures 0.50 | JPMorgan Chase & Co. reported net revenue of $70.1 billion, up 9% in fiscal year 2024 [JPM FY2024 p.79]. NVIDIA Corporation reported revenue of $60.9 billion, up 126% in fiscal year 2024 [NVDA FY2024 p.36]. |
| F01 | citation miss | Azure and other cloud services revenue grew 30% in fiscal 2024 [MSFT FY2024 p.39]. |
| F02 | false abstention | None of the answer's claims could be verified against the cited sources. |
| F04 | citation miss | Mastercard's net revenue increased 16% in 2025 versus the prior year [MA FY2025 p.6]. |
| F05 | false abstention | None of the answer's claims could be verified against the cited sources. |
