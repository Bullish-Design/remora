"""Hub client stub for Pull Hook integration.

This module provides a stub implementation of the Hub client.
In Phase 2, this will be replaced with actual Hub communication.
"""

from __future__ import annotations

from typing import Any


class HubClientStub:
    """Stub Hub client that does nothing.

    This allows the ContextManager to call pull_hub_context()
    without errors, even when the Hub is not available.
    """

    async def get_context(self, node_ids: list[str]) -> dict[str, Any]:
        """Return empty context (Hub not implemented yet)."""
        _ = node_ids
        return {}

    async def health_check(self) -> bool:
        """Return False (Hub not running)."""
        return False


_hub_client_stub = HubClientStub()


def get_hub_client() -> HubClientStub:
    """Get the Hub client instance.

    In Phase 2, this will attempt to connect to the actual Hub.
    For now, returns the stub.
    """
    return _hub_client_stub
