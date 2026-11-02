"""Which reporting period each column of an earnings release table belongs to.

Releases show several periods side by side, so a real figure can be the wrong answer: "440,808 vehicles in Q1 2024"
is the year-ago column of a five-quarter row. This reads the column labels so the verifier can tell. It answers only
when it is sure: dates it can't place, or a row whose cells don't line up with the header, give no answer (None), and
the figure is then judged as before.

A year-to-date column is labelled by the quarter it ends in. So a six-month figure can pass as that quarter's (no false
alarm, a missed error), but never as another period's.
"""

import re
from collections.abc import Callable

from app.agent.entities import fiscal_period_of
from app.ingestion.models import Chunk

Period = tuple[int, int]  # (fiscal quarter, fiscal year)

_QUARTER_FIRST = re.compile(r"Q([1-4])[\s-]*(?:FY\s?)?'?(\d{4}|\d{2})", re.IGNORECASE)  # Q1-2024, Q3 FY25, Q1 2022
_NUMBER_FIRST = re.compile(r"([1-4])Q[\s-]*'?(\d{4}|\d{2})", re.IGNORECASE)  # 1Q22, 3Q-2020
_DATE = re.compile(r"\d{1,2}-([A-Z][a-z]{2})-(\d{2})")  # 30-Jun-24, Tesla's balance sheet: its fiscal year is the calendar year
_MONTH_QUARTER = {"Mar": 1, "Jun": 2, "Sep": 3, "Dec": 4}
_YEAR = re.compile(r"20\d{2}")
_THREE_MONTHS = re.compile(r"three months ended|quarter ended", re.IGNORECASE)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH_DAY = re.compile(rf"({'|'.join(_MONTHS)})[a-z]*\.?\s+(\d{{1,2}}),?(?:\s+(20\d{{2}}))?", re.IGNORECASE)
_FLAT_LABEL = r"(?:Q[1-4]-\d{4}|[1-4]Q-\d{4}|\d{1,2}-[A-Z][a-z]{2}-\d{2})"
_FLAT_HEADER = re.compile(rf"((?:{_FLAT_LABEL}\s+)*{_FLAT_LABEL})(\s+YoY)?\s*$")
_FLAT_VALUE = re.compile(r"\(?-?\$?\d[\d,.]*%?\)?|-")


def _year(text: str) -> int:
    return int(text) if len(text) == 4 else 2000 + int(text)


def parse_label(cell: str) -> Period | None:
    cell = cell.strip()
    if m := _QUARTER_FIRST.fullmatch(cell) or _NUMBER_FIRST.fullmatch(cell):
        return int(m.group(1)), _year(m.group(2))
    if (m := _DATE.fullmatch(cell)) and m.group(1) in _MONTH_QUARTER:
        return _MONTH_QUARTER[m.group(1)], _year(m.group(2))
    return None


def split_row(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _markdown_header(chunk: Chunk) -> tuple[Period | None, ...] | None:
    rows = [line for line in chunk.text.split("\n") if line.startswith("|") and not line.startswith("|---")][:4]
    for row in rows:
        labels = tuple(parse_label(c) for c in split_row(row))
        if sum(label is not None for label in labels) >= 2:
            return labels
    if not _THREE_MONTHS.search(" ".join(rows)):  # a balance sheet's dates or a full-year table don't name quarters
        return None
    return _dated_header(rows, chunk) or _year_header(rows, chunk)


def _year_header(rows: list[str], chunk: Chunk) -> tuple[Period | None, ...] | None:
    """Year columns, where the period's calendar year is the fiscal year (NVIDIA's Q1 FY2022 column is headed 2021)."""
    if chunk.period_end[:4] != str(chunk.fiscal_year):
        return None
    for row in rows:
        cells = split_row(row)
        if sum(bool(_YEAR.fullmatch(c)) for c in cells) >= 2:
            return tuple((chunk.fiscal_quarter, int(c)) if _YEAR.fullmatch(c) else None for c in cells)  # type: ignore[misc]
    return None


def _dated_header(rows: list[str], chunk: Chunk) -> tuple[Period | None, ...] | None:
    """Period-end dates, on one row ("December 25, 2021") or two ("July 28," over "2024"), by the company's fiscal calendar."""
    for i, row in enumerate(rows):
        cells = split_row(row)
        below = split_row(rows[i + 1]) if i + 1 < len(rows) else []
        labels: list[Period | None] = []
        for j, cell in enumerate(cells):
            m = _MONTH_DAY.fullmatch(cell)
            year = m and (m.group(3) or (below[j] if len(below) == len(cells) and _YEAR.fullmatch(below[j]) else None))
            labels.append(fiscal_period_of(chunk.ticker, _MONTHS.index(m.group(1)[:3].lower()) + 1, int(m.group(2)), int(year))[::-1]
                          if year else None)
        if sum(label is not None for label in labels) >= 2:
            return tuple(labels)
    return None


def _flat_header(chunk: Chunk) -> tuple[tuple[Period, ...], bool] | None:
    """Tesla's flattened statements: every piece repeats a header line of period labels, maybe with YoY."""
    for line in chunk.text.split("\n")[:4]:
        if m := _FLAT_HEADER.search(line):
            labels = tuple(parse_label(c) for c in m.group(1).split())
            if len(labels) >= 2 and all(labels):
                return labels, bool(m.group(2))  # type: ignore[return-value]
    return None




def _chunk_headers(chunk: Chunk):
    if "|---" in chunk.text:
        return _markdown_header(chunk), None
    return None, _flat_header(chunk)


def known_periods(chunk: Chunk) -> set[Period]:
    """Every period this table labels; empty when its columns can't be read."""
    if chunk.chunk_type != "table":
        return set()
    markdown, flat = _chunk_headers(chunk)
    if markdown:
        return {p for p in markdown if p}
    return set(flat[0]) if flat else set()


def periods_of_figure(row: str, chunk: Chunk, matches: Callable[[str], bool]) -> set[Period] | None:
    """The periods of the columns where `matches` finds the figure in this row; None when that can't be said."""
    if chunk.chunk_type != "table":
        return None
    markdown, flat = _chunk_headers(chunk)
    if markdown:
        cells = split_row(row) if row.startswith("|") else []
        if len(cells) != len(markdown):
            return None
        labels = [markdown[j] for j, cell in enumerate(cells) if cell and matches(cell)]
        return set(labels) if labels and all(labels) else None  # type: ignore[arg-type]
    if not flat:
        return None
    labels_flat, has_yoy = flat
    width = len(labels_flat) + has_yoy
    tokens = row.split()
    found: set[Period] = set()
    i = 0
    while i < len(tokens):
        if not _FLAT_VALUE.fullmatch(tokens[i]):
            i += 1
            continue
        end = i
        while end < len(tokens) and _FLAT_VALUE.fullmatch(tokens[end]):
            end += 1
        run = tokens[i:end]
        i = end
        hits = [j for j, token in enumerate(run) if matches(token)]
        if not hits:
            continue
        if len(run) != width:  # a footnote or page number among the values: positions can't be trusted
            return None
        if any(j >= len(labels_flat) for j in hits):  # the YoY cell, not a period
            return None
        found |= {labels_flat[j] for j in hits}
    return found or None
