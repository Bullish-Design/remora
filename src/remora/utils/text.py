"""Text manipulation utilities."""

from __future__ import annotations


def truncate(text: str, max_len: int = 200, suffix: str = "...") -> str:
    """Truncate text to a maximum length with suffix."""
    if len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix


def summarize(text: str, max_len: int = 200) -> str:
    """Alias for truncate with default settings."""
    return truncate(text, max_len=max_len)


__all__ = ["summarize", "truncate"]
