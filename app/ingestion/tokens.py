"""Token counting with the embedding model's own tokenizer.

Only the ~700 KB tokenizer.json is downloaded (once, cached by Hugging Face),
not the model weights.
"""

import os
from functools import lru_cache

# Windows without Developer Mode can't create symlinks; HF falls back to copies and warns.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from tokenizers import Tokenizer  # noqa: E402

from app.ingestion.chunker import TokenCounter


@lru_cache
def get_token_counter(model_name: str) -> TokenCounter:
    tokenizer = Tokenizer.from_pretrained(model_name)
    tokenizer.no_truncation()  # bge ships with truncation at 512, which would cap the counts
    tokenizer.no_padding()

    def count(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=False).ids)

    return count
