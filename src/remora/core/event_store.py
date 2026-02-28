"""Event sourcing storage for Remora events."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator

from structured_agents.events import Event as StructuredEvent

from remora.core.events import RemoraEvent
from remora.utils import PathLike, normalize_path

if TYPE_CHECKING:
    from remora.core.event_bus import EventBus
    from remora.core.subscriptions import SubscriptionRegistry


class EventStore:
    """SQLite-backed event store for event sourcing with reactive triggers."""

    def __init__(
        self,
        db_path: PathLike,
        subscriptions: "SubscriptionRegistry | None" = None,
        event_bus: "EventBus | None" = None,
    ):
        self._db_path = normalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._subscriptions = subscriptions
        self._event_bus = event_bus
        self._trigger_queue: asyncio.Queue[tuple[str, int, RemoraEvent]] | None = None

    def set_subscriptions(self, subscriptions: "SubscriptionRegistry") -> None:
        """Set the subscription registry for trigger matching."""
        self._subscriptions = subscriptions
        if self._trigger_queue is None:
            self._trigger_queue = asyncio.Queue()

    def set_event_bus(self, event_bus: "EventBus") -> None:
        """Set the event bus for UI updates."""
        self._event_bus = event_bus

    async def initialize(self) -> None:
        """Initialize the database and create tables."""
        async with self._lock:
            if self._conn is not None:
                return
            self._conn = await asyncio.to_thread(
                sqlite3.connect,
                str(self._db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row

            await asyncio.to_thread(
                self._conn.executescript,
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    graph_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    from_agent TEXT,
                    to_agent TEXT,
                    correlation_id TEXT,
                    tags TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_events_graph_id
                ON events(graph_id);

                CREATE INDEX IF NOT EXISTS idx_events_type
                ON events(event_type);

                CREATE INDEX IF NOT EXISTS idx_events_timestamp
                ON events(timestamp);

                CREATE INDEX IF NOT EXISTS idx_events_to_agent
                ON events(to_agent);
                """,
            )

            await self._migrate_routing_fields()

            if self._subscriptions is not None:
                self._trigger_queue = asyncio.Queue()

    async def _migrate_routing_fields(self) -> None:
        """Add routing fields to existing tables."""
        cursor = await asyncio.to_thread(
            self._conn.execute,
            "PRAGMA table_info(events)",
        )
        columns = {row["name"] for row in cursor.fetchall()}

        if "from_agent" not in columns:
            await asyncio.to_thread(
                self._conn.execute,
                "ALTER TABLE events ADD COLUMN from_agent TEXT",
            )
        if "to_agent" not in columns:
            await asyncio.to_thread(
                self._conn.execute,
                "ALTER TABLE events ADD COLUMN to_agent TEXT",
            )
        if "correlation_id" not in columns:
            await asyncio.to_thread(
                self._conn.execute,
                "ALTER TABLE events ADD COLUMN correlation_id TEXT",
            )
        if "tags" not in columns:
            await asyncio.to_thread(
                self._conn.execute,
                "ALTER TABLE events ADD COLUMN tags TEXT",
            )

    async def append(
        self,
        graph_id: str,
        event: StructuredEvent | RemoraEvent,
    ) -> int:
        """Append an event to the store."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        event_type = type(event).__name__
        payload = self._serialize_event(event)
        timestamp = getattr(event, "timestamp", time.time())
        created_at = time.time()

        from_agent = getattr(event, "from_agent", None)
        to_agent = getattr(event, "to_agent", None)
        correlation_id = getattr(event, "correlation_id", None)
        tags = getattr(event, "tags", None)
        tags_json = json.dumps(tags) if tags else None

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                """
                INSERT INTO events (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags_json),
            )
            await asyncio.to_thread(self._conn.commit)
            event_id = cursor.lastrowid or 0

        if self._trigger_queue is not None and self._subscriptions is not None:
            matching_agents = await self._subscriptions.get_matching_agents(event)
            for agent_id in matching_agents:
                await self._trigger_queue.put((agent_id, event_id, event))

        if self._event_bus is not None:
            await self._event_bus.emit(event)

        return event_id

    async def get_triggers(self) -> AsyncIterator[tuple[str, int, RemoraEvent]]:
        """Iterate over event triggers for matched subscriptions."""
        if self._trigger_queue is None:
            raise RuntimeError("EventStore subscriptions not configured")

        while True:
            try:
                trigger = await self._trigger_queue.get()
                yield trigger
            except asyncio.CancelledError:
                break

    async def replay(
        self,
        graph_id: str,
        *,
        event_types: list[str] | None = None,
        since: float | None = None,
        until: float | None = None,
        after_id: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Replay events for a graph."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        query = "SELECT * FROM events WHERE graph_id = ?"
        params: list[Any] = [graph_id]

        if event_types:
            placeholders = ",".join("?" * len(event_types))
            query += f" AND event_type IN ({placeholders})"
            params.extend(event_types)

        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)

        if until is not None:
            query += " AND timestamp <= ?"
            params.append(until)

        if after_id is not None:
            query += " AND id > ?"
            params.append(after_id)

        query += " ORDER BY timestamp ASC, id ASC"

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                query,
                params,
            )
            rows = await asyncio.to_thread(cursor.fetchall)

        for row in rows:
            tags = row["tags"]
            if tags:
                tags = json.loads(tags)
            yield {
                "id": row["id"],
                "graph_id": row["graph_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload"]),
                "timestamp": row["timestamp"],
                "created_at": row["created_at"],
                "from_agent": row["from_agent"],
                "to_agent": row["to_agent"],
                "correlation_id": row["correlation_id"],
                "tags": tags,
            }

    async def get_graph_ids(
        self,
        *,
        limit: int = 100,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent graph execution IDs with metadata."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        query = """
            SELECT
                graph_id,
                MIN(timestamp) as started_at,
                MAX(timestamp) as ended_at,
                COUNT(*) as event_count
            FROM events
        """
        params: list[Any] = []

        if since is not None:
            query += " WHERE timestamp >= ?"
            params.append(since)

        query += " GROUP BY graph_id ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                query,
                params,
            )
            rows = await asyncio.to_thread(cursor.fetchall)

        return [
            {
                "graph_id": row["graph_id"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "event_count": row["event_count"],
            }
            for row in rows
        ]

    async def get_event_count(self, graph_id: str) -> int:
        """Get the number of events for a graph."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                "SELECT COUNT(*) FROM events WHERE graph_id = ?",
                (graph_id,),
            )
            row = await asyncio.to_thread(cursor.fetchone)

        return row[0] if row else 0

    async def delete_graph(self, graph_id: str) -> int:
        """Delete all events for a graph."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                "DELETE FROM events WHERE graph_id = ?",
                (graph_id,),
            )
            await asyncio.to_thread(self._conn.commit)
            return cursor.rowcount

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            async with self._lock:
                await asyncio.to_thread(self._conn.close)
                self._conn = None
        self._trigger_queue = None

    def _serialize_event(self, event: StructuredEvent | RemoraEvent) -> str:
        """Serialize an event to JSON."""
        if is_dataclass(event):
            data = asdict(event)
        elif hasattr(event, "__dict__"):
            data = dict(vars(event))
        else:
            data = {"value": str(event)}

        return json.dumps(data, default=str)


class EventSourcedBus:
    """An EventBus wrapper that persists events to an EventStore."""

    def __init__(
        self,
        event_bus: "EventBus",
        event_store: EventStore,
        graph_id: str,
    ):
        from remora.core.event_bus import EventBus

        self._bus = event_bus
        self._store = event_store
        self._graph_id = graph_id

    async def emit(self, event: StructuredEvent | RemoraEvent) -> None:
        """Emit and persist an event."""
        await self._store.append(self._graph_id, event)
        await self._bus.emit(event)

    async def replay_to_bus(
        self,
        *,
        event_types: list[str] | None = None,
    ) -> int:
        """Replay stored events through the bus."""
        count = 0
        async for event_record in self._store.replay(
            self._graph_id,
            event_types=event_types,
        ):
            await self._bus.emit(event_record)  # type: ignore[arg-type]
            count += 1
        return count

    def __getattr__(self, name: str) -> Any:
        return getattr(self._bus, name)


__all__ = ["EventSourcedBus", "EventStore"]
