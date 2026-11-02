"""Ingestion of earnings releases (8-K Exhibit 99.1): raw HTML -> chunks + quality report.

Reuses the 10-K parser and chunker. The differences: no Items (one section, headings as subsections),
no printed pages (citations name the release), and Tesla's slide decks. A Tesla exhibit is one image per
slide over a hidden text layer, so a statement arrives as one flat run of words: letter-spaced titles
("F I N A N C I A L S U M M A R Y") are restored, and each statement is split into rows and packed into
pieces that all repeat the period header, because a figure without its column can't be read.

Usage:
    python -m app.ingestion.earnings_pipeline
    python -m app.ingestion.earnings_pipeline --tickers NVDA TSLA --years 2025

Outputs (data/processed/, merged into the index in a later step):
    chunks_earnings.jsonl           one chunk per line
    earnings_quality_report.json    per-release statistics
    earnings_quality_report.md      the same, human-readable
"""

import argparse
import json
import logging
import re
import statistics
from dataclasses import asdict
from pathlib import Path

from app.config import get_settings
from app.ingestion.chunker import ChunkingConfig, TokenCounter, _split_oversized, chunk_filing
from app.ingestion.html_parser import parse_filing
from app.ingestion.models import Block, Chunk, FilingMeta
from app.ingestion.sections import assign_release_sections
from app.ingestion.tokens import get_token_counter

logger = logging.getLogger(__name__)

DECK_MIN_SLIDES = 10
SLIDE_MIN_CHARS = 60  # shorter slides are photo captions and the cover
MAX_TABLE_PREFIX_CHARS = 200  # text before a period header longer than this is prose, not the table's title
MIN_FIGURES = 50  # fewer comma-grouped numbers than this: the statements aren't in the text (images)

_SLIDE_TITLES = (
    "RECONCILIATION OF GAAP TO NON-GAAP FINANCIAL INFORMATION", "KEY METRICS TRAILING 12 MONTHS",
    "KEY METRICS QUARTERLY", "STATEMENT OF CASH FLOWS", "STATEMENT OF OPERATIONS", "FINANCIAL STATEMENTS",
    "FINANCIAL SUMMARY", "OPERATIONAL SUMMARY", "SUMMARY HIGHLIGHTS", "ADDITIONAL INFORMATION", "CORE TECHNOLOGY",
    "VEHICLE CAPACITY", "OTHER HIGHLIGHTS", "BALANCE SHEET", "PHOTOS & CHARTS", "OUTLOOK",
)


def _spaced(title: str) -> re.Pattern:
    """Match a title in the text layer's spacing: every letter apart, word boundaries lost."""
    letters = [r"\s*[-–]\s*" if c == "-" else re.escape(c) for c in title.replace(" ", "")]
    return re.compile(r"\s*".join(letters), re.I)


def _remove_spaced_title(pattern: re.Pattern, text: str) -> tuple[str, bool]:
    """Remove a letter-spaced title; the same words in normal prose ("Outlook", "balance sheet") stay."""
    found = False

    def replace(match: re.Match) -> str:
        nonlocal found
        spaced = match.group().count(" ") * 2 >= len(match.group().replace(" ", ""))
        found = found or spaced
        return " " if spaced else match.group()

    return pattern.sub(replace, text), found


_TITLE_PATTERNS = [(t, _spaced(t)) for t in _SLIDE_TITLES]
_LETTER_SPACED = re.compile(r"(?<![A-Za-z])(?:[A-Za-z&] ){3,}[A-Za-z&](?![A-Za-z])")
_PERIOD_HEADER = re.compile(
    r"(?:(?:(?:Q[1-4]-\d{4}|[1-4]Q-\d{4}|\d{1,2}-[A-Z][a-z]{2}-\d{2})\s+){2,}|(?:(?:19|20)\d{2}\s+){3,})(?:YoY\s+)?"
)
# A flat row ends in a figure ("-7%", "(2,060)", "-23 bp"); the next row's label starts with a capital.
_ROW_BREAK = re.compile(r"(?:(?<=[\d%)-])|(?<=bp)) (?=[A-Z][A-Za-z])")
_FIGURE = re.compile(r"\d{1,3}(?:,\d{3})+")


def is_slide_deck(blocks: list[Block]) -> bool:
    pages = {b.page for b in blocks}
    return len(pages) >= DECK_MIN_SLIDES and len(blocks) <= len(pages) * 2 and not any(b.kind == "table" for b in blocks)


def _flat_table_blocks(text: str, page: int, count: TokenCounter, cfg: ChunkingConfig) -> list[Block] | None:
    """Rows of a flattened statement, packed into table blocks that each start with the period header."""
    header = _PERIOD_HEADER.search(text)
    if not header:
        return None
    before = text[: header.start()].strip()
    blocks = []
    if len(before) > MAX_TABLE_PREFIX_CHARS:
        blocks.append(Block(kind="text", text=before, page=page))
        before = ""
    prefix = f"{before} {header.group().strip()}".strip()

    rows: list[str] = []
    for row in _ROW_BREAK.split(text[header.end() :]):
        rows.extend([row] if count(row) <= cfg.target_tokens // 2 else _split_oversized(row, count, cfg))
    budget = cfg.target_tokens - count(prefix)
    current: list[str] = []
    used = 0
    for row in rows:
        n = count(row)
        if current and used + n > budget:
            blocks.append(Block(kind="table", text="\n".join([prefix, *current]), page=page))
            current, used = [], 0
        current.append(row)
        used += n
    if current:
        blocks.append(Block(kind="table", text="\n".join([prefix, *current]), page=page))
    return blocks


def normalize_slides(blocks: list[Block], count: TokenCounter, cfg: ChunkingConfig) -> list[Block]:
    """Per slide: the restored title as a heading, then its statement rows or its text."""
    out: list[Block] = []
    for block in blocks:
        text, titles = block.text, []
        for title, pattern in _TITLE_PATTERNS:
            text, found = _remove_spaced_title(pattern, text)
            if found:
                titles.append(title)
        text = _LETTER_SPACED.sub(lambda m: m.group().replace(" ", ""), text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < SLIDE_MIN_CHARS:
            continue
        if titles:
            out.append(Block(kind="heading", text=" - ".join(titles), page=block.page))
        out.extend(_flat_table_blocks(text, block.page, count, cfg) or [Block(kind="text", text=text, page=block.page)])
    return out


def process_release(ref: dict, raw_dir: Path, count_tokens: TokenCounter, cfg: ChunkingConfig, max_tokens: int) -> tuple[list[Chunk], dict]:
    meta = FilingMeta.from_manifest(ref)
    parsed = parse_filing((raw_dir / ref["local_path"]).read_bytes())
    blocks = parsed.blocks
    deck = is_slide_deck(blocks)
    if deck:
        blocks = normalize_slides(blocks, count_tokens, cfg)
    assign_release_sections(blocks)
    chunks = chunk_filing(blocks, meta, {}, count_tokens, cfg)
    return chunks, release_stats(meta, blocks, chunks, deck, max_tokens)


def release_stats(meta: FilingMeta, blocks: list[Block], chunks: list[Chunk], deck: bool, max_tokens: int) -> dict:
    tokens = sorted(c.token_count for c in chunks) or [0]
    figures = sum(len(_FIGURE.findall(c.text)) for c in chunks)
    return {
        "doc_id": meta.doc_id,
        "ticker": meta.ticker,
        "fiscal_year": meta.fiscal_year,
        "fiscal_quarter": meta.fiscal_quarter,
        "slide_deck": deck,
        "tables": sum(b.kind == "table" for b in blocks),
        "chunks": len(chunks),
        "text_chunks": sum(c.chunk_type == "text" for c in chunks),
        "table_chunks": sum(c.chunk_type == "table" for c in chunks),
        "chunks_without_heading": sum(not c.subsection for c in chunks),
        "figures": figures,
        "figures_missing": figures < MIN_FIGURES,
        "tokens_p50": int(statistics.median(tokens)),
        "tokens_p95": tokens[int(0.95 * (len(tokens) - 1))],
        "tokens_max": tokens[-1],
        "chunks_over_limit": sum(t > max_tokens for t in tokens),
    }


def write_report(stats: list[dict], path: Path) -> None:
    path.with_suffix(".json").write_text(json.dumps(stats, indent=2))
    missing = [s["doc_id"] for s in stats if s["figures_missing"]]
    lines = [
        "# Earnings release quality report",
        "",
        f"Releases: {len(stats)} | Chunks: {sum(s['chunks'] for s in stats)} "
        f"| Over token limit: {sum(s['chunks_over_limit'] for s in stats)} "
        f"| Releases without figures in the text: {len(missing)}",
        "",
    ]
    if missing:
        lines += ["Financial tables only as images (not parsed, no OCR): " + ", ".join(missing), ""]
    lines += [
        "| Release | Tables | Chunks (text/table) | No heading | Figures | Tokens p50/p95/max |",
        "|---|---|---|---|---|---|",
    ]
    for s in stats:
        lines.append(
            f"| {s['doc_id']} | {s['tables']} | {s['chunks']} ({s['text_chunks']}/{s['table_chunks']}) "
            f"| {s['chunks_without_heading']} | {s['figures']} | {s['tokens_p50']}/{s['tokens_p95']}/{s['tokens_max']} |"
        )
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--years", type=int, nargs="+")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    manifest = json.loads((settings.raw_sec_dir / "manifest_earnings.json").read_text())
    refs = [
        r
        for r in manifest
        if (not args.tickers or r["ticker"] in {t.upper() for t in args.tickers})
        and (not args.years or r["fiscal_year"] in args.years)
    ]

    count_tokens = get_token_counter(settings.embedding_model)
    cfg = ChunkingConfig()
    out_dir = settings.processed_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    all_stats = []
    with (out_dir / "chunks_earnings.jsonl").open("w", encoding="utf-8") as f:
        for ref in refs:
            chunks, stats = process_release(ref, settings.raw_sec_dir, count_tokens, cfg, settings.embedding_max_tokens)
            for chunk in chunks:
                f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
            all_stats.append(stats)
            logger.info("%s: %d chunks, %d figures", stats["doc_id"], stats["chunks"], stats["figures"])

    write_report(all_stats, out_dir / "earnings_quality_report")
    logger.info("Wrote %d chunks to %s", sum(s["chunks"] for s in all_stats), out_dir / "chunks_earnings.jsonl")


if __name__ == "__main__":
    main()
