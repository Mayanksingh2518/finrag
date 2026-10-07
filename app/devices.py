"""Pick the torch device for local models (embedder, reranker)."""

import sys


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


def check_torch_faiss_compatible(device: str, platform: str = sys.platform) -> None:
    """Fail fast instead of hanging: torch on macOS CPU cannot share a process with FAISS.

    The macOS faiss-cpu and torch wheels each bundle their own libomp. With both loaded,
    multithreaded torch CPU inference segfaults or deadlocks (verified with faiss-cpu 1.15
    and torch 2.14 on an M4). On mps the models run on the GPU and the two coexist.
    """
    if platform == "darwin" and device == "cpu":
        raise RuntimeError(
            "DEVICE=cpu is not supported on macOS together with FAISS (duplicate OpenMP "
            "runtimes crash or deadlock). Use DEVICE=auto (mps) on macOS."
        )
