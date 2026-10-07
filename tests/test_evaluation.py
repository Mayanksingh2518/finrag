import json
import math

import pytest

from app.evaluation.golden import GoldEvidence, PageText, load_golden, normalize, resolve_pages, validate
from app.evaluation.metrics import RetrievedPage, score_ranking

KS = (1, 3, 5, 10)
E2024 = GoldEvidence("AAPL", 2024, (20, 41), ("Services net sales increased",))
E2025 = GoldEvidence("AAPL", 2025, (21,), ("Services net sales increased",))


def hit(ticker="AAPL", year=2024, start=1, end=None) -> RetrievedPage:
    return RetrievedPage(ticker, year, start, end or start)


def test_first_rank_hit_scores_perfectly():
    m = score_ranking([hit(start=20), hit(start=3)], [E2024], KS)
    assert m["mrr"] == 1.0 and m["recall@1"] == 1.0 and m["ndcg@10"] == pytest.approx(1.0)


def test_any_listed_page_and_page_ranges_count():
    assert score_ranking([hit(start=41)], [E2024], KS)["hit@1"] == 1.0
    assert score_ranking([hit(start=19, end=21)], [E2024], KS)["hit@1"] == 1.0  # chunk spans the page


def test_wrong_filing_or_page_does_not_count():
    ranking = [hit(year=2025, start=20), hit(ticker="MSFT", start=20), hit(start=22)]
    m = score_ranking(ranking, [E2024], KS)
    assert m["mrr"] == 0.0 and m["recall@10"] == 0.0 and m["ndcg@10"] == 0.0


def test_mrr_uses_first_relevant_rank():
    assert score_ranking([hit(start=1), hit(start=2), hit(start=20)], [E2024], KS)["mrr"] == pytest.approx(1 / 3)


def test_multi_evidence_recall_is_partial():
    m = score_ranking([hit(year=2025, start=21), hit(start=5)], [E2024, E2025], KS)
    assert m["recall@1"] == 0.5 and m["recall@3"] == 0.5 and m["hit@1"] == 1.0


def test_ndcg_counts_each_gold_item_once():
    duplicate_page = score_ranking([hit(start=20), hit(start=20), hit(year=2025, start=21)], [E2024, E2025], KS)
    both_first = score_ranking([hit(start=20), hit(year=2025, start=21)], [E2024, E2025], KS)
    assert both_first["ndcg@10"] == pytest.approx(1.0)
    expected = (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert duplicate_page["ndcg@10"] == pytest.approx(expected)


def test_metrics_reject_unanswerable():
    with pytest.raises(ValueError):
        score_ranking([hit()], [], KS)


def _row(**overrides) -> dict:
    row = {
        "id": "q1",
        "category": "lookup",
        "question": "How did Apple's services revenue change in FY2024?",
        "reference_answer": "It increased.",
        "filters": {"tickers": ["AAPL"], "fiscal_years": [2024]},
        "evidence": [{"ticker": "AAPL", "fiscal_year": 2024, "pages": [20], "quotes": ["Services  net sales\nincreased"]}],
    }
    return row | overrides


def _load(tmp_path, rows):
    path = tmp_path / "golden.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return load_golden(path)


PAGES = {("AAPL", 2024, 20): PageText("19", "Services net sales increased 13% — driven by advertising.")}


def test_valid_golden_set_passes_with_whitespace_insensitive_quotes(tmp_path):
    questions = _load(tmp_path, [_row()])
    assert validate(questions, PAGES) == []
    assert questions[0].filters.tickers == ("AAPL",)


def test_validation_catches_bad_labels(tmp_path):
    rows = [
        _row(evidence=[{"ticker": "AAPL", "fiscal_year": 2024, "pages": [20], "quotes": ["not on the page"]}]),
        _row(id="q2", evidence=[{"ticker": "AAPL", "fiscal_year": 2024, "pages": [99], "quotes": ["x"]}]),
        _row(id="q3", evidence=[{"ticker": "MSFT", "fiscal_year": 2024, "pages": [20], "quotes": ["Services"]}]),
        _row(id="q4", category="unanswerable"),
        _row(id="q5", category="follow_up"),
        _row(id="q5"),
    ]
    problems = "\n".join(validate(_load(tmp_path, rows), PAGES))
    for expected in ("q1: none of", "q2: no such page", "q3: evidence ticker MSFT", "q4: unanswerable",
                     "q5: follow_up needs", "q5: duplicate id"):
        assert expected in problems


def test_normalize_unifies_dashes_quotes_and_spaces():
    assert normalize("Apple’s  —\n net\xa0sales") == "Apple's - net sales"


def test_resolve_pages_finds_every_page_with_any_quote():
    pages = PAGES | {
        ("AAPL", 2024, 41): PageText("40", "Total Services net sales increased"),
        ("AAPL", 2024, 42): PageText("41", "unrelated"),
        ("AAPL", 2025, 20): PageText("19", "Services net sales increased"),
    }
    assert resolve_pages("AAPL", 2024, ["services net  sales increased", "nope"], pages) == (20, 41)


class _StubSearcher:
    """Returns fixed pages per query and records the filters it was given."""

    def __init__(self, pages_by_query):
        self.pages_by_query = pages_by_query
        self.filters_seen = []

    def search(self, query, filters=None, k=8, mode="hybrid"):
        from types import SimpleNamespace

        from app.retrieval.types import ScoredChunk, SearchResult

        self.filters_seen.append(filters)
        hits = [ScoredChunk(SimpleNamespace(ticker=t, fiscal_year=y, page_start=p, page_end=p, section="Item 7",
                                            chunk_type="text"), 1.0) for t, y, p in self.pages_by_query[query][:k]]
        return SearchResult(query, mode, filters, hits, {"total": 5.0, "rerank": 4.0})


def test_evaluate_skips_unanswerable_and_applies_filters(tmp_path):
    from app.evaluation.run_retrieval_eval import evaluate, render_report

    rows = [
        _row(),
        _row(id="f1", category="follow_up", question="And 2024?", history=["prior"], standalone_query="standalone"),
        _row(id="u1", category="unanswerable", evidence=[], filters={}),
    ]
    questions = _load(tmp_path, rows)
    stub = _StubSearcher({questions[0].question: [("AAPL", 2024, 3), ("AAPL", 2024, 20)], "standalone": [("AAPL", 2024, 5)]})

    filtered = evaluate(stub, questions, "hybrid", filtered=True)
    assert [q.id for q in filtered.questions] == ["q1", "f1"]  # unanswerable skipped, follow-up uses standalone_query
    assert filtered.mean("mrr") == pytest.approx(0.25) and filtered.mean("mrr", "lookup") == 0.5
    assert stub.filters_seen[0].tickers == ("AAPL",)

    unfiltered = evaluate(stub, questions, "hybrid", filtered=False)
    assert stub.filters_seen[-1].is_empty()
    report = render_report([filtered, unfiltered], [filtered], questions)
    assert "| hybrid | gold | " in report and "| hybrid | none | " in report and "Reranker ablations" in report
