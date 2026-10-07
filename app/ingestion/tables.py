"""Clean SEC filing tables and render them as Markdown.

Filing tables are typeset for print: currency symbols, closing parentheses and
percent signs sit in their own cells, and spacer columns are everywhere. We
glue those fragments onto their numbers and drop empty columns so a row like
``["Net sales", "$", "416,161", "", "$", "391,035"]`` becomes
``["Net sales", "$416,161", "$391,035"]``.
"""

import re

_CURRENCY = frozenset({"$", "€", "£", "¥"})
# Fragments that belong to the preceding value: ")" "%" units, and letter
# footnote markers like "(g)". Numeric "(5)" is a negative number, not a marker.
_SUFFIX = re.compile(r"^(\)|%|\)%|%\)|pts|bps|x|\([a-z]{1,2}\))$", re.I)
_BULLET = re.compile(r"^(•|●|◦|▪|■|–|—|-|\(?[a-z0-9]{1,3}\)|\d{1,2}\.)$", re.I)
_VALUE = re.compile(r"^[($€£¥\-—–]*\d[\d,.]*")
_YEAR = re.compile(r"^(19|20)\d{2}$")


def clean_table(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return []
    width = max(len(r) for r in rows)
    grid = [r + [""] * (width - len(r)) for r in rows]

    for row in grid:
        for j, cell in enumerate(row):
            if cell in _CURRENCY:
                k = next((k for k in range(j + 1, width) if row[k]), None)
                if k is not None:
                    row[k] = cell + row[k]
                    row[j] = ""
        for j, cell in enumerate(row):
            if _SUFFIX.match(cell):
                k = next((k for k in range(j - 1, -1, -1) if row[k]), None)
                if k is not None:
                    row[k] = row[k] + cell
                    row[j] = ""

    keep_cols = [j for j in range(width) if any(row[j] for row in grid)]
    grid = [[row[j] for j in keep_cols] for row in grid if any(row[j] for j in keep_cols)]
    return _merge_complementary_columns(grid)


def _merge_complementary_columns(grid: list[list[str]]) -> list[list[str]]:
    """Merge adjacent columns that are never both filled in the same row.

    Headers and values of one logical column often land in different physical
    columns (a header spans "$", number and spacer cells; the value sits in the
    middle one). Columns that never collide are the same logical column.
    """
    j = 0
    while grid and j < len(grid[0]) - 1:
        if any(row[j] and row[j + 1] for row in grid):
            j += 1
            continue
        for row in grid:
            row[j] = row[j] or row[j + 1]
            del row[j + 1]
    return grid


LONG_CELL_CHARS = 400


def is_layout_table(rows: list[list[str]]) -> bool:
    """Tables used for layout (bullets, footers, prose in cells) rather than data."""
    if not rows or len(rows) == 1 or max(len(r) for r in rows) <= 1:
        return True
    if any(len(c) > LONG_CELL_CHARS for row in rows for c in row):
        return True
    return all(len(r) <= 2 and _BULLET.match(r[0]) for r in rows)


def layout_table_lines(rows: list[list[str]]) -> list[str]:
    """Bullet rows read as prose; wider rows keep their column boundaries."""
    lines = []
    for row in rows:
        cells = [c for c in row if c]
        lines.append((" " if len(cells) <= 2 else " | ").join(cells))
    return lines


def _is_value(cell: str) -> bool:
    return bool(_VALUE.match(cell)) and not _YEAR.match(cell)


def header_row_count(rows: list[list[str]]) -> int:
    """Leading rows without numeric values (years don't count) are column headers."""
    count = 0
    for row in rows[:3]:
        if any(_is_value(c) for c in row[1:]):
            break
        count += 1
    return max(1, min(count, len(rows) - 1)) if len(rows) > 1 else 1


def to_markdown(rows: list[list[str]], header_rows: int) -> str:
    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(c.replace("|", "\\|") for c in row) + " |"

    lines = []
    for i, row in enumerate(rows):
        lines.append(fmt(row))
        if i == header_rows - 1:
            lines.append("|" + "|".join(["---"] * len(row)) + "|")
    return "\n".join(lines)
