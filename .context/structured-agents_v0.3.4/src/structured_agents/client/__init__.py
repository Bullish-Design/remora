"""Client package for LLM connections."""

from structured_agents.client.protocol import CompletionResponse, LLMClient
from structured_agents.client.openai import OpenAICompatibleClient, build_client

__all__ = ["CompletionResponse", "LLMClient", "OpenAICompatibleClient", "build_client"]
