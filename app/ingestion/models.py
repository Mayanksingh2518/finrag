"""Data models shared by the ingestion pipeline."""

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["text", "heading", "table"]


@dataclass
class Block:
    """A contiguous unit of filing content (paragraph, heading or table) on one page."""

    kind: BlockKind
    text: str  # Markdown for tables
    page: int  # 1-based physical page index within the filing
    rows: list[list[str]] | None = None  # cleaned table cells (tables only)
    header_rows: int = 0
    part: str | None = None
    section: str | None = None  # e.g. "Item 7"
    section_title: str | None = None
    subsection: str | None = None  # nearest preceding heading within the section
    # Running headers/footers and page numbers: excluded from chunks and page text,
    # but kept because running headers ("Management's discussion and analysis")
    # are useful section signals.
    furniture: bool = False


@dataclass
class Page:
    index: int  # 1-based physical page index
    label: str | None  # page number as printed in the filing footer, if detected
    text: str


@dataclass
class ParsedFiling:
    blocks: list[Block]
    pages: list[Page]

    @property
    def page_labels(self) -> dict[int, str]:
        return {p.index: p.label for p in self.pages if p.label}


@dataclass(frozen=True)
class FilingMeta:
    ticker: str
    company: str
    fiscal_year: int
    form: str
    filing_date: str
    period_end: str
    source_url: str

    @property
    def doc_id(self) -> str:
        return f"{self.ticker}-FY{self.fiscal_year}-{self.form}"

    @classmethod
    def from_manifest(cls, row: dict) -> "FilingMeta":
        return cls(
            ticker=row["ticker"],
            company=row["company"],
            fiscal_year=row["fiscal_year"],
            form=row["form"],
            filing_date=row["filing_date"],
            period_end=row["report_date"],
            source_url=row["source_url"],
        )


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    ticker: str
    company: str
    fiscal_year: int
    form: str
    filing_date: str
    period_end: str
    part: str | None
    section: str
    section_title: str
    subsection: str | None
    page_start: int
    page_end: int
    page_label_start: str | None
    page_label_end: str | None
    chunk_type: Literal["text", "table"]
    context: str  # contextual header prepended for embedding / prompting
    text: str
    token_count: int  # tokens of context + text, in the embedding model's tokenizer
    source_url: str
    metadata: dict = field(default_factory=dict)

    @property
    def embed_text(self) -> str:
        return f"{self.context}\n\n{self.text}"
