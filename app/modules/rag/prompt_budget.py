from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _encoding():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_tokens(text: str) -> int:
    """Return a stable prompt-size estimate without requiring a local model."""
    encoding = _encoding()
    if encoding is not None:
        return len(encoding.encode(text))
    return max(1, len(text))


def truncate_to_tokens(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    encoding = _encoding()
    if encoding is not None:
        tokens = encoding.encode(text)
        if len(tokens) <= budget:
            return text
        return encoding.decode(tokens[:budget]).rstrip()
    return text if len(text) <= budget else text[:budget].rstrip()
