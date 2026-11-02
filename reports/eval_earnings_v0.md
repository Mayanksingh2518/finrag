# Earnings release evaluation (v0)

FinRAG answers quarterly questions from 160 earnings releases (8-K Exhibit 99.1) across 10 companies and fiscal 2022-2025.
This is how it did on a separate golden set of 47 questions: 33 answerable (single figures, quarterly trends, guidance,
comparisons, follow-ups, questions phrased by period-end date) and 14 it should refuse.

## Results

| Metric | Result |
|---|---|
| Judged correctness, answerable questions (gpt-oss judge, 33 answers) | 0.970 (32 correct) |
| Judged correctness, independent qwen judge (32 answers, 1 judge error) | 0.969 (31 correct) |
| False abstention | 0 of 33 |
| Abstention recall | 14 of 14 |
| Filters read correctly (no gold filters given) | 33 of 33 |
| Citation hit (a cited chunk contains a gold quote) | 0.939 |
| Retrieval recall@5 / MRR (hybrid + rerank, gold filters) | 0.932 / 0.823 |
| Retrieval plan recall@10 / context recall | 1.000 / 1.000 |
| End-to-end latency, uncached, p50 / p95 (first 35 questions) | 20.9 s / 46.1 s |

The 10-K system is unaffected: 84 of 84 cached answers are identical with the current code, and retrieval was identical on all 740 question x
mode results when releases were merged. Annual questions still search only 10-Ks.

## Known failure: the wrong column

"How many vehicles did Tesla produce in Q1 2024?" gets a high-confidence wrong answer: **440,808**, where the right figure is 433,371. The row lists five
quarters and the answer took the year-ago column. The figure is in the source, so the citation verifier passes it. Both judges graded it incorrect.
Releases show several periods side by side, so expect this class of error in production until the verifier can read columns. A reader sees
no warning: the answer shows high confidence and a valid citation.

## Fixed: a figure relabelled as another metric

Two questions first got wrong answers: "Apple sold 69,138 million iPhone units" (really dollars of sales) and "422,405 Model Y vehicles" (really Model 3 and Y
combined). A prompt rule didn't help. Two checks in the verifier, for release sources only, now reject them: a count can't rest on a dollar figure, and one
product can't claim a combined row.

This protection is partial. Tables often show the dollar sign only on their first row, so "7,949 million Mac units" on the row `| Mac | 7,949 |` passes these
checks, and a product name not on the list of counted nouns isn't covered. In the fresh test, those two questions were refused for other reasons (a wrong source, no
citation), so the 14 of 14 refusals overstate how robust this is.

## How far to trust the correctness score

- **The questions are easier than the 10-K set.** Nearly all ask for a stated figure; none asks "why". The 10-K set scores 0.865 with such
  questions. Do not read 0.970 as better than 0.865.
- **The first version of this set was too easy.** It scored 1.000. Twelve new questions, written to test the fix above, immediately found the wrong-column answer.
  A larger set would probably find more.
- **The judges do catch errors.** Both caught the real error above. Answers made deliberately wrong with figures really in the source (another period's column, an
  annual total, an adjusted figure, the next quarter's outlook) were judged incorrect: 6 of 6 by gpt-oss, 4 of 4 graded by qwen (2 errors).
- **The questions and labels have one author,** the same assistant that built the system. An independent review would be stronger.
- **Labels were changed after results were seen.** The first run scored citation hit 0.741 because many facts appear in several places in a release and only one was
  listed. Other locations were added, each checked by reading the text, and one reference answer (E15) was corrected. This raises those metrics, and the review wasn't
  blind. E15 and E27 still miss the citation metric; the cause wasn't diagnosed.

## Limits of the corpus

- Tesla's FY2022 Q1-FY2023 Q1 financial tables exist only as images, so the releases can't answer those figures, though later releases
  show some as comparative columns that a quarter-filtered search doesn't reach.
- JPMorgan's releases here are the narrative only; its full statements are in Exhibit 99.2, which isn't downloaded.
- Comparing fiscal quarters across companies can compare different calendar quarters, and answers don't always say so.

## Reports

[agent](agent_earnings_v0.md), [judge](judge_earnings_v0.md), [second judge](judge_earnings_v0_qwen.md), [judge sensitivity](judge_sensitivity.md),
[second judge sensitivity](judge_sensitivity_qwen.md), [retrieval](retrieval_earnings_v0.md), [plan](plan_earnings_v0.md). Golden set:
`data/eval/golden_earnings_v0.jsonl`. Ten gate checks in `gate.json` hold these results.
