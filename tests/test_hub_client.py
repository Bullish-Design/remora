"""Tests for hub client."""

import asyncio

from remora.context import HubClient, get_hub_client


def test_get_hub_client_returns_client() -> None:
    client = get_hub_client()
    assert isinstance(client, HubClient)


def test_hub_client_returns_empty_context_when_missing_db() -> None:
    client = get_hub_client()
    result = asyncio.run(client.get_context(["node-1"]))
    assert result == {}


def test_hub_client_health_check_false_when_missing_db() -> None:
    client = get_hub_client()
    assert asyncio.run(client.health_check()) is False
