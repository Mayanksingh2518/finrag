"""Turn retrieval hits into numbered prompt sources within a token budget.

Each source gets an id (S1, S2, ...) the model cites, and a human citation
([AAPL FY2025 p.23]) the UI shows. Hits are taken in ranked order (decomposed
retrieval already interleaves companies/years); a chunk that doesn't fit the
budget is skipped whole rather than truncated, so tables stay intact.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.ingestion.models import Chunk
from app.retrieval.types import ScoredChunk


@dataclass(frozen=True)
class Source:
    id: str  # "S1"
    chunk: Chunk
    score: float

    @property
    def page(self) -> str:
        c = self.chunk
        if not c.page_label_start:
            return f"#{c.page_start}"
        if c.page_label_end and c.page_label_end != c.page_label_start:
            return f"{c.page_label_start}-{c.page_label_end}"
        return c.page_label_start

    @property
    def citation(self) -> str:
        return f"[{self.chunk.ticker} FY{self.chunk.fiscal_year} p.{self.page}]"

    def render(self) -> str:
        c = self.chunk
        header = (f"[{self.id}] {c.company} ({c.ticker}) Form 10-K, fiscal year {c.fiscal_year}, "
                  f"{c.section}: {c.section_title}, page {self.page}")
        if c.subsection:
            header += f" | {c.subsection}"
        return f"{header}\n{c.text}"


def build_sources(hits: Sequence[ScoredChunk], token_budget: int, max_sources: int = 12) -> list[Source]:
    sources: list[Source] = []
    used = 0
    seen: set[str] = set()
    for hit in hits:
        c = hit.chunk
        if c.chunk_id in seen:
            continue
        cost = c.token_count + 30  # + header
        if used + cost > token_budget:
            continue  # skip whole; a smaller later chunk may still fit
        seen.add(c.chunk_id)
        sources.append(Source(f"S{len(sources) + 1}", c, hit.score))
        used += cost
        if len(sources) >= max_sources:
            break
    return sources


def render_sources(sources: Sequence[Source]) -> str:
    return "\n\n".join(s.render() for s in sources)
