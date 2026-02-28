"""Neovim JSON-RPC server for Remora.

This module provides a minimal JSON-RPC server that allows Neovim
to interact with the Remora reactive swarm.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import remora.core.events as events_module
from remora.core.event_store import EventStore
from remora.core.events import AgentMessageEvent
from remora.core.subscriptions import SubscriptionPattern, SubscriptionRegistry
from remora.utils import PathLike, normalize_path, to_project_relative

if TYPE_CHECKING:
    from remora.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class NvimServer:
    """JSON-RPC server for Neovim integration."""

    def __init__(
        self,
        socket_path: PathLike,
        event_store: EventStore,
        subscriptions: SubscriptionRegistry,
        event_bus: "EventBus | None" = None,
        project_root: PathLike | None = None,
    ):
        self._socket_path = normalize_path(socket_path)
        self._event_store = event_store
        self._subscriptions = subscriptions
        self._event_bus = event_bus
        self._project_root = normalize_path(project_root or Path.cwd())
        self._clients: set[asyncio.StreamWriter] = set()
        self._server: asyncio.Server | None = None
        self._handlers = {
            "swarm.emit": self._handle_swarm_emit,
            "agent.select": self._handle_agent_select,
            "agent.chat": self._handle_agent_chat,
            "agent.subscribe": self._handle_agent_subscribe,
            "agent.get_subscriptions": self._handle_agent_get_subscriptions,
        }

    async def start(self) -> None:
        """Start the JSON-RPC server."""
        if self._socket_path.exists():
            self._socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self._socket_path),
        )
        logger.info(f"NvimServer started on {self._socket_path}")

        if self._event_bus is not None:
            self._event_bus.subscribe_all(self._broadcast_event)

    async def stop(self) -> None:
        """Stop the server."""
        if self._event_bus is not None:
            self._event_bus.unsubscribe(self._broadcast_event)

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        for client in list(self._clients):
            client.close()
            await client.wait_closed()

        if self._socket_path.exists():
            self._socket_path.unlink()

        logger.info("NvimServer stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        self._clients.add(writer)
        addr = writer.get_extra_info("peername")
        logger.debug(f"Client connected: {addr}")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    message = json.loads(line.decode())
                    response = await self._process_message(message)
                    if response:
                        writer.write((json.dumps(response) + "\n").encode())
                        await writer.drain()
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON received")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")

        except asyncio.CancelledError:
            pass
        finally:
            self._clients.discard(writer)
            writer.close()
            await writer.wait_closed()
            logger.debug(f"Client disconnected: {addr}")

    async def _process_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Process a JSON-RPC message."""
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params", {})

        if not method:
            return None

        handler = self._handlers.get(method)
        if not handler:
            return self._error_response(msg_id, -32601, f"Method not found: {method}")

        try:
            result = await handler(params)
            if msg_id is not None:
                return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as e:
            return self._error_response(msg_id, -32000, str(e))

        return None

    def _error_response(self, msg_id: Any, code: int, message: str) -> dict[str, Any]:
        """Create an error response."""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    async def _handle_swarm_emit(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle swarm.emit method."""
        event_type = params.get("event_type")
        event_data = dict(params.get("data") or {})

        if "path" in event_data and event_data["path"]:
            event_data["path"] = str(to_project_relative(self._project_root, event_data["path"]))

        try:
            event_class = getattr(events_module, str(event_type))
        except AttributeError as exc:
            raise ValueError(f"Unknown event type: {event_type}") from exc

        try:
            event = event_class(**event_data)
        except TypeError as exc:
            raise ValueError(f"Invalid arguments for {event_type}: {exc}") from exc

        await self._event_store.append("nvim", event)
        return {"status": "ok"}

    async def _handle_agent_select(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle agent.select method."""
        agent_id = params.get("agent_id")
        if not agent_id:
            raise ValueError("agent_id is required")

        subscriptions = await self._subscriptions.get_subscriptions(agent_id)
        return {
            "agent_id": agent_id,
            "subscriptions": [
                {
                    "id": sub.id,
                    "pattern": {
                        "event_types": sub.pattern.event_types,
                        "from_agents": sub.pattern.from_agents,
                        "to_agent": sub.pattern.to_agent,
                        "path_glob": sub.pattern.path_glob,
                        "tags": sub.pattern.tags,
                    },
                    "is_default": sub.is_default,
                }
                for sub in subscriptions
            ],
        }

    async def _handle_agent_chat(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle agent.chat method."""
        agent_id = params.get("agent_id")
        message = params.get("message", "")

        if not agent_id:
            raise ValueError("agent_id is required")

        event = AgentMessageEvent(
            from_agent="nvim",
            to_agent=agent_id,
            content=message,
        )

        await self._event_store.append(f"chat-{agent_id}", event)
        return {"status": "ok", "event_id": "generated"}

    async def _handle_agent_subscribe(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle agent.subscribe method."""
        agent_id = params.get("agent_id")
        pattern_data = params.get("pattern", {})

        if not agent_id:
            raise ValueError("agent_id is required")

        pattern = SubscriptionPattern(
            event_types=pattern_data.get("event_types"),
            from_agents=pattern_data.get("from_agents"),
            to_agent=pattern_data.get("to_agent"),
            path_glob=pattern_data.get("path_glob"),
            tags=pattern_data.get("tags"),
        )

        subscription = await self._subscriptions.register(agent_id, pattern)
        return {"subscription_id": subscription.id}

    async def _handle_agent_get_subscriptions(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle agent.get_subscriptions method."""
        agent_id = params.get("agent_id")
        if not agent_id:
            raise ValueError("agent_id is required")

        subscriptions = await self._subscriptions.get_subscriptions(agent_id)
        return {"subscriptions": [{"id": sub.id, "pattern": asdict(sub.pattern)} for sub in subscriptions]}

    async def _broadcast_event(self, event: Any) -> None:
        """Broadcast an event to all connected clients."""
        event_type = type(event).__name__
        payload = {
            "event_type": event_type,
            "data": {k: v for k, v in vars(event).items() if not k.startswith("_")},
        }

        message = json.dumps({"method": "event.subscribed", "params": payload}) + "\n"

        for client in list(self._clients):
            try:
                client.write(message.encode())
                await client.drain()
            except Exception:
                pass


def asdict(obj: Any) -> Any:
    """Simple asdict for dataclasses."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: asdict(v) for k, v in vars(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [asdict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: asdict(v) for k, v in obj.items()}
    return obj


__all__ = ["NvimServer"]
