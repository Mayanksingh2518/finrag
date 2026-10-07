"""Cross-encoder reranking.

Bi-encoders embed query and chunk separately; a cross-encoder reads them
together, which is far more precise but too slow for the whole corpus. So it
only re-scores the few dozen candidates that hybrid retrieval returns.
"""

from typing import Protocol


class Reranker(Protocol):
    model_name: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str, max_length: int = 512, batch_size: int = 16):
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self.model = CrossEncoder(model_name, max_length=max_length, device="cpu")
        self.batch_size = batch_size

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        scores = self.model.predict(
            [(query, p) for p in passages], batch_size=self.batch_size, show_progress_bar=False
        )
        return [float(s) for s in scores]
