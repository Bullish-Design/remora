"""Shared async HTTP client for vLLM communication."""

from __future__ import annotations

from openai import AsyncOpenAI

from remora.config import ModelConfig


def build_client(model_config: ModelConfig, *, timeout: float | None = None) -> AsyncOpenAI:
    """Return a configured AsyncOpenAI client for the model server."""
    kwargs = {
        "base_url": model_config.base_url,
        "api_key": model_config.api_key,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return AsyncOpenAI(**kwargs)
