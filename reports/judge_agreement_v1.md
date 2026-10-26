# Judge agreement: judge_v1 vs judge_v1_qwen

Same answers judged by both: 70. Exact agreement **0.91**, correct vs not-correct **0.93**.

| judge_v1 \ judge_v1_qwen | correct | partially_correct | incorrect |
|---|---|---|---|
| correct | 50 | 4 | 0 |
| partially_correct | 1 | 6 | 0 |
| incorrect | 0 | 1 | 8 |

| Category | n | judge_v1 | judge_v1_qwen |
|---|---|---|---|
| comparison | 12 | 0.667 | 0.625 |
| follow_up | 6 | 0.833 | 0.833 |
| lookup | 27 | 0.815 | 0.796 |
| numeric | 17 | 0.941 | 0.941 |
| trend | 12 | 0.542 | 0.542 |

Disagreements:

- L20: correct vs partially_correct: The candidate provides the correct percentage (11.5%) which matches the reference answer's main figure. However, the candidate fails to mention that this figure includes regulatory buffers (specifically the 2.5% stress c
- L22: correct vs partially_correct: The candidate correctly identifies the $906 million accrual amount but omits the additional $1.0 billion deposit into the escrow account, which is part of the reference answer's description of the accrual activity.
- L26: incorrect vs partially_correct: The candidate correctly identifies the timing of the announcement and the specific severance charges ($2.1 billion). However, the reference answer highlights the total cost of the reduction and related efforts (including
- T05: correct vs partially_correct: The candidate correctly identifies the starting and ending net income figures for 2022 and 2025 and the overall increase. However, the question asks how net income changed 'from 2022 to 2025', which implies a description
- T06: partially_correct vs correct: The candidate answer provides the exact revenue figures for all four fiscal years (FY2022-FY2025) and the year-over-year growth rates, which align perfectly with the reference answer. The additional calculation of the to
- C11: correct vs partially_correct: The candidate correctly identifies Alphabet's workforce reduction and the associated financial charges, which aligns with the reference. However, the candidate's description of Meta's actions is not supported by the prov
