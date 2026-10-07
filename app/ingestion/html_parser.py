"""Parse SEC 10-K inline-XBRL HTML into page-aware content blocks.

Pipeline:
1. Walk the DOM in document order, emitting leaf blocks (paragraphs, headings,
   tables) and advancing the page counter at CSS page breaks. Inline elements
   (spans, ix:nonFraction) are concatenated so "$" and "288" stay together.
2. Detect repeated headers/footers ("Table of Contents", "MASTERCARD 2023 FORM
   10-K") by frequency across pages and drop them.
3. Read the printed page number from each page's footer, then validate it
   against neighbouring pages so stray numbers aren't mistaken for page labels.
"""

import re
from collections import defaultdict

from lxml import html as lxml_html

from app.ingestion.models import Block, Page, ParsedFiling
from app.ingestion.tables import (
    clean_table,
    header_row_count,
    is_layout_table,
    layout_table_lines,
    to_markdown,
)

BLOCK_TAGS = frozenset(
    "html body div p ul ol li h1 h2 h3 h4 h5 h6 section article center blockquote table hr".split()
)
HEADING_MAX_CHARS = 250
BOILERPLATE_MAX_CHARS = 100
BOILERPLATE_MIN_PAGE_SHARE = 0.25
# Short lines that repeat but carry meaning (table units) must survive boilerplate removal.
_KEEP_REPEATED = re.compile(r"million|billion|thousand|%|except", re.I)

_WS = re.compile(r"\s+")
_FONT_WEIGHT = re.compile(r"font-weight:(\w+)")
_LABEL = r"((?:[A-Z]-)?\d{1,3})"
_PAGE_LABEL_PATTERNS = [
    re.compile(rf"^(?:page\s+)?{_LABEL}\.?$", re.I),  # "6", "5.", "F-12"
    re.compile(rf"\|\s*{_LABEL}$"),  # "Apple Inc. | 2025 Form 10-K | 2"
    re.compile(rf"^{_LABEL}\s+\S.*\b10-K\b", re.I),  # "20 MASTERCARD 2025 FORM 10-K"
    re.compile(rf"\b10-K\s*\|?\s*{_LABEL}$", re.I),  # "MASTERCARD 2025 FORM 10-K 21"
]


def _style(el) -> str:
    return (el.get("style") or "").replace(" ", "").lower()


def _is_hidden(el) -> bool:
    return "display:none" in _style(el)


def _is_element(node) -> bool:
    return isinstance(node.tag, str)  # comments / processing instructions have callable tags


def _bold(el, inherited: bool) -> bool:
    if el.tag in ("b", "strong"):
        return True
    match = _FONT_WEIGHT.search(_style(el))
    if match:
        weight = match.group(1)
        return weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 600)
    return inherited


def _collect_runs(el, bold: bool, runs: list[tuple[str, bool]]) -> None:
    """Append (text, is_bold) runs for an inline subtree."""
    if el.text:
        runs.append((el.text, bold))
    for child in el:
        if _is_element(child) and not _is_hidden(child):
            if child.tag == "br":
                runs.append((" ", bold))
            else:
                # Block children inside a table cell are separate lines: keep a word boundary.
                is_block = child.tag in BLOCK_TAGS
                if is_block:
                    runs.append((" ", bold))
                _collect_runs(child, _bold(child, bold), runs)
                if is_block:
                    runs.append((" ", bold))
        if child.tail:
            runs.append((child.tail, bold))


def _span(cell, attr: str) -> int:
    try:
        return max(1, min(int(cell.get(attr) or 1), 1000))
    except ValueError:
        return 1


def _cell_text(cell) -> str:
    runs: list[tuple[str, bool]] = []
    _collect_runs(cell, False, runs)
    return normalize_ws("".join(t for t, _ in runs))


def normalize_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


class _Walker:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.page = 1
        self._page_has_content = False

    def _page_break(self) -> None:
        # Collapse consecutive breaks so blank separator pages don't inflate the count.
        if self._page_has_content:
            self.page += 1
            self._page_has_content = False

    def _emit(self, block: Block) -> None:
        self.blocks.append(block)
        self._page_has_content = True

    def _flush_runs(self, runs: list[tuple[str, bool]]) -> None:
        text = normalize_ws("".join(t for t, _ in runs))
        if not text:
            return
        total = sum(len(t) - t.count(" ") for t, _ in runs)
        bold = sum(len(t) - t.count(" ") for t, b in runs if b)
        is_heading = total > 0 and bold / total >= 0.9 and len(text) <= HEADING_MAX_CHARS
        self._emit(Block(kind="heading" if is_heading else "text", text=text, page=self.page))

    def _table(self, el) -> None:
        raw_rows = []
        row_spans: dict[int, int] = {}  # column -> remaining rows still covered by a rowspan above
        for tr in el.iter("tr"):
            row: list[str] = []

            def skip_spanned_columns() -> None:
                while len(row) in row_spans:
                    col = len(row)
                    row.append("")
                    row_spans[col] -= 1
                    if not row_spans[col]:
                        del row_spans[col]

            for cell in tr:
                if not _is_element(cell) or cell.tag not in ("td", "th") or _is_hidden(cell):
                    continue
                skip_spanned_columns()
                colspan, rowspan = _span(cell, "colspan"), _span(cell, "rowspan")
                start = len(row)
                # Numbers are right-aligned: a value spanning the "$" column and the
                # number column belongs in the last spanned column.
                row.extend([""] * (colspan - 1))
                row.append(_cell_text(cell))
                if rowspan > 1:
                    row_spans.update({c: rowspan - 1 for c in range(start, start + colspan)})
            skip_spanned_columns()
            raw_rows.append(row)

        rows = clean_table(raw_rows)
        if not rows:
            return
        if is_layout_table(rows):
            for line in layout_table_lines(rows):
                self._emit(Block(kind="text", text=line, page=self.page))
            return
        header_rows = header_row_count(rows)
        self._emit(
            Block(
                kind="table",
                text=to_markdown(rows, header_rows),
                page=self.page,
                rows=rows,
                header_rows=header_rows,
            )
        )

    def walk(self, el, bold: bool = False) -> None:
        if not _is_element(el) or _is_hidden(el):
            return
        style = _style(el)
        bold = _bold(el, bold)
        if "page-break-before:always" in style or "break-before:page" in style:
            self._page_break()

        if el.tag == "table":
            self._table(el)
        elif el.tag != "hr":
            runs: list[tuple[str, bool]] = []
            if el.text:
                runs.append((el.text, bold))
            for child in el:
                if _is_element(child) and child.tag in BLOCK_TAGS:
                    self._flush_runs(runs)
                    runs = []
                    self.walk(child, bold)
                elif _is_element(child) and not _is_hidden(child):
                    if child.tag == "br":
                        runs.append((" ", bold))
                    else:
                        _collect_runs(child, _bold(child, bold), runs)
                if child.tail:
                    runs.append((child.tail, bold))
            self._flush_runs(runs)

        if "page-break-after:always" in style or "break-after:page" in style:
            self._page_break()


def _boilerplate_key(block: Block) -> str | None:
    if block.kind == "table" or len(block.text) > BOILERPLATE_MAX_CHARS:
        return None
    if _KEEP_REPEATED.search(block.text):
        return None
    return re.sub(r"\d+", "#", block.text.lower())


def _find_boilerplate(blocks: list[Block], num_pages: int) -> set[str]:
    pages_by_key: dict[str, set[int]] = defaultdict(set)
    for b in blocks:
        key = _boilerplate_key(b)
        if key:
            pages_by_key[key].add(b.page)
    threshold = max(5, BOILERPLATE_MIN_PAGE_SHARE * num_pages)
    return {k for k, pages in pages_by_key.items() if len(pages) >= threshold}


def _match_page_label(text: str) -> str | None:
    if len(text) > BOILERPLATE_MAX_CHARS:
        return None
    for pattern in _PAGE_LABEL_PATTERNS:
        if match := pattern.search(text):
            return match.group(1).upper()
    return None


def _detect_page_labels(blocks: list[Block]) -> tuple[dict[int, str], set[int]]:
    """Return {page_index: printed label} and the indices of footer blocks to drop."""
    by_page: dict[int, list[int]] = defaultdict(list)
    for i, b in enumerate(blocks):
        if b.kind != "table":
            by_page[b.page].append(i)

    raw: dict[int, str] = {}
    footer_ids: set[int] = set()
    for page, idxs in by_page.items():
        for i in idxs[-3:][::-1] + idxs[:2]:  # footers first, then headers
            label = _match_page_label(blocks[i].text)
            if label:
                raw[page] = label
                footer_ids.add(i)
                break

    # A printed number counts as a page label only if a neighbouring page agrees.
    nums = {p: int(l) for p, l in raw.items() if l.isdigit()}
    valid = {p for p, n in nums.items() if nums.get(p - 1) == n - 1 or nums.get(p + 1) == n + 1}
    labels = {p: l for p, l in raw.items() if p in valid or not l.isdigit()}

    # Fill single gaps (e.g. a full-page table without a footer) when both sides agree.
    ordered = sorted(valid)
    for a, b in zip(ordered, ordered[1:]):
        if 1 < b - a and nums[b] - nums[a] == b - a:
            for p in range(a + 1, b):
                labels[p] = str(nums[a] + p - a)
    return labels, footer_ids


def parse_filing(content: bytes) -> ParsedFiling:
    root = lxml_html.fromstring(content)
    body = root.find("body")
    walker = _Walker()
    walker.walk(body if body is not None else root)
    blocks = walker.blocks
    if not blocks:
        return ParsedFiling(blocks=[], pages=[])

    num_pages = max(b.page for b in blocks)
    labels, footer_ids = _detect_page_labels(blocks)
    boilerplate = _find_boilerplate(blocks, num_pages)
    page_texts: dict[int, list[str]] = defaultdict(list)
    for i, b in enumerate(blocks):
        b.furniture = i in footer_ids or _boilerplate_key(b) in boilerplate
        if not b.furniture:
            page_texts[b.page].append(b.text)

    pages = [
        Page(index=p, label=labels.get(p), text="\n".join(page_texts.get(p, [])))
        for p in range(1, num_pages + 1)
    ]
    return ParsedFiling(blocks=blocks, pages=pages)
