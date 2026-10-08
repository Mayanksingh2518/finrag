# Generation evaluation v0

Models: `granite4.1:3b` (84) (providers: {'ollama': 84}). Retrieval: hybrid_rerank, k=10, gold filters, automatic per-entity decomposition; source budget 3500 tokens. 84 questions, 0 errors.

| Metric | Value | Meaning |
|---|---|---|
| Abstention recall | 1.000 | unanswerable questions correctly refused |
| Abstention precision | 0.667 | refusals that were on unanswerable questions |
| False abstention rate | 0.068 | answerable questions refused |
| Citation hit | 0.878 | a verified citation lands on a gold page |
| Evidence recall | 0.783 | gold evidence items covered by verified citations |
| Claim support | 0.978 | claims passing the citation/number verifier |
| Figure recall | 0.579 | reference-answer figures present in the answer |
| LLM latency | p50 nan ms, p95 nan ms | provider call only (excludes free-tier rate-limit waits) |
| Retrieval latency | p50 2015 ms | hybrid + rerank (+ decomposition) |
| Tokens | 274,887 | prompt + completion, whole run |

Confidence distribution: {'high': 49, 'medium': 19, 'none': 15, 'low': 1}

## By category

| Category | n | Abstained | Citation hit | Evidence recall | Claim support | Figure recall |
|---|---|---|---|---|---|---|
| comparison | 12 | 1 | 0.833 | 0.583 | 0.955 | 0.742 |
| follow_up | 6 | 0 | 1.000 | 1.000 | 1.000 | 0.583 |
| lookup | 27 | 1 | 0.852 | 0.852 | 1.000 | 0.510 |
| numeric | 17 | 1 | 0.941 | 0.941 | 1.000 | 0.559 |
| trend | 12 | 2 | 0.833 | 0.493 | 0.897 | 0.556 |
| unanswerable | 10 | 10 | n/a | n/a | n/a | n/a |

## Questions to review

| Id | Issue | Answer / reason |
|---|---|---|
| L01 | citation miss | Apple's Services net sales increased in fiscal 2025 primarily due to higher net sales from advertising, the App Store and cloud services [AAPL FY2025 p.24]. |
| L03 | figures 0.50 | Apple had approximately 166,000 full-time equivalent employees at the end of fiscal 2025. [AAPL FY2025 p.4] |
| L06 | figures 0.33 | 125,000 [MSFT FY2025 p.9] |
| L10 | figures 0.50 | Amazon employed approximately 1,576,000 full-time and part-time employees at the end of 2025 [AMZN FY2025 p.4]. |
| L13 | citation miss | Google Cloud revenue growth in 2025 was primarily driven by an increase in revenues, partially offset by increases in usage costs for technical infrastructure and employee compensation expenses [GOOGL FY2025 p.36]. |
| L14 | figures 0.50 | 3.58 billion daily active people (DAP) in December 2025 [META FY2025 p.61] |
| L17 | false abstention | None of the answer's claims could be verified against the cited sources. |
| L20 | citation miss | The Standardized CET1 capital ratio requirement at the end of 2025 was 14.6% [JPM FY2025 p.47]. |
| L22 | figures 0.50 | Visa accrued $906 million for the interchange multidistrict litigation in fiscal 2023. [V FY2023 p.95] |
| L24 | figures 0.33 | Mastercard's net revenue growth in 2025 was driven primarily by organic growth in its payment network (12% increase) and value-added services and solutions (23% increase), with additional contributions from acquisitions  |
| N01 | figures 0.50 | Apple's total net sales in fiscal 2023 were $383.3 billion [AAPL FY2023 p.20]. |
| N02 | figures 0.33 | Apple spent $34,550 million on research and development in fiscal 2025. [AAPL FY2025 p.24] |
| N03 | figures 0.50 | Microsoft Cloud revenue in fiscal 2025 was $168.9 billion [MSFT FY2025 p.35]. |
| N04 | figures 0.50 | Revenue for fiscal year 2025 was $130.5 billion [NVDA FY2025 p.38]. |
| N05 | false abstention | None of the answer's claims could be verified against the cited sources. |
| N07 | figures 0.50 | Google Search & other generated $224,532 million in revenue in 2025 [GOOGL FY2025 p.33]. |
| N08 | figures 0.50 | Total revenue in 2025 was $200.97 billion [META FY2025 p.60]. |
| N11 | figures 0.50 | Tesla delivered approximately 1.64 million consumer vehicles in 2025. [TSLA FY2025 p.31] |
| N12 | figures 0.33 | Net income for 2025 was $57.0 billion [JPM FY2025 p.47]. |
| N13 | figures 0.50 | JPMorgan's firmwide net interest income in 2024 was $92,583 million [JPM FY2024 p.77]. [JPM FY2024 p.68] |
| N14 | figures 0.50 | Visa's net revenue in fiscal 2024 was $35,926 million. [V FY2024 p.44] |
| N15 | figures 0.33 | Mastercard's net revenue in 2022 was $22,237 million. [MA FY2022 p.66] |
| N16 | figures 0.50 | Amazon's cash capital expenditures in 2023 were $48.1 billion. [AMZN FY2023 p.22-23] |
| T01 | false abstention | None of the answer's claims could be verified against the cited sources. |
| T04 | figures 0.25 | Vehicle deliveries increased from 2022 to 2025. In 2022, Tesla delivered 1,313,851 consumer vehicles. In 2023, deliveries rose to 1,540,000 consumer vehicles. In 2024, deliveries continued to grow to 1,600,000 consumer v |
| T05 | figures 0.25 | Net income increased from $15.0 billion in 2022 to $57.0 billion in 2025, a change of +2%. [JPM FY2025 p.47][JPM FY2022 p.68] |
| T06 | figures 0.33 | Revenue grew from $26.91 billion in fiscal 2022 to $130.5 billion in fiscal 2025. This represents an increase of approximately 342% over the three-year period. [NVDA FY2022 p.31] [NVDA FY2025 p.38] |
| T08 | figures 0.50 | Net revenue growth increased from 18% in 2022 [MA FY2022 p.53] to 16% in 2025 [MA FY2025 p.56]. |
| T09 | figures 0.83 | Microsoft Cloud revenue grew from $111.6 billion in fiscal 2023 to $137.7 billion in fiscal 2024, and then to $168.9 billion in fiscal 2025. [MSFT FY2025 p.85] Revenue, classified by significant product and service offer |
| T10 | figures 0.75 | Google Cloud revenue increased $6.8 billion from 2022 to 2023 [GOOGL FY2023 p.36], $10.1 billion from 2023 to 2024 [GOOGL FY2024 p.37], and $15.5 billion from 2024 to 2025 [GOOGL FY2024 p.37]. [GOOGL FY2025 p.34] |
| T11 | figures 0.75 | Apple repurchased 90.2 billion shares in 2022 [AAPL FY2022 p.46], 95.0 billion shares in 2024 [AAPL FY2024 p.44], and 89.3 billion shares in 2025 [AAPL FY2025 p.44-45]. |
| T12 | false abstention | None of the answer's claims could be verified against the cited sources. |
| C01 | false abstention | None of the answer's claims could be verified against the cited sources. |
| C03 | figures 0.67 | Visa grew net revenue faster in fiscal 2025 (23% increase on a currency-neutral basis) compared to Mastercard, which increased by 16% (or 15% on a currency-neutral basis). [MA FY2025 p.50] [MA FY2025 p.56] |
| C07 | figures 0.50 | Meta Platforms earned more net income in 2025. Meta reported a net income of $60.46 billion, while JPMorgan Chase reported a net income of $4.5 billion [META FY2025 p.92][JPM FY2025 p.81]. |
| C10 | citation miss | Cross-border activity drove Visa's revenue by increasing international transaction revenue by 13% in fiscal 2025, primarily due to a 15% growth in nominal cross-border volume (excluding Europe) and higher currency volati |
| C12 | figures 0.50 | JPMorgan Chase & Co. reported net revenue of $70.1 billion, up 9% in fiscal year 2024 [JPM FY2024 p.79]. NVIDIA Corporation reported revenue of $60.9 billion, up 126% in fiscal year 2024 [NVDA FY2024 p.36]. |
| F04 | figures 0.50 | Mastercard's net revenue increased 16% in 2025 versus the prior year [MA FY2025 p.6]. |
