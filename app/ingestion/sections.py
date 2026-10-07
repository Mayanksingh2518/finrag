"""Assign 10-K Part/Item sections and subsection headings to blocks.

Section titles are canonical (from Form 10-K's structure) rather than copied
from each filing, so a metadata filter like ``section == "Item 1A"`` means the
same thing for every company.
"""

import re
from collections import Counter

from app.ingestion.models import Block

ITEM_TITLES: dict[str, str] = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities",
    "6": "[Reserved]",
    "7": "Management's Discussion and Analysis of Financial Condition and Results of Operations",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants on Accounting and Financial Disclosure",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Disclosure Regarding Foreign Jurisdictions that Prevent Inspections",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters",
    "13": "Certain Relationships and Related Transactions, and Director Independence",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}
ITEM_ORDER = {item: i for i, item in enumerate(ITEM_TITLES)}
CORE_ITEMS = ("1", "1A", "7", "7A", "8")

COVER_SECTION = "Cover"
COVER_TITLE = "Cover Page and Table of Contents"

_ITEM_RE = re.compile(r"^(?:part\s+(?:iv|i{1,3})\W*)?items?\s+(\d{1,2}[a-c]?)\b", re.I)
_PART_RE = re.compile(r"^part\s+(iv|i{1,3})\b", re.I)
ITEM_HEADING_MAX_CHARS = 200
TOC_MIN_ITEMS_PER_PAGE = 4
TOC_MAX_AVG_GAP_CHARS = 80

# Some filers (JPMorgan; NVIDIA FY2022) satisfy Items 7/8 by reference to an
# annex after Part IV. Inside that annex, these headings identify the logical item.
_ANNEX_HEADINGS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^management.?s discussion and analysis", re.I), "7"),
    (re.compile(r"^quantitative and qualitative disclosures? about market risk", re.I), "7A"),
    (
        re.compile(
            r"^(notes to (the )?consolidated financial statements"
            r"|consolidated (balance sheets?|statements? of)"
            r"|report of independent registered public accounting firm"
            r"|index to (the )?consolidated financial statements)",
            re.I,
        ),
        "8",
    ),
]
ANNEX_ITEMS_AFTER = ("15", "16")
STUB_MAX_BLOCKS = 10  # an item with fewer content blocks is a by-reference placeholder


def _item_candidate(block: Block) -> str | None:
    if block.kind == "table" or len(block.text) > ITEM_HEADING_MAX_CHARS:
        return None
    # Cross-references ("Item 7 of this report discusses...") are long body text,
    # real headings are bold or short.
    if block.kind != "heading" and len(block.text) > 100:
        return None
    match = _ITEM_RE.match(block.text)
    if not match:
        return None
    item = match.group(1).upper()
    return item if item in ITEM_TITLES else None


def _toc_pages(blocks: list[Block], candidates: dict[int, str]) -> set[int]:
    """Pages listing many items with almost no text between them (a table of contents).

    By-reference placeholder items also cluster on one page, but each carries a
    sentence ("The information required by this item is included on page F-1"),
    so the gap test tells them apart.
    """
    by_page: dict[int, list[int]] = {}
    for i in candidates:
        by_page.setdefault(blocks[i].page, []).append(i)

    toc = set()
    for page, idxs in by_page.items():
        if len(idxs) < TOC_MIN_ITEMS_PER_PAGE:
            continue
        gaps = [
            sum(len(blocks[k].text) for k in range(a + 1, b) if not blocks[k].furniture)
            for a, b in zip(idxs, idxs[1:])
        ]
        if sum(gaps) / len(gaps) < TOC_MAX_AVG_GAP_CHARS:
            toc.add(page)
    return toc


def _annex_item(block: Block) -> str | None:
    if block.kind == "table" or len(block.text) > 120:
        return None
    if block.kind != "heading" and not block.furniture:
        return None
    text = block.text.replace("’", "'")
    return next((item for pattern, item in _ANNEX_HEADINGS if pattern.match(text)), None)


def assign_sections(blocks: list[Block]) -> None:
    """Annotate blocks in place with part, section, section_title and subsection."""
    candidates = {i: item for i, b in enumerate(blocks) if (item := _item_candidate(b))}
    toc_pages = _toc_pages(blocks, candidates)

    # Pass 1: forward-only walk over Item headings.
    items: list[str | None] = []
    current: str | None = None
    for i, block in enumerate(blocks):
        item = candidates.get(i)
        # Items only move forward; an out-of-order match is a cross-reference.
        if item and block.page not in toc_pages and (
            current is None or ITEM_ORDER[item] >= ITEM_ORDER[current]
        ):
            current = item
        items.append(current)

    # Pass 2: relabel annex content after Part IV when the regular item was a stub.
    content_counts = Counter(it for it, b in zip(items, blocks) if not b.furniture)
    stubs = {it for it in ITEM_TITLES if content_counts[it] < STUB_MAX_BLOCKS}
    annex: str | None = None
    for i, block in enumerate(blocks):
        if items[i] not in ANNEX_ITEMS_AFTER:
            annex = None
            continue
        if i in candidates:  # a real Item heading ends any annex region
            annex = None
        elif (mapped := _annex_item(block)) and mapped in stubs:
            annex = mapped
        if annex:
            items[i] = annex

    # Pass 3: write labels, tracking Part and subsection headings.
    part: str | None = None
    subsection: str | None = None
    previous: str | None = None
    for i, block in enumerate(blocks):
        item = items[i]
        if item != previous:
            subsection = None
            previous = item
        if (
            block.kind != "table"
            and block.page not in toc_pages
            and (m := _PART_RE.match(block.text))
        ):
            part = f"Part {m.group(1).upper()}"
        elif (
            block.kind == "heading"
            and not block.furniture
            and item
            and i not in candidates
            and not _is_title_echo(block.text, item)
        ):
            subsection = block.text

        block.part = part
        block.section = f"Item {item}" if item else COVER_SECTION
        block.section_title = ITEM_TITLES[item] if item else COVER_TITLE
        block.subsection = subsection


def _is_title_echo(text: str, item: str) -> bool:
    """Headings that just repeat the item title ("BUSINESS") add no information."""
    norm = re.sub(r"[^a-z]", "", text.lower())
    return bool(norm) and re.sub(r"[^a-z]", "", ITEM_TITLES[item].lower()).startswith(norm)
