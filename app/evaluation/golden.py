"""Golden evaluation set: schema, loading and validation against the filing text.

Each evidence item names a filing (ticker, fiscal year), one or more short verbatim
quotes that support the answer, and the physical pages where they occur. Pages are
filled in by `resolve_pages` (every page of the filing containing a quote, so a fact
repeated in MD&A and the financial statements accepts either), and validation checks
each listed page really contains a quote. Labels are therefore machine-checked and
survive re-chunking: relevance is judged by page, not by chunk id.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.retrieval.types import SearchFilters

Category = Literal["lookup", "trend", "comparison", "numeric", "follow_up", "unanswerable"]
CATEGORIES: tuple[Category, ...] = ("lookup", "trend", "comparison", "numeric", "follow_up", "unanswerable")


def normalize(text: str) -> str:
    """Collapse whitespace and unify quotes/dashes so quotes match regardless of HTML formatting."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("—", "-").replace("–", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class GoldEvidence:
    ticker: str
    fiscal_year: int
    pages: tuple[int, ...]  # physical page indexes; any of them satisfies this item
    quotes: tuple[str, ...]  # verbatim text; every listed page contains at least one


@dataclass(frozen=True)
class GoldQuestion:
    id: str
    category: Category
    question: str
    reference_answer: str
    evidence: tuple[GoldEvidence, ...]
    # Filters the Phase 6 query analyzer should extract; retrieval eval can run with or without them.
    filters: SearchFilters = SearchFilters()
    # Follow-ups: prior turns, plus the standalone rewrite that retrieval is evaluated on.
    history: tuple[str, ...] = ()
    standalone_query: str | None = None
    notes: str = ""
    tags: tuple[str, ...] = field(default=())

    @property
    def answerable(self) -> bool:
        return bool(self.evidence)

    @property
    def retrieval_query(self) -> str:
        return self.standalone_query or self.question


def _parse(row: dict) -> GoldQuestion:
    f = row.get("filters") or {}
    return GoldQuestion(
        id=row["id"],
        category=row["category"],
        question=row["question"],
        reference_answer=row["reference_answer"],
        evidence=tuple(
            GoldEvidence(
                e["ticker"], int(e["fiscal_year"]), tuple(int(p) for p in e.get("pages", [])), tuple(e["quotes"])
            )
            for e in row.get("evidence", [])
        ),
        filters=SearchFilters(
            tickers=tuple(f["tickers"]) if f.get("tickers") else None,
            fiscal_years=tuple(int(y) for y in f["fiscal_years"]) if f.get("fiscal_years") else None,
            sections=tuple(f["sections"]) if f.get("sections") else None,
        ),
        history=tuple(row.get("history", [])),
        standalone_query=row.get("standalone_query"),
        notes=row.get("notes", ""),
        tags=tuple(row.get("tags", [])),
    )


def load_golden(path: Path) -> list[GoldQuestion]:
    with path.open(encoding="utf-8") as fh:
        return [_parse(json.loads(line)) for line in fh if line.strip()]


@dataclass(frozen=True)
class PageText:
    label: str | None
    text: str


PageKey = tuple[str, int, int]  # (ticker, fiscal_year, physical page index)


def load_pages(path: Path) -> dict[PageKey, PageText]:
    pages: dict[PageKey, PageText] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            pages[(r["ticker"], int(r["fiscal_year"]), int(r["index"]))] = PageText(r["label"], r["text"])
    return pages


def validate(questions: Iterable[GoldQuestion], pages: dict[PageKey, PageText]) -> list[str]:
    """Return human-readable problems; an empty list means the set is consistent with the filings."""
    problems: list[str] = []
    seen: set[str] = set()
    normalized: dict[PageKey, str] = {}
    for q in questions:
        where = f"{q.id}:"
        if q.id in seen:
            problems.append(f"{where} duplicate id")
        seen.add(q.id)
        if q.category not in CATEGORIES:
            problems.append(f"{where} unknown category {q.category!r}")
        if (q.category == "unanswerable") == q.answerable:
            problems.append(f"{where} unanswerable questions must have no evidence, others must have some")
        if q.category == "follow_up" and not (q.history and q.standalone_query):
            problems.append(f"{where} follow_up needs history and standalone_query")
        for e in q.evidence:
            if q.filters.tickers and e.ticker not in q.filters.tickers:
                problems.append(f"{where} evidence ticker {e.ticker} outside filters {q.filters.tickers}")
            if q.filters.fiscal_years and e.fiscal_year not in q.filters.fiscal_years:
                problems.append(f"{where} evidence FY{e.fiscal_year} outside filters {q.filters.fiscal_years}")
            if not e.pages:
                problems.append(f"{where} evidence without pages")
            if not e.quotes:
                problems.append(f"{where} evidence without quotes")
            quotes = [normalize(qt).lower() for qt in e.quotes]
            for p in e.pages:
                key = (e.ticker, e.fiscal_year, p)
                if key not in pages:
                    problems.append(f"{where} no such page {key}")
                    continue
                if key not in normalized:
                    normalized[key] = normalize(pages[key].text).lower()
                if not any(qt in normalized[key] for qt in quotes):
                    problems.append(f"{where} none of {e.quotes[0][:50]!r}... found on {key}")
    return problems


def resolve_pages(ticker: str, fiscal_year: int, quotes: Iterable[str], pages: dict[PageKey, PageText]) -> tuple[int, ...]:
    """Every physical page of the filing that contains at least one of the quotes."""
    needles = [normalize(q).lower() for q in quotes]
    return tuple(
        index
        for (t, y, index), page in sorted(pages.items())
        if t == ticker and y == fiscal_year and any(n in normalize(page.text).lower() for n in needles)
    )
