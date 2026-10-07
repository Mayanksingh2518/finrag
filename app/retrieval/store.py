"""In-memory chunk store with vectorised metadata filtering.

Row position is the shared document id across the dense and BM25 indexes,
so a filter is computed once as a boolean mask and reused by both.
"""

import json
from pathlib import Path

import numpy as np

from app.ingestion.models import Chunk
from app.retrieval.types import SearchFilters


class ChunkStore:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._row = {c.chunk_id: i for i, c in enumerate(chunks)}
        self._tickers = np.array([c.ticker for c in chunks])
        self._years = np.array([c.fiscal_year for c in chunks])
        self._sections = np.array([c.section for c in chunks])
        self._types = np.array([c.chunk_type for c in chunks])

    @classmethod
    def from_jsonl(cls, path: Path) -> "ChunkStore":
        with path.open(encoding="utf-8") as f:
            return cls([Chunk(**json.loads(line)) for line in f])

    def __len__(self) -> int:
        return len(self.chunks)

    def row(self, chunk_id: str) -> int:
        return self._row[chunk_id]

    def mask(self, filters: SearchFilters | None) -> np.ndarray | None:
        """Boolean mask of rows matching the filters, or None when unfiltered."""
        if filters is None or filters.is_empty():
            return None
        mask = np.ones(len(self.chunks), dtype=bool)
        for values, column in (
            (filters.tickers and [t.upper() for t in filters.tickers], self._tickers),
            (filters.fiscal_years, self._years),
            (filters.sections, self._sections),
            (filters.chunk_types, self._types),
        ):
            if values:
                mask &= np.isin(column, list(values))
        return mask
