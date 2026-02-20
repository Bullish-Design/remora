"""Tests for hub client stub."""

import asyncio

from remora.context import HubClientStub, get_hub_client


def test_get_hub_client_returns_stub() -> None:
    client = get_hub_client()
    assert isinstance(client, HubClientStub)


def test_hub_client_stub_returns_empty_context() -> None:
    client = get_hub_client()
    result = asyncio.run(client.get_context(["node-1"]))
    assert result == {}


def test_hub_client_stub_health_check() -> None:
    client = get_hub_client()
    assert asyncio.run(client.health_check()) is False
