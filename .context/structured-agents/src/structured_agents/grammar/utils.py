from __future__ import annotations


def escape_ebnf_string(value: str) -> str:
    """Escape special characters for EBNF string literals.

    Args:
        value: Raw string value.

    Returns:
        Escaped string safe for use in EBNF.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def validate_ebnf(grammar: str) -> list[str]:
    """Validate EBNF grammar syntax.

    Args:
        grammar: EBNF grammar string.

    Returns:
        List of error messages (empty if valid).
    """
    try:
        from xgrammar.testing import _get_matcher_from_grammar

        _get_matcher_from_grammar(grammar)
        return []
    except Exception as exc:  # pragma: no cover - depends on xgrammar
        return [str(exc)]
