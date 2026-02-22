from __future__ import annotations


def require_xgrammar_and_vllm() -> None:
    """Fail fast if required grammar dependencies are missing."""
    try:
        import vllm  # noqa: F401
        import xgrammar  # noqa: F401
    except ImportError as exc:
        message = (
            "Missing required dependencies: vllm and xgrammar. "
            "Install them to use structured-agents v2."
        )
        raise RuntimeError(message) from exc
