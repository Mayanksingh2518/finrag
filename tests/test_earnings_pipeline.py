"""Earnings release ingestion: fixtures mimic EDGAR's SGML wrapper and Tesla's slide-deck exhibits."""

import json
from dataclasses import asdict

from app.generation.context import Source
from app.ingestion.chunker import ChunkingConfig, chunk_filing
from app.ingestion.earnings_pipeline import is_slide_deck, normalize_slides, process_release, release_stats
from app.ingestion.html_parser import parse_filing, strip_sgml_wrapper
from app.ingestion.models import Block, Chunk, FilingMeta
from app.ingestion.sections import assign_release_sections

RELEASE = """<DOCUMENT>
<TYPE>EX-99.1
<SEQUENCE>2
<FILENAME>pr.htm
<TEXT>
<html><body>
<div><font style="font-weight:700">Exhibit 99.1</font></div>
<div><font style="font-weight:700">Test Corp Announces Third Quarter Results</font></div>
<div>Revenue for the quarter was $35.1 billion, up 94% from a year ago.</div>
<div><font style="font-weight:700">Income Statement</font></div>
<table>
<tr><td>($ in millions)</td><td colspan="2">Q3 FY25</td><td colspan="2">Q3 FY24</td></tr>
<tr><td>Revenue</td><td>$</td><td>35,082</td><td>$</td><td>18,120</td></tr>
<tr><td>Net income</td><td>$</td><td>19,309</td><td>$</td><td>9,243</td></tr>
</table>
</body></html>
</TEXT>
</DOCUMENT>"""
REF = {
    "ticker": "TEST", "company": "Test Corp", "fiscal_year": 2025, "fiscal_quarter": 3, "form": "8-K EX-99.1",
    "filing_date": "2024-11-20", "report_date": "2024-10-27", "source_url": "https://sec.gov/ex991.htm",
    "local_path": "TEST/8-K/FY2025_Q3_EX-99.1.htm",
}
META = FilingMeta.from_manifest(REF)


def words(text: str) -> int:
    return len(text.split())


def spaced(title: str) -> str:
    return " ".join(title.replace(" ", ""))


def release_chunks(tmp_path) -> list[Chunk]:
    path = tmp_path / REF["local_path"]
    path.parent.mkdir(parents=True)
    path.write_text(RELEASE)
    chunks, _ = process_release(REF, tmp_path, words, ChunkingConfig(), 512)
    return chunks


def test_sgml_wrapper_is_removed_and_plain_html_untouched():
    assert strip_sgml_wrapper(b"<html><body>x</body></html>") == b"<html><body>x</body></html>"
    assert strip_sgml_wrapper(b"<DOCUMENT>\n<TYPE>EX-99.1\n<TEXT>\n<html></html>\n</TEXT>\n</DOCUMENT>") == b"<html></html>"
    # Inside the wrapper lxml would read the page as one inline run: one text block, no table.
    blocks = parse_filing(RELEASE.encode()).blocks
    assert [b.kind for b in blocks].count("table") == 1 and len(blocks) > 3


def test_release_chunks_carry_quarter_and_no_pages(tmp_path):
    chunks = release_chunks(tmp_path)
    assert chunks[0].chunk_id == "TEST-FY2025-Q3-EX-99.1-0000" and chunks[0].doc_id == "TEST-FY2025-Q3-EX-99.1"
    for c in chunks:
        assert c.fiscal_quarter == 3 and c.form == "8-K EX-99.1" and c.section == "Earnings release"
        assert (c.page_start, c.page_end, c.page_label_start, c.page_label_end) == (0, 0, None, None)
        assert c.context.startswith("Test Corp (TEST) earnings release, Q3 fiscal year 2025, quarter ended 2024-10-27")


def test_release_table_keeps_its_figures_and_caption(tmp_path):
    table = next(c for c in release_chunks(tmp_path) if c.chunk_type == "table")
    assert table.subsection == "Income Statement" and "Income Statement\n\n|" in table.text
    assert "| Revenue | $35,082 | $18,120 |" in table.text


def test_exhibit_label_is_not_a_subsection():
    blocks = [Block(kind="heading", text="Exhibit 99.1", page=1), Block(kind="text", text="Body", page=1)]
    assign_release_sections(blocks)
    assert blocks[1].subsection is None


def test_10k_chunks_stay_as_they_were():
    meta = FilingMeta("TEST", "Test Corp", 2025, "10-K", "2026-02-01", "2025-12-31", "https://sec.gov/x")
    block = Block(kind="text", text="Body", page=7, section="Item 7", section_title="MD&A")
    chunk = chunk_filing([block], meta, {7: "23"}, words)[0]
    assert chunk.doc_id == "TEST-FY2025-10-K" and chunk.fiscal_quarter is None
    assert chunk.context == "Test Corp (TEST) Form 10-K, fiscal year 2025 | Item 7: MD&A"
    assert (chunk.page_start, chunk.page_label_start) == (7, "23")


def test_chunk_written_before_the_quarter_field_still_loads():
    row = asdict(chunk_filing([Block(kind="text", text="Body", page=1, section="Item 7", section_title="MD&A")],
                              FilingMeta("T", "T", 2025, "10-K", "", "", ""), {}, words)[0])
    del row["fiscal_quarter"]
    assert Chunk(**json.loads(json.dumps(row))).fiscal_quarter is None


def test_release_citation_and_prompt_header():
    chunk = chunk_filing([Block(kind="text", text="Body", page=1, section="Earnings release",
                                section_title="Earnings release", subsection="Outlook")], META, {}, words)[0]
    source = Source("S1", chunk, 1.0)
    assert source.citation == "[TEST Q3 FY2025 release]"
    assert source.render() == ("[S1] Test Corp (TEST) earnings release, Q3 fiscal year 2025, "
                               "quarter ended 2024-10-27 | Outlook\nBody")


def statement(rows: int) -> str:
    body = " ".join(f"Line item {i} {i},100 {i},200 {i},300 5%" for i in range(1, rows + 1))
    return f"{spaced('FINANCIAL SUMMARY')} ($ in millions) Q1-2024 Q2-2024 Q3-2024 YoY {body} 4"


def test_deck_statement_splits_with_the_period_header_on_every_piece():
    cfg = ChunkingConfig(target_tokens=60, max_tokens=80)
    out = normalize_slides([Block(kind="text", text=statement(30), page=4)], words, cfg)
    assert out[0].kind == "heading" and out[0].text == "FINANCIAL SUMMARY"
    tables = out[1:]
    assert len(tables) > 1 and all(b.kind == "table" for b in tables)
    assert all(b.text.startswith("($ in millions) Q1-2024 Q2-2024 Q3-2024 YoY\n") for b in tables)
    assert all(words(b.text) <= cfg.max_tokens for b in tables)
    assert sum(f"Line item {i} {i},100 {i},200 {i},300 5%" in b.text for b in tables for i in range(1, 31)) == 30


def test_deck_other_period_headers_are_recognized():
    for header in ("3Q-2020 4Q-2020 1Q-2021", "30-Jun-23 30-Sep-23 31-Dec-23", "2021 2022 2023 YoY"):
        out = normalize_slides([Block(kind="text", text=f"{header} Total assets 1,000 2,000 3,000 " * 2, page=1)],
                               words, ChunkingConfig())
        assert out[0].kind == "table" and header in out[0].text


def test_deck_titles_only_match_letter_spacing():
    prose = "Our Outlook is unchanged and the balance sheet remains strong, as we said in the last quarter."
    assert normalize_slides([Block(kind="text", text=prose, page=1)], words, ChunkingConfig())[0].text == prose
    out = normalize_slides([Block(kind="text", text=f"O u t l o o K {prose}", page=1)], words, ChunkingConfig())
    assert out[0].text == "OUTLOOK" and out[1].text == prose


def test_deck_detection_and_short_slides():
    deck = [Block(kind="text", text=f"slide {i}", page=i) for i in range(1, 13)]
    assert is_slide_deck(deck)
    assert normalize_slides(deck, words, ChunkingConfig()) == []  # photo captions and the cover
    assert not is_slide_deck(deck + [Block(kind="table", text="| a |", page=1)])
    assert not is_slide_deck(deck[:5])


def test_release_without_figures_is_flagged():
    chunk = chunk_filing([Block(kind="text", text="Only prose here.", page=1, section="Earnings release",
                                section_title="Earnings release")], META, {}, words)[0]
    stats = release_stats(META, [], [chunk], True, 512)
    assert stats["figures_missing"] and stats["chunks_over_limit"] == 0
