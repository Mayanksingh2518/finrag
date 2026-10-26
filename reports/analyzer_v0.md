# Query analyzer evaluation v0

Rules for companies/years/sections; follow-up rewrite: gemini gemini-3.8-flash, groq openai/gpt-oss-120b, ollama granite4.1:3b. 74 answerable + 10 unanswerable questions.

## Filters vs gold (answerable questions)

| Field | Exact | Compatible (none or superset of gold) |
|---|---|---|
| Tickers | 1.000 | 1.000 |
| Fiscal years | 0.905 | 1.000 |
| Sections | 1.000 | 1.000 |
| All | 0.905 | 1.000 |

Scope: 4/10 unanswerable questions refused before retrieval (years outside the corpus); 0 answerable questions wrongly refused.

## Retrieval: gold vs analyzer filters and queries (hybrid_rerank, k=10)

| Category | n | Gold recall@5 | Analyzer recall@5 | Gold recall@10 | Analyzer recall@10 | Gold MRR | Analyzer MRR |
|---|---|---|---|---|---|---|---|
| **all** | 74 | 0.914 | 0.914 | 0.966 | 0.966 | 0.918 | 0.908 |
| comparison | 12 | 0.875 | 0.875 | 0.958 | 0.958 | 0.831 | 0.831 |
| follow_up | 6 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| lookup | 27 | 1.000 | 1.000 | 1.000 | 1.000 | 0.981 | 0.954 |
| numeric | 17 | 1.000 | 1.000 | 1.000 | 1.000 | 0.926 | 0.926 |
| trend | 12 | 0.597 | 0.597 | 0.833 | 0.833 | 0.811 | 0.811 |

## Differences from gold

| Id | Predicted | Gold | Question / rewrite |
|---|---|---|---|
| L05 | {"tickers": ["MSFT"], "fiscal_years": [], "sections": []} | {"tickers": ["MSFT"], "fiscal_years": [2024], "sections": []} | When did Activision Blizzard join Microsoft? |
| L07 | {"tickers": ["NVDA"], "fiscal_years": [], "sections": []} | {"tickers": ["NVDA"], "fiscal_years": [2023], "sections": []} | What did NVIDIA record when its acquisition of Arm was terminated? |
| L15 | {"tickers": ["META"], "fiscal_years": [], "sections": []} | {"tickers": ["META"], "fiscal_years": [2025], "sections": []} | What is Meta's approach to open-sourcing its AI models? |
| L16 | {"tickers": ["TSLA"], "fiscal_years": [], "sections": []} | {"tickers": ["TSLA"], "fiscal_years": [2025], "sections": []} | When did Tesla launch its Robotaxi service? |
| L17 | {"tickers": ["TSLA"], "fiscal_years": [], "sections": []} | {"tickers": ["TSLA"], "fiscal_years": [2024], "sections": []} | When did Tesla start delivering the Cybertruck? |
| L25 | {"tickers": ["MSFT"], "fiscal_years": [], "sections": ["Item 1C"]} | {"tickers": ["MSFT"], "fiscal_years": [2025], "sections": ["Item 1C"]} | Who presents cybersecurity topics to Microsoft's Board of Directors? |
| L27 | {"tickers": ["NVDA"], "fiscal_years": [], "sections": ["Item 1A"]} | {"tickers": ["NVDA"], "fiscal_years": [2025], "sections": ["Item 1A"]} | What are NVIDIA's risks related to Chinese government actions? |
| F01 | {"tickers": ["MSFT"], "fiscal_years": [2024], "sections": []} | {"tickers": ["MSFT"], "fiscal_years": [2024], "sections": []} | And what about the year before? → What was the revenue growth for Azure and other cloud services at Microsoft in the fiscal year prior to 2025? |
| F02 | {"tickers": ["TSLA"], "fiscal_years": [2025], "sections": []} | {"tickers": ["TSLA"], "fiscal_years": [2025], "sections": []} | How about in 2025? → How many vehicles did Tesla deliver in 2025? |
| F03 | {"tickers": ["JPM"], "fiscal_years": [2024], "sections": []} | {"tickers": ["JPM"], "fiscal_years": [2024], "sections": []} | What drove its net interest income that year? → What drove JPMorgan's net interest income in 2024? |
| F04 | {"tickers": ["MA"], "fiscal_years": [2025], "sections": []} | {"tickers": ["MA"], "fiscal_years": [2025], "sections": []} | And Mastercard's? → What was the change in net revenue for Mastercard in fiscal 2025? |
| F05 | {"tickers": ["NVDA"], "fiscal_years": [2024], "sections": []} | {"tickers": ["NVDA"], "fiscal_years": [2024], "sections": []} | What share of data center revenue came from China? → What share of data center revenue came from China in fiscal 2024? |
| F06 | {"tickers": ["META"], "fiscal_years": [2025], "sections": []} | {"tickers": ["META"], "fiscal_years": [2025], "sections": []} | And in 2025? → What were Meta's capital expenditures in 2025? |
| U02 | refused: The filings cover fiscal 2022-2025; the question asks about 2018. | {"tickers": [], "fiscal_years": [], "sections": []} | What were Apple's iPhone net sales in fiscal 2018? |
| U03 | refused: The filings cover fiscal 2022-2025; the question asks about 2027. | {"tickers": [], "fiscal_years": [], "sections": []} | How many vehicles will Tesla deliver in 2027? |
| U07 | refused: The filings cover fiscal 2022-2025; the question asks about 2030. | {"tickers": [], "fiscal_years": [], "sections": []} | What was JPMorgan Chase's net income in 2030? |
| U09 | refused: The filings cover fiscal 2022-2025; the question asks about 2027. | {"tickers": [], "fiscal_years": [], "sections": []} | What were Apple's total net sales in fiscal 2027? |
