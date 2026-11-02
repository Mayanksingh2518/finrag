"""BM25 keyword search tuned for financial filings.

Dense embeddings blur exact terms; BM25 catches them. The tokenizer keeps the
tokens that matter in 10-Ks: "10-k", "7a", "416,161", "3.5", segment names.
Words are stemmed (revenues -> revenu) but numbers are left untouched.
"""

import re
from collections.abc import Sequence

import bm25s
import numpy as np
import Stemmer

_TOKEN = re.compile(r"[a-z0-9]+(?:[.,'\-][a-z0-9]+)*")
STOPWORDS = frozenset(
    """a an and are as at be been but by for from had has have how in into is it its of on or
    our than that the their there these this those to was were what when where which while who
    why will with within would we you your company company's""".split()
)

_stemmer = Stemmer.Stemmer("english")


def tokenize(text: str) -> list[str]:
    tokens = []
    for tok in _TOKEN.findall(text.lower().replace("’", "'")):
        if tok in STOPWORDS:
            continue
        tokens.append(_stemmer.stemWord(tok) if tok.isalpha() else tok)
    return tokens


class BM25Index:
    def __init__(self, texts: list[str], k1: float = 1.2, b: float = 0.75):
        self.retriever = bm25s.BM25(k1=k1, b=b)
        self.retriever.index([tokenize(t) for t in texts], show_progress=False)
        self.size = len(texts)

    def __len__(self) -> int:
        return self.size

    def search(self, query: str, k: int, mask: np.ndarray | None = None) -> list[tuple[int, float]]:
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = np.asarray(self.retriever.get_scores(tokens), dtype=np.float32)
        if mask is not None:
            scores = np.where(mask, scores, -np.inf)
        k = min(k, int(np.isfinite(scores).sum()))
        if k <= 0:
            return []
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(int(r), float(scores[r])) for r in top if scores[r] > 0]


class PartitionedBM25:
    """One index per document type, same `search` contract over the shared row ids.

    IDF and average length are corpus statistics: one index would let number-heavy earnings releases
    change every 10-K score. Separate indexes keep 10-K rankings, and the cached answers built on them,
    exactly as they were.
    """

    def __init__(self, texts: Sequence[str], partitions: Sequence[str]):
        names = np.array(partitions)
        self.parts = [(rows := np.flatnonzero(names == name), BM25Index([texts[r] for r in rows]))
                      for name in dict.fromkeys(partitions)]
        self.size = len(texts)

    def __len__(self) -> int:
        return self.size

    def search(self, query: str, k: int, mask: np.ndarray | None = None) -> list[tuple[int, float]]:
        hits: list[tuple[int, float]] = []
        for rows, index in self.parts:
            part_mask = None if mask is None else mask[rows]
            if part_mask is None or part_mask.any():
                hits += [(int(rows[r]), score) for r, score in index.search(query, k, part_mask)]
        return sorted(hits, key=lambda h: -h[1])[:k]
