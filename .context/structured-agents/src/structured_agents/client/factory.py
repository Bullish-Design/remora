"""Client factory helpers."""

from __future__ import annotations

from structured_agents.client.openai_compat import OpenAICompatibleClient
from structured_agents.types import KernelConfig


def build_client(config: KernelConfig) -> OpenAICompatibleClient:
    """Build an OpenAI-compatible client from kernel config."""
    return OpenAICompatibleClient(config)
