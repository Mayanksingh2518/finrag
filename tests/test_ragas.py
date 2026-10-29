"""RAGAS second opinion: the adapter over FinRAG's LLM layer, score splitting, and the runner's summary."""

import json

from app.evaluation.ragas_metrics import RagasScorer
from app.evaluation.run_ragas_eval import RagasRecord, render_report, spearman, summarize
from app.generation.context import build_sources
from app.generation.llm import LLM, LLMResponse, ResponseCache, Usage
from app.retrieval.types import ScoredChunk
from tests.test_retrieval import make_chunk

ANSWER = "Revenue was $130,497 million in fiscal 2025, up 114.2% [NVDA FY2025 p.1]."
REFERENCE = "$130.5B in FY2025 (+114%)."


class ScriptedProvider:
    """Answers each RAGAS step by its output schema; the NLI verdicts depend on which text is the context."""

    name, model = "groq", "qwen/qwen3.8-27b"

    def __init__(self):
        self.prompts: list[tuple[str, str]] = []

    def complete(self, messages, schema, schema_name):
        prompt = messages[0]["content"]
        self.prompts.append((schema_name, prompt))
        if schema_name == "StatementGeneratorOutput":
            out = {"statements": ["Revenue was $130,497 million in fiscal 2025.", "Revenue rose 114.2%."]}
        elif schema_name == "ClaimDecompositionOutput":
            is_reference = f'"response": "{REFERENCE}"' in prompt
            out = {"claims": ["FY2025 revenue was $130.5B.", "Revenue grew 114%."] if is_reference
                   else ["Revenue was $130,497 million.", "Revenue was up 114.2%.", "It was fiscal 2025."]}
        else:  # NLIStatementOutput: all true vs the sources; answer vs reference, only growth claims pass
            payload = json.loads(prompt[prompt.rindex("input: ") + 7: prompt.rindex("Output:")])
            factual = payload["context"] in (REFERENCE, ANSWER)
            out = {"statements": [{"statement": st, "reason": "r", "verdict": int(not factual or "114" in st)}
                                  for st in payload["statements"]]}
        return LLMResponse(json.dumps(out), self.name, self.model, Usage(1000, 100))


def _sources():
    return build_sources([ScoredChunk(make_chunk(0, "NVDA", 2025, "Item 7", "Revenue was $130,497 million, up 114%."),
                                      0.9)], token_budget=1000)


def test_scorer_runs_ragas_through_finrag_llm_and_splits_factual_correctness(tmp_path):
    provider = ScriptedProvider()
    scorer = RagasScorer(LLM([provider], ResponseCache(tmp_path)))
    s = scorer.score("How did NVIDIA's revenue grow?", ANSWER, REFERENCE, _sources())

    assert [name for name, _ in provider.prompts] == ["StatementGeneratorOutput", "NLIStatementOutput",
                                                      "ClaimDecompositionOutput", "NLIStatementOutput",
                                                      "ClaimDecompositionOutput", "NLIStatementOutput"]
    assert "[NVDA FY2025 p.1]\\nRevenue was $130,497 million, up 114%." in provider.prompts[1][1]  # cited sources
    assert s.faithfulness == 1.0
    assert s.fc_precision == 1 / 3  # tp 1, fp 2: exact figure and extra detail fail NLI vs the rounded reference
    assert s.fc_coverage == 0.5  # reference claims entailed by the answer: only the growth claim (scripted)
    assert s.factual_correctness == 0.4  # RAGAS f1 from tp 1, fp 2, fn 1
    assert scorer.llm.stats.calls == 6 and scorer.llm.stats.tokens == 6600 and scorer.llm.stats.cached == 0

    again = RagasScorer(LLM([provider], ResponseCache(tmp_path)))
    assert again.score("How did NVIDIA's revenue grow?", ANSWER, REFERENCE, _sources()) == s
    assert len(provider.prompts) == 6 and again.llm.stats.cached == 6 and again.llm.stats.tokens == 0


def test_scorer_skips_faithfulness_without_cited_sources(tmp_path):
    s = RagasScorer(LLM([ScriptedProvider()], ResponseCache(tmp_path))).score("q", ANSWER, REFERENCE, [])
    assert s.faithfulness is None and s.fc_coverage == 0.5


def test_spearman_handles_ties_and_constant_series():
    assert spearman([0.1, 0.5, 0.9, 0.9], [0.0, 0.5, 1.0, 1.0]) == 1.0
    assert spearman([0.9, 0.5, 0.1], [0.0, 0.5, 1.0]) == -1.0
    assert spearman([1.0, 1.0, 1.0], [0.0, 0.5, 1.0]) != spearman([1.0, 1.0, 1.0], [0.0, 0.5, 1.0])  # nan
    assert spearman([1.0], [1.0]) != spearman([1.0], [1.0])


def test_summary_groups_ragas_scores_by_judge_grade_and_lists_disagreements():
    records = [
        RagasRecord("T06", "trend", "a", 1.0, 0.18, 0.1, 1.0, "correct", 1.0, 1.0, True, "gpt-oss", 6, 7000),
        RagasRecord("C05", "comparison", "b", 1.0, 0.75, 0.6, 1.0, "correct", 1.0, 1.0, True, "gpt-oss", 6, 5000),
        RagasRecord("L09", "lookup", "c", 0.5, 0.2, 0.5, 0.0, "incorrect", 0.0, 0.5, False, "granite", 6, 4000),
        RagasRecord("L10", "lookup", "d", error="groq daily limit reached"),
    ]
    s = summarize(records)
    assert s["scored"] == 3 and s["errors"] == 1 and s["tokens"] == 16000
    assert s["by_judge_grade"]["correct"][:2] == (2, 1.0)  # n, mean coverage
    assert s["spearman_coverage"] == 1.0
    assert s["answer_mismatches"] == ["L09"]
    report = render_report(records, s, "ragas_v0", "judge_v2_qwen.json", ["qwen/qwen3.8-27b"])
    assert "| L09 | incorrect | 0.00 |" not in report  # coverage 0 vs judge 0 is agreement
    assert "Correctness disagreements (|RAGAS coverage - judge| >= 0.5): 0" in report
