"""Section-aware chunking with contextual headers.

Rules:
- Chunks never cross a 10-K Item boundary, so section filters are exact.
- Headings start a new chunk (when the current one has real content).
- Tables are their own chunks; oversized tables split by rows with the
  column header repeated, so every piece is readable on its own.
- Size is measured in the embedding model's tokenizer. bge-small reads at
  most 512 tokens; anything beyond is silently truncated, so the contextual
  header + body must stay under that.
- Overlap (a few trailing sentences) is carried only when a chunk was split
  for size, not across headings or tables.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import groupby

from app.ingestion.models import Block, Chunk, FilingMeta
from app.ingestion.tables import to_markdown

TokenCounter = Callable[[str], int]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9(\"“$•])")


@dataclass(frozen=True)
class ChunkingConfig:
    target_tokens: int = 320
    max_tokens: int = 420  # body budget; leaves room for the ~30-80 token context header
    overlap_tokens: int = 50
    min_tokens_before_heading_break: int = 80
    min_chunk_tokens: int = 40
    max_subsection_chars: int = 150


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text) if s]


def _split_oversized(text: str, count: TokenCounter, cfg: ChunkingConfig) -> list[str]:
    """Split a paragraph into pieces of at most ~target tokens on sentence (then word) boundaries."""
    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in split_sentences(text):
        n = count(sentence)
        if n > cfg.max_tokens:  # pathological run-on sentence: fall back to word windows
            words = sentence.split()
            step = max(1, len(words) * cfg.target_tokens // n)
            parts = [" ".join(words[i : i + step]) for i in range(0, len(words), step)]
        else:
            parts = [sentence]
        for part in parts:
            n = count(part)
            if current and current_tokens + n > cfg.target_tokens:
                pieces.append(" ".join(current))
                current, current_tokens = [], 0
            current.append(part)
            current_tokens += n
    if current:
        pieces.append(" ".join(current))
    return pieces


class _FilingChunker:
    def __init__(
        self,
        meta: FilingMeta,
        page_labels: dict[int, str],
        count: TokenCounter,
        cfg: ChunkingConfig,
    ):
        self.meta = meta
        self.page_labels = page_labels
        self.count = count
        self.cfg = cfg
        self.chunks: list[Chunk] = []

    def context_header(self, block: Block) -> str:
        header = (
            f"{self.meta.company} ({self.meta.ticker}) Form {self.meta.form}, "
            f"fiscal year {self.meta.fiscal_year} | {block.section}: {block.section_title}"
        )
        if block.subsection:
            header += f" | {block.subsection[: self.cfg.max_subsection_chars]}"
        return header

    def emit(self, kind: str, text: str, pages: list[int], anchor: Block) -> None:
        context = self.context_header(anchor)
        start, end = min(pages), max(pages)
        self.chunks.append(
            Chunk(
                chunk_id=f"{self.meta.doc_id}-{len(self.chunks):04d}",
                doc_id=self.meta.doc_id,
                ticker=self.meta.ticker,
                company=self.meta.company,
                fiscal_year=self.meta.fiscal_year,
                form=self.meta.form,
                filing_date=self.meta.filing_date,
                period_end=self.meta.period_end,
                part=anchor.part,
                section=anchor.section or "",
                section_title=anchor.section_title or "",
                subsection=anchor.subsection,
                page_start=start,
                page_end=end,
                page_label_start=self.page_labels.get(start),
                page_label_end=self.page_labels.get(end),
                chunk_type=kind,  # type: ignore[arg-type]
                context=context,
                text=text,
                token_count=self.count(f"{context}\n\n{text}"),
                source_url=self.meta.source_url,
            )
        )

    def chunk_section(self, blocks: list[Block]) -> None:
        buf: list[tuple[str, int]] = []  # (text, page)
        buf_tokens = 0
        overlap_only = False  # buf holds nothing but text carried from the previous chunk
        anchor = blocks[0]
        caption: str | None = None

        def flush(carry_overlap: bool) -> None:
            nonlocal buf, buf_tokens, overlap_only
            if buf and not overlap_only:
                self.emit("text", "\n".join(t for t, _ in buf), [p for _, p in buf], anchor)
            tail = buf[-1] if buf and not overlap_only else None
            buf, buf_tokens, overlap_only = [], 0, False
            if carry_overlap and tail and (overlap := self._overlap(tail[0])):
                buf, buf_tokens, overlap_only = [(overlap, tail[1])], self.count(overlap), True

        for block in blocks:
            if block.kind == "table":
                if buf and not overlap_only and buf_tokens < self.cfg.min_chunk_tokens:
                    # A lone heading/intro line before a table becomes the table's caption.
                    caption = " ".join(t for t, _ in buf)
                    buf, buf_tokens = [], 0
                flush(carry_overlap=False)
                self.emit_table(block, caption)
                anchor = block
                continue

            if block.kind == "heading" and buf_tokens >= self.cfg.min_tokens_before_heading_break:
                flush(carry_overlap=False)
            if not buf or overlap_only:
                anchor = block

            n = self.count(block.text)
            units = [block.text] if n <= self.cfg.max_tokens else _split_oversized(block.text, self.count, self.cfg)
            for unit in units:
                n = self.count(unit) if len(units) > 1 else n
                if buf and not overlap_only and buf_tokens + n > self.cfg.target_tokens:
                    flush(carry_overlap=True)
                    anchor = block
                if overlap_only and buf_tokens + n > self.cfg.max_tokens:
                    buf, buf_tokens = [], 0  # no room for overlap in front of a large unit
                buf.append((unit, block.page))
                buf_tokens += n
                overlap_only = False
            caption = block.text if len(block.text) <= 300 else block.subsection
        flush(carry_overlap=False)

    def _overlap(self, text: str) -> str:
        picked: list[str] = []
        tokens = 0
        for sentence in reversed(split_sentences(text)):
            n = self.count(sentence)
            if tokens + n > self.cfg.overlap_tokens:
                break
            picked.insert(0, sentence)
            tokens += n
        return " ".join(picked)

    def emit_table(self, block: Block, caption: str | None) -> None:
        prefix = f"{caption}\n\n" if caption else ""
        if not block.rows or self.count(prefix + block.text) <= self.cfg.max_tokens:
            self.emit("table", prefix + block.text, [block.page], block)
            return

        header, body = block.rows[: block.header_rows], block.rows[block.header_rows :]
        cont_prefix = f"{caption} (continued)\n\n" if caption else "(continued)\n\n"
        base = self.count(cont_prefix + to_markdown(header, block.header_rows))
        groups: list[list[list[str]]] = [[]]
        group_tokens = base
        for row in body:
            n = self.count(" | ".join(row)) + len(row) + 2
            if groups[-1] and group_tokens + n > self.cfg.max_tokens:
                groups.append([])
                group_tokens = base
            groups[-1].append(row)
            group_tokens += n
        for i, rows in enumerate(groups):
            text = (prefix if i == 0 else cont_prefix) + to_markdown(header + rows, block.header_rows)
            if self.count(text) <= self.cfg.max_tokens:
                self.emit("table", text, [block.page], block)
                continue
            # A single row too large for the embedder: keep the content as plain text pieces.
            for piece in _split_oversized(" ".join(" ".join(c for c in r if c) for r in rows), self.count, self.cfg):
                self.emit("table", piece, [block.page], block)


def _section_groups(blocks: list[Block]) -> Iterator[list[Block]]:
    for _, group in groupby(blocks, key=lambda b: b.section):
        yield list(group)


def chunk_filing(
    blocks: list[Block],
    meta: FilingMeta,
    page_labels: dict[int, str],
    count_tokens: TokenCounter,
    cfg: ChunkingConfig = ChunkingConfig(),
) -> list[Chunk]:
    chunker = _FilingChunker(meta, page_labels, count_tokens, cfg)
    for group in _section_groups([b for b in blocks if not b.furniture]):
        chunker.chunk_section(group)
    return chunker.chunks
