# Earnings release evaluation (v0)

FinRAG answers quarterly questions from 160 earnings releases (8-K Exhibit 99.1) across 10 companies and fiscal 2022-2025. This is how it did on a
separate golden set of 60 questions: 46 answerable (single figures, table reading, quarterly trends, guidance, comparisons, follow-ups, questions phrased by
period-end date) and 14 it should refuse. Answers come from the shipped setup: the local 3B model, with trends and comparisons on Groq gpt-oss-120b.

## Results

| Metric | Result |
|---|---|
| **Judged correctness, answerable questions (gpt-oss judge)** | **0.870** (40 of 46 correct, 3 wrong, 3 refused) |
| Judged correctness, independent qwen judge (45 graded) | 0.867 |
| Correctness of the answers it gave | 0.930 |
| False abstention | 3 of 46 |
| Abstention recall | 14 of 14 |
| Filters read correctly (no gold filters given) | 46 of 46 |
| Citation hit (a cited chunk contains a gold quote) | 0.848 |
| Retrieval recall@5 / recall@10 / MRR (hybrid + rerank, gold filters) | 0.886 / 0.995 / 0.699 |
| Retrieval plan recall@10 / context recall | 1.000 / 1.000 |
| End-to-end latency, uncached, p50 / p95 (first 35 questions) | 20.9 s / 46.1 s |

The 10-K system is unaffected: 84 of 84 cached answers are identical with the current code, and retrieval was identical on all 740 question x mode results when
releases were merged. Annual questions still search only 10-Ks.

## The main finding: a small model misreads dense tables

13 table-reading questions were added late, and the score fell from 0.970 to 0.870. Releases show several periods side by side, and the 3B model often takes the wrong column.

| 14 table questions | Local 3B model | Groq gpt-oss-120b |
|---|---|---|
| Correct | 8 | **14** |
| Wrong answer shown | 3 | 0 |
| Refused after the verifier rejected a wrong answer | 3 | 0 |

The larger model's answers were each checked against the source tables by hand. This is 14 questions, not a full evaluation, and it isn't the shipped setup yet: `ANSWER_ROUTE_RELEASES` is off until
the full set has been run on it. It would use about 3.6k free-tier tokens per question, with the local model as the fallback when the daily quota runs out.

## Wrong answers the system still gives

Each has a valid citation and no warning to the reader. Both judges graded all three incorrect.

| Question | Answer | Actual | Why it gets through |
|---|---|---|---|
| Tesla energy storage deployed, Q3 2023 | 3.0 GWh | 3,980 MWh | "3.0" matches a stray "3" in legal boilerplate |
| JPMorgan *reported* net revenue, Q1 2022 | $31.6 billion | $30,717 million | that's the managed figure; the verifier can't tell |
| NVIDIA non-GAAP net income, Q2 FY2025 | $9,453 million | $16,952 million | the column headers are missing from this piece of a split table |

## What the verifier now catches (earnings releases only)

Figures alone can't catch a real number used wrongly, so three checks were added:
- **Wrong column.** A figure must sit in the column of the period the claim names. It reads 48% of release tables (1,365 of 2,849), across all 10 companies. The other tables get no verdict. On real data, every right-column
  claim was accepted (21,785 of 21,785) and 99.9% of wrong-column claims were rejected (64,493 of 64,528). Column reading agrees across separately read releases on 99.2% of 2,298 rows; the differences seen are restatements and stock splits.
  A year-to-date figure can still pass as its quarter's.
- **Count on dollars.** "69,138 million iPhone units" can't rest on a dollar figure.
- **Combined figures.** "Model Y" can't claim a "Model 3/Y" row.

These turn wrong answers into refusals. They can't produce the right answer: the three false abstentions above are all answers the verifier rejected.

## How far to trust these numbers

- **The score fell each time harder questions were added:** 1.000, then 0.970, then 0.870. A larger set would probably find more errors.
- **The set still has no "why" questions,** and most questions ask for a stated figure. It isn't comparable with the 10-K set's 0.865.
- **The judges do catch errors.** Both graded the real wrong answers incorrect. Answers made deliberately wrong with figures really in the source were judged incorrect: 6 of 6 by gpt-oss, 4 of 4 graded by qwen (2 errors).
- **The questions and labels have one author,** the same assistant that built the system. An independent review would be stronger.
- **Labels were changed after results were seen.** Citation hit first scored 0.741 because many facts appear in several places and only one was listed. Other locations were added, each checked by reading the text, and one reference answer (E15)
  was corrected. This raises those metrics, and the review wasn't blind. E15 and E27 still miss the citation metric; the cause wasn't diagnosed.
- **Gate floors were lowered when the harder questions came in,** to sit just below these numbers. The questions got harder; answers to the earlier questions didn't get worse.

## Limits of the corpus

- Tesla's FY2022 Q1-FY2023 Q1 financial tables exist only as images, so the releases can't answer those figures, though later releases show some as comparative columns that a quarter-filtered search doesn't reach.
- JPMorgan's releases here are the narrative only; its full statements are in Exhibit 99.2, which isn't downloaded.
- Comparing fiscal quarters across companies can compare different calendar quarters, and answers don't always say so.
- Investor presentations were left out by decision: most aren't on EDGAR.

## Reports

[agent](agent_earnings_v0.md), [judge](judge_earnings_v0.md), [second judge](judge_earnings_v0_qwen.md), [judge sensitivity](judge_sensitivity.md), [second judge sensitivity](judge_sensitivity_qwen.md),
[retrieval](retrieval_earnings_v0.md), [plan](plan_earnings_v0.md). Golden set: `data/eval/golden_earnings_v0.jsonl`. Ten gate checks in `gate.json` hold these results.
