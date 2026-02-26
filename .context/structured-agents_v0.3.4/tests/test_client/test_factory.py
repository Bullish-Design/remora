"""Tests for client factory helpers."""

from structured_agents.client import OpenAICompatibleClient, build_client


def test_build_client_returns_openai_client() -> None:
    config = {"base_url": "http://localhost:8000/v1", "model": "test"}
    client = build_client(config)
    assert isinstance(client, OpenAICompatibleClient)
