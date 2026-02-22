from __future__ import annotations

from remora import client
from remora.config import ServerConfig


def test_build_client_uses_server_config(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(client, "AsyncOpenAI", FakeAsyncOpenAI)

    config = ServerConfig(
        base_url="http://example.test/v1",
        api_key="token",
        timeout=15,
        default_adapter="adapter",
    )

    created = client.build_client(config)

    assert isinstance(created, FakeAsyncOpenAI)
    assert captured == {
        "base_url": "http://example.test/v1",
        "api_key": "token",
        "timeout": 15,
    }
