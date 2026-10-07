"""Pick the torch device for local models (embedder, reranker)."""


def resolve_device(preference: str = "auto") -> str:
    """"auto" -> Apple GPU (mps) on Apple Silicon, CUDA if present, else CPU."""
    if preference != "auto":
        return preference
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
