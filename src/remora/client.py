"""Shared async HTTP client for vLLM communication."""

from __future__ import annotations

from openai import AsyncOpenAI

from remora.config import ServerConfig


def build_client(server_config: ServerConfig) -> AsyncOpenAI:
    """Return a configured AsyncOpenAI client for the vLLM server."""
    return AsyncOpenAI(
        base_url=server_config.base_url,
        api_key=server_config.api_key,
        timeout=server_config.timeout,
    )
