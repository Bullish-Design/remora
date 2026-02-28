"""Manages connected Neovim clients and their subscriptions."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.core.events import RemoraEvent

logger = logging.getLogger(__name__)


@dataclass
class NvimClient:
    """A connected Neovim client with its subscriptions."""

    writer: asyncio.StreamWriter
    subscribed_agents: set[str] = field(default_factory=set)
    client_id: str = ""

    def __post_init__(self):
        if not self.client_id:
            self.client_id = f"nvim_{id(self)}"


class ClientManager:
    """Manages all connected Neovim clients."""

    def __init__(self):
        self._clients: dict[str, NvimClient] = {}
        self._lock = asyncio.Lock()

    async def register(self, writer: asyncio.StreamWriter) -> NvimClient:
        """Register a new Neovim client."""
        client = NvimClient(writer=writer)
        async with self._lock:
            self._clients[client.client_id] = client
        logger.info(f"Client {client.client_id} connected")
        return client

    async def unregister(self, client: NvimClient) -> None:
        """Unregister a disconnected client."""
        async with self._lock:
            self._clients.pop(client.client_id, None)
        logger.info(f"Client {client.client_id} disconnected")

    async def subscribe(self, client: NvimClient, agent_id: str) -> None:
        """Subscribe a client to an agent's events."""
        async with self._lock:
            client.subscribed_agents.clear()
            client.subscribed_agents.add(agent_id)
        logger.debug(f"Client {client.client_id} subscribed to {agent_id}")

    async def notify_event(self, event: RemoraEvent) -> None:
        """Push an event to all clients subscribed to the relevant agent."""
        agent_id = (
            getattr(event, "agent_id", None)
            or getattr(event, "to_agent", None)
            or getattr(event, "from_agent", None)
        )

        if not agent_id:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": "event.push",
            "params": {
                "agent_id": agent_id,
                "event_type": type(event).__name__,
                "timestamp": getattr(event, "timestamp", None),
                "data": self._serialize_event(event),
            },
        }
        msg = json.dumps(notification).encode() + b"\n"

        async with self._lock:
            clients_to_notify = [
                c for c in self._clients.values() if agent_id in c.subscribed_agents
            ]

        for client in clients_to_notify:
            try:
                client.writer.write(msg)
                await client.writer.drain()
            except Exception as e:
                logger.warning(f"Failed to push to {client.client_id}: {e}")

    def _serialize_event(self, event: RemoraEvent) -> dict:
        """Convert event to JSON-serializable dict."""
        from dataclasses import asdict, is_dataclass

        if is_dataclass(event):
            return asdict(event)
        elif hasattr(event, "__dict__"):
            return dict(vars(event))
        else:
            return {"value": str(event)}


# Global instance
client_manager = ClientManager()
