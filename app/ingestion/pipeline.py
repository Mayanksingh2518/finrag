"""Ingestion pipeline: raw 10-K HTML -> pages + chunks + quality report.

Usage:
    python -m app.ingestion.pipeline
    python -m app.ingestion.pipeline --tickers AAPL JPM --years 2025

Outputs (data/processed/):
    chunks.jsonl          one chunk per line, with full metadata
    pages.jsonl           cleaned text per page (citation verification, page viewer)
    quality_report.json   per-filing parsing statistics
    quality_report.md     the same, human-readable
"""

import argparse
import json
import logging
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from app.config import get_settings
from app.ingestion.chunker import ChunkingConfig, TokenCounter, chunk_filing
from app.ingestion.html_parser import parse_filing
from app.ingestion.models import Chunk, FilingMeta, Page
from app.ingestion.sections import CORE_ITEMS, assign_sections
from app.ingestion.tokens import get_token_counter

logger = logging.getLogger(__name__)


def process_filing(
    ref: dict, raw_dir: Path, count_tokens: TokenCounter, cfg: ChunkingConfig, max_tokens: int
) -> tuple[list[Chunk], list[Page], dict]:
    meta = FilingMeta.from_manifest(ref)
    parsed = parse_filing((raw_dir / ref["local_path"]).read_bytes())
    assign_sections(parsed.blocks)
    chunks = chunk_filing(parsed.blocks, meta, parsed.page_labels, count_tokens, cfg)
    return chunks, parsed.pages, filing_stats(meta, parsed.pages, parsed.blocks, chunks, max_tokens)


def filing_stats(meta: FilingMeta, pages: list[Page], blocks, chunks: list[Chunk], max_tokens: int) -> dict:
    sections = list(dict.fromkeys(c.section for c in chunks))
    tokens = sorted(c.token_count for c in chunks) or [0]
    return {
        "doc_id": meta.doc_id,
        "ticker": meta.ticker,
        "fiscal_year": meta.fiscal_year,
        "pages": len(pages),
        "labeled_pages_pct": round(100 * sum(p.label is not None for p in pages) / max(1, len(pages)), 1),
        "sections": sections,
        "missing_core_items": [i for i in CORE_ITEMS if f"Item {i}" not in sections],
        "tables": sum(b.kind == "table" for b in blocks),
        "chunks": len(chunks),
        "text_chunks": sum(c.chunk_type == "text" for c in chunks),
        "table_chunks": sum(c.chunk_type == "table" for c in chunks),
        "tokens_p50": int(statistics.median(tokens)),
        "tokens_p95": tokens[int(0.95 * (len(tokens) - 1))],
        "tokens_max": tokens[-1],
        "chunks_over_limit": sum(t > max_tokens for t in tokens),
    }


def write_report(stats: list[dict], path: Path) -> None:
    path.with_suffix(".json").write_text(json.dumps(stats, indent=2))
    lines = [
        "# Ingestion quality report",
        "",
        f"Filings: {len(stats)} | Chunks: {sum(s['chunks'] for s in stats)} "
        f"| Over token limit: {sum(s['chunks_over_limit'] for s in stats)} "
        f"| Filings missing a core item: {sum(bool(s['missing_core_items']) for s in stats)}",
        "",
        "| Filing | Pages | Labeled % | Sections | Missing core | Tables | Chunks (text/table) | Tokens p50/p95/max |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in stats:
        lines.append(
            f"| {s['doc_id']} | {s['pages']} | {s['labeled_pages_pct']} | {len(s['sections'])} "
            f"| {', '.join(s['missing_core_items']) or '-'} | {s['tables']} "
            f"| {s['chunks']} ({s['text_chunks']}/{s['table_chunks']}) "
            f"| {s['tokens_p50']}/{s['tokens_p95']}/{s['tokens_max']} |"
        )
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--years", type=int, nargs="+")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    manifest = json.loads((settings.raw_sec_dir / "manifest.json").read_text())
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
    with (out_dir / "chunks.jsonl").open("w", encoding="utf-8") as chunks_f, (
        out_dir / "pages.jsonl"
    ).open("w", encoding="utf-8") as pages_f:
        for ref in refs:
            start = time.perf_counter()
            chunks, pages, stats = process_filing(
                ref, settings.raw_sec_dir, count_tokens, cfg, settings.embedding_max_tokens
            )
            for chunk in chunks:
                chunks_f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
            for page in pages:
                row = {"doc_id": stats["doc_id"], "ticker": ref["ticker"], "fiscal_year": ref["fiscal_year"], **asdict(page)}
                pages_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            all_stats.append(stats)
            logger.info(
                "%s: %d pages, %d chunks, missing core items %s (%.1fs)",
                stats["doc_id"], stats["pages"], stats["chunks"], stats["missing_core_items"] or "none",
                time.perf_counter() - start,
            )

    write_report(all_stats, out_dir / "quality_report")
    logger.info("Wrote %d chunks to %s", sum(s["chunks"] for s in all_stats), out_dir / "chunks.jsonl")


if __name__ == "__main__":
    main()
