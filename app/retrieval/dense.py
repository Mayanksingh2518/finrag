"""Exact inner-product vector search with FAISS.

17.6k chunks x 384 dims is ~27 MB, and a flat (brute-force) index answers in
milliseconds, so approximate indexes (IVF/HNSW) would only add recall loss.
They become worth it around the millions-of-vectors scale.
"""

import faiss
import numpy as np


class DenseIndex:
    def __init__(self, vectors: np.ndarray):
        self.index = faiss.IndexFlatIP(vectors.shape[1])  # cosine similarity on normalized vectors
        self.index.add(np.ascontiguousarray(vectors, dtype=np.float32))

    def __len__(self) -> int:
        return self.index.ntotal

    def search(self, query: np.ndarray, k: int, mask: np.ndarray | None = None) -> list[tuple[int, float]]:
        """Top-k (row, score); ``mask`` restricts the search to allowed rows (pre-filtering)."""
        params = None
        if mask is not None:
            allowed = np.flatnonzero(mask).astype(np.int64)
            if not len(allowed):
                return []
            k = min(k, len(allowed))
            params = faiss.SearchParameters(sel=faiss.IDSelectorBatch(allowed))
        scores, rows = self.index.search(query.reshape(1, -1).astype(np.float32), k, params=params)
        return [(int(r), float(s)) for r, s in zip(rows[0], scores[0]) if r >= 0]
