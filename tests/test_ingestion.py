"""Ingestion tests built from small HTML fixtures that mimic real 10-K quirks."""

from app.ingestion.chunker import ChunkingConfig, chunk_filing
from app.ingestion.html_parser import parse_filing
from app.ingestion.models import Block, FilingMeta
from app.ingestion.sections import assign_sections
from app.ingestion.tables import clean_table, header_row_count, is_layout_table

PAGE_BREAK = '<hr style="page-break-after:always"/>'
META = FilingMeta("TEST", "Test Corp", 2025, "10-K", "2026-02-01", "2025-12-31", "https://sec.gov/x")


def words(text: str) -> int:
    return len(text.split())


def filing(*pages: str) -> bytes:
    return f"<html><body>{PAGE_BREAK.join(pages)}</body></html>".encode()


def para(text: str, bold: bool = False) -> str:
    weight = 700 if bold else 400
    return f'<div><span style="font-weight:{weight}">{text}</span></div>'


# --- tables -----------------------------------------------------------------


def test_clean_table_glues_currency_suffixes_and_aligns_headers():
    rows = [
        ["", "", "2025", "", "", "Change", ""],
        ["iPhone", "$", "209,586", "", "4", "%", ""],
        ["Mac", "", "33,708", "", "(4", ")%", ""],
    ]
    assert clean_table(rows) == [
        ["", "2025", "Change"],
        ["iPhone", "$209,586", "4%"],
        ["Mac", "33,708", "(4)%"],
    ]


def test_letter_footnotes_attach_but_negative_numbers_do_not():
    assert clean_table([["Revenue", "177,556", "(g)", "(5)"]]) == [["Revenue", "177,556(g)", "(5)"]]


def test_header_rows_ignore_years():
    rows = [["Title", "", ""], ["", "2025", "2024"], ["Revenue", "$10", "$9"]]
    assert header_row_count(rows) == 2


def test_layout_tables():
    assert is_layout_table([["148", "JPMorgan Chase & Co./2025 Form 10-K"]])  # one-row footer
    assert is_layout_table([["•", "first bullet"], ["•", "second bullet"]])
    assert is_layout_table([["Matter", "x" * 500], ["Other", "y"]])  # prose in cells
    assert not is_layout_table([["", "2025"], ["Revenue", "$10"]])


# --- HTML parsing -----------------------------------------------------------


def test_inline_spans_join_and_hidden_xbrl_is_dropped():
    html = filing(
        '<div style="display:none"><ix:header>hidden facts</ix:header></div>'
        '<div><span>was </span><span>$</span><ix:nonfraction>288</ix:nonfraction><span> million</span></div>'
    )
    parsed = parse_filing(html)
    assert [b.text for b in parsed.blocks] == ["was $288 million"]


def test_pages_labels_and_furniture():
    bodies = ["Alpha grew.", "Beta fell.", "Gamma held.", "Delta rose.", "Epsilon dipped.", "Zeta led."]
    pages = [
        para("Table of Contents") + para(body) + para(f"MASTERCARD 2025 FORM 10-K {i}")
        for i, body in enumerate(bodies, start=1)
    ]
    parsed = parse_filing(filing(*pages))
    assert [p.label for p in parsed.pages] == ["1", "2", "3", "4", "5", "6"]
    content = [b.text for b in parsed.blocks if not b.furniture]
    assert content == bodies
    assert parsed.pages[2].text == "Gamma held."


def test_isolated_number_is_not_a_page_label():
    parsed = parse_filing(filing(para("Intro") + para("42"), para("Next page")))
    assert parsed.pages[0].label is None


def test_rowspan_keeps_columns_aligned():
    table = (
        "<table>"
        '<tr><td rowspan="2">Year ended (in millions)</td><td>Rev</td></tr>'
        "<tr><td>2025</td></tr>"
        "<tr><td>Revenue</td><td>100</td></tr>"
        "<tr><td>Cost</td><td>40</td></tr>"
        "</table>"
    )
    block = parse_filing(filing(table)).blocks[0]
    assert block.kind == "table"
    assert block.rows == [["Year ended (in millions)", "Rev"], ["", "2025"], ["Revenue", "100"], ["Cost", "40"]]


# --- sections ---------------------------------------------------------------


def _blocks(*specs: tuple[str, str, int]) -> list[Block]:
    return [Block(kind=kind, text=text, page=page) for kind, text, page in specs]  # type: ignore[arg-type]


def test_sections_skip_toc_and_cross_references():
    blocks = _blocks(
        ("text", "Item 1. Business", 1),  # TOC page: items with no text between them
        ("text", "Item 1A. Risk Factors", 1),
        ("text", "Item 7. MD&A", 1),
        ("text", "Item 8. Financial Statements", 1),
        ("heading", "Item 1. Business", 2),
        ("text", "We make things.", 2),
        ("heading", "Item 7. Management's Discussion", 3),
        ("text", "Item 1A. Risk Factors", 3),  # out of order -> cross-reference
        ("heading", "Revenue", 3),
        ("text", "Revenue grew.", 3),
    )
    assign_sections(blocks)
    assert [b.section for b in blocks] == ["Cover"] * 4 + ["Item 1"] * 2 + ["Item 7"] * 4
    assert blocks[-1].subsection == "Revenue"
    assert blocks[-1].section_title.startswith("Management's Discussion")


def test_annex_content_maps_back_to_stub_items():
    stub = "The information required by this item appears in the annex of this report."
    blocks = _blocks(
        ("heading", "Item 7. Management's Discussion and Analysis", 1),
        ("text", stub, 1),
        ("heading", "Item 8. Financial Statements and Supplementary Data", 1),
        ("text", stub, 1),
        ("heading", "Item 15. Exhibits", 2),
        ("text", "Exhibit list", 2),
        ("heading", "Management's discussion and analysis", 3),
        ("text", "Net revenue rose.", 3),
        ("heading", "Notes to consolidated financial statements", 4),
        ("text", "Note 1 basis of presentation.", 4),
    )
    assign_sections(blocks)
    assert [b.section for b in blocks[4:]] == ["Item 15", "Item 15", "Item 7", "Item 7", "Item 8", "Item 8"]


# --- chunking ---------------------------------------------------------------


def _section_blocks(section: str, *specs: tuple[str, str]) -> list[Block]:
    return [
        Block(kind=k, text=t, page=1, section=section, section_title=section)  # type: ignore[arg-type]
        for k, t in specs
    ]


def test_chunks_respect_sections_and_size():
    sentence = "Revenue grew because demand increased strongly. "
    blocks = _section_blocks("Item 1", ("text", sentence * 40)) + _section_blocks("Item 7", ("text", sentence * 5))
    cfg = ChunkingConfig(target_tokens=60, max_tokens=80, overlap_tokens=10)
    chunks = chunk_filing(blocks, META, {1: "3"}, words, cfg)
    assert {c.section for c in chunks} == {"Item 1", "Item 7"}
    assert all(words(c.text) <= cfg.max_tokens for c in chunks)
    assert all(not (c.section == "Item 1" and "Item 7" in c.context) for c in chunks)
    assert chunks[0].page_label_start == "3"
    assert chunks[0].chunk_id == "TEST-FY2025-10-K-0000"


def test_lone_heading_becomes_table_caption():
    table = Block(kind="table", text="| | 2025 |\n|---|---|\n| Revenue | $10 |", page=1,
                  rows=[["", "2025"], ["Revenue", "$10"]], header_rows=1, section="Item 8", section_title="FS")
    blocks = _section_blocks("Item 8", ("heading", "Note 5. Revenue")) + [table]
    chunks = chunk_filing(blocks, META, {}, words, ChunkingConfig())
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "table"
    assert chunks[0].text.startswith("Note 5. Revenue")


def test_large_table_splits_with_repeated_header():
    rows = [["", "2025", "2024"]] + [[f"Line item {i}", f"{i},000", f"{i},500"] for i in range(60)]
    table = Block(kind="table", text="x " * 1000, page=1, rows=rows, header_rows=1, section="Item 8", section_title="FS")
    chunks = chunk_filing([table], META, {}, words, ChunkingConfig(target_tokens=60, max_tokens=80))
    assert len(chunks) > 1
    assert all("| 2025 | 2024 |" in c.text for c in chunks)
    assert chunks[1].text.startswith("(continued)")
    assert all(words(c.text) <= 80 for c in chunks)


def test_furniture_is_not_chunked():
    blocks = _section_blocks("Item 1", ("text", "Real content here."), ("text", "Table of Contents"))
    blocks[1].furniture = True
    chunks = chunk_filing(blocks, META, {}, words, ChunkingConfig())
    assert [c.text for c in chunks] == ["Real content here."]
