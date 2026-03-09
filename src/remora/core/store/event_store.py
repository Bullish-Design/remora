"""Event sourcing storage for Remora events."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from structured_agents.events import Event as StructuredEvent

import remora.core.store.event_store_connection as store_connection
import remora.core.store.event_store_queries as store_queries
import remora.core.store.event_store_schema as store_schema
from remora.utils import PathLike, normalize_path

logger = logging.getLogger(__name__)

_NOISY_EVENT_TYPES = frozenset({"NodeDiscoveredEvent", "ScaffoldRequestEvent"})
_T = TypeVar("_T")

if TYPE_CHECKING:
    from remora.core.code.projections import NodeProjection
    from remora.core.events import CoreEvent
    from remora.core.events.event_bus import EventBus
    from remora.core.events.subscriptions import SubscriptionRegistry
    from remora.core.store.node_store import NodeStore


class EventStore:
    """SQLite-backed event store for event sourcing with reactive triggers."""

    def __init__(
        self,
        db_path: PathLike,
        subscriptions: SubscriptionRegistry | None = None,
        event_bus: EventBus | None = None,
        projection: NodeProjection | None = None,
    ):
        self._db_path = normalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._read_conn: sqlite3.Connection | None = None  # Separate connection for reads
        self._lock = asyncio.Lock()
        # Serializes concurrent asyncio.to_thread dispatches against _read_conn.
        # SQLite connections are NOT thread-safe even in WAL mode; concurrent
        # to_thread() calls against the same connection corrupt its internal
        # state and raise sqlite3.InterfaceError. The lock is asyncio-level so
        # it does NOT block write throughput — writers use _lock, readers use
        # _read_lock, and they never contend with each other.
        self._read_lock = asyncio.Lock()
        self._subscriptions = subscriptions
        self._event_bus = event_bus
        self._projection = projection
        self._trigger_queue: asyncio.Queue[tuple[str, int, CoreEvent]] | None = None
        self._node_store: NodeStore | None = None

    @property
    def nodes(self) -> NodeStore:
        """Access the isolated NodeStore for graph nodes."""
        if self._node_store is None:
            raise RuntimeError("EventStore not initialized")
        return self._node_store

    def set_subscriptions(self, subscriptions: SubscriptionRegistry) -> None:
        """Set the subscription registry for trigger matching."""
        self._subscriptions = subscriptions
        if self._trigger_queue is None:
            self._trigger_queue = asyncio.Queue()

    def set_event_bus(self, event_bus: EventBus) -> None:
        """Set the event bus for UI updates."""
        self._event_bus = event_bus

    def rebind_runtime_primitives(self) -> None:
        """Recreate asyncio primitives for the active event loop."""
        self._lock = asyncio.Lock()
        self._read_lock = asyncio.Lock()
        if self._subscriptions is not None:
            self._trigger_queue = asyncio.Queue()
        if self._node_store is not None:
            self._node_store.bind_read_lock(self._read_lock)
            if self._conn is not None:
                self._node_store.bind_write_backend(self._conn, self._lock)

    async def initialize(self) -> None:
        """Initialize the database and create tables."""
        async with self._lock:
            if self._conn is not None:
                return
            # Use a very short timeout (100ms) so we fail fast and can retry quickly.
            # SQLite write contention is expected during background scan, so we
            # want operations to fail/retry quickly rather than blocking.
            self._conn = await asyncio.to_thread(
                sqlite3.connect,
                str(self._db_path),
                timeout=0.1,
                check_same_thread=False,
                isolation_level=None,
            )
            self._conn.row_factory = sqlite3.Row

            # Enable WAL mode for better concurrent read/write performance
            await asyncio.to_thread(self._conn.execute, "PRAGMA journal_mode=WAL")
            await asyncio.to_thread(self._conn.execute, "PRAGMA synchronous=NORMAL")
            # Keep WAL growth bounded even when no explicit checkpoint runs.
            await asyncio.to_thread(self._conn.execute, "PRAGMA wal_autocheckpoint=1000")

            # Create a separate read-only connection for queries.
            # With WAL mode, readers don't block writers and vice versa.
            # All reads are serialized via _read_lock to prevent the
            # sqlite3.InterfaceError that occurs when concurrent to_thread()
            # dispatches share the same connection object.
            self._read_conn = await asyncio.to_thread(
                sqlite3.connect,
                str(self._db_path),
                timeout=2.0,
                check_same_thread=False,
            )
            self._read_conn.row_factory = sqlite3.Row
            # Mark read connection as read-only via query_only pragma
            await asyncio.to_thread(self._read_conn.execute, "PRAGMA query_only=ON")

            await asyncio.to_thread(store_schema.create_tables, self._conn)
            await self._migrate_routing_fields()

            from remora.core.store.node_store import NodeStore
            self._node_store = NodeStore(
                read_conn=self._read_conn,
                read_lock=self._read_lock,
                write_conn=self._conn,
                write_lock=self._lock,
            )

            if self._subscriptions is not None:
                self._trigger_queue = asyncio.Queue()

    def _is_locked_error(self, exc: BaseException) -> bool:
        return store_connection.is_locked_error(exc)

    def _retry_delay_seconds(self, attempt: int) -> float:
        return store_connection.retry_delay_seconds(attempt)

    def _lock_diagnostics(self) -> dict[str, Any]:
        return store_connection.lock_diagnostics(self._db_path, self._conn)

    def _begin_immediate_with_recovery(self, op_name: str) -> None:
        """Start a write transaction, recovering from stale in-transaction state."""
        assert self._conn is not None
        store_connection.begin_immediate_with_recovery(
            self._conn,
            op_name=op_name,
            db_path=self._db_path,
            log=logger,
        )

    async def _run_locked_write_with_retries(self, op_name: str, op: Callable[[], _T]) -> _T:
        """Run write op under the store lock with lock retries and cancel-safe completion."""
        return await store_connection.run_locked_write_with_retries(
            op_name,
            op,
            lock=self._lock,
            db_path=self._db_path,
            conn=self._conn,
            log=logger,
        )

    def _log_event_routing(self, event_type: str, to_agent: str | None, matching_agents: list[str]) -> None:
        """Emit high-volume routing logs at DEBUG while keeping user-facing events at INFO."""
        log_fn = logger.debug if event_type in _NOISY_EVENT_TYPES else logger.info
        log_fn(
            "Event %s to_agent=%s matched %d agents: %s",
            event_type,
            to_agent,
            len(matching_agents),
            matching_agents,
        )

    async def _migrate_routing_fields(self) -> None:
        """Add routing fields to existing tables."""
        assert self._conn is not None, "_migrate_routing_fields called before connection"
        await asyncio.to_thread(store_schema.migrate, self._conn)



    async def append(
        self,
        graph_id: str,
        event: StructuredEvent | CoreEvent,
    ) -> int:
        """Append an event to the store."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        # Prefer the model's event_type field (e.g. "HumanChatEvent") over
        # the Python class name (e.g. "AgentEvent") so panel.lua can
        # match on the canonical event_type string.
        event_type = getattr(event, "event_type", None) or type(event).__name__
        payload = self._serialize_event(event)
        timestamp = getattr(event, "timestamp", time.time())
        created_at = time.time()

        from_agent = getattr(event, "from_agent", None)
        to_agent = getattr(event, "to_agent", None)
        correlation_id = getattr(event, "correlation_id", None)
        agent_id = getattr(event, "agent_id", None)
        tags = getattr(event, "tags", None)
        tags_json = json.dumps(tags) if tags else None

        def _do_append() -> tuple[int, list[CoreEvent]]:
            assert self._conn is not None
            self._begin_immediate_with_recovery("append")
            try:
                with contextlib.closing(self._conn.execute(
                    """
                    INSERT INTO events (graph_id, event_type, payload, timestamp, created_at, agent_id, from_agent, to_agent, correlation_id, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        graph_id,
                        event_type,
                        payload,
                        timestamp,
                        created_at,
                        agent_id,
                        from_agent,
                        to_agent,
                        correlation_id,
                        tags_json,
                    ),
                )) as cursor:
                    ev_id = cursor.lastrowid or 0

                f_ups: list[CoreEvent] = []
                if self._projection is not None:
                    f_ups = self._projection.apply(self._conn, event)

                self._conn.execute("COMMIT")
                return ev_id, f_ups
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        # Retry with jittered exponential backoff.
        # IMPORTANT: lock is held until the in-flight write thread completes,
        # even if caller cancellation arrives (timeout via wait_for).
        event_id, follow_ups = await self._run_locked_write_with_retries("append", _do_append)

        if self._trigger_queue is not None and self._subscriptions is not None:
            matching_agents = await self._subscriptions.get_matching_agents(event)
            self._log_event_routing(event_type, to_agent, matching_agents)
            for agent_id in matching_agents:
                await self._trigger_queue.put((agent_id, event_id, event))

        if self._event_bus is not None:
            await self._event_bus.emit(event)

        # Re-append follow-up events produced by the projection (e.g.
        # ScaffoldRequestEvent when a stub node is discovered).  These are
        # appended as separate events after the original transaction commits.
        for follow_up in follow_ups:
            await self.append(graph_id, follow_up)

        return event_id

    async def batch_append(
        self,
        graph_id: str,
        events: list[StructuredEvent | CoreEvent],
    ) -> list[int]:
        """Append multiple events in a single transaction for better performance.

        Returns a list of event IDs corresponding to the input events.
        """
        if not events:
            return []

        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        prepared: list[
            tuple[
                str,
                str,
                float,
                float,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                StructuredEvent | CoreEvent,
            ]
        ] = []
        for event in events:
            event_type = getattr(event, "event_type", None) or type(event).__name__
            payload = self._serialize_event(event)
            timestamp = getattr(event, "timestamp", time.time())
            created_at = time.time()
            agent_id = getattr(event, "agent_id", None)
            from_agent = getattr(event, "from_agent", None)
            to_agent = getattr(event, "to_agent", None)
            correlation_id = getattr(event, "correlation_id", None)
            tags = getattr(event, "tags", None)
            tags_json = json.dumps(tags) if tags else None
            prepared.append(
                (
                    event_type,
                    payload,
                    timestamp,
                    created_at,
                    agent_id,
                    from_agent,
                    to_agent,
                    correlation_id,
                    tags_json,
                    event,
                )
            )

        def _do_batch_append() -> tuple[list[int], list[CoreEvent]]:
            assert self._conn is not None
            self._begin_immediate_with_recovery("batch_append")
            try:
                event_ids: list[int] = []
                all_follow_ups: list[CoreEvent] = []
                for (
                    event_type,
                    payload,
                    timestamp,
                    created_at,
                    agent_id,
                    from_agent,
                    to_agent,
                    correlation_id,
                    tags_json,
                    event,
                ) in prepared:
                    with contextlib.closing(self._conn.execute(
                        """
                        INSERT INTO events (graph_id, event_type, payload, timestamp, created_at, agent_id, from_agent, to_agent, correlation_id, tags)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            graph_id,
                            event_type,
                            payload,
                            timestamp,
                            created_at,
                            agent_id,
                            from_agent,
                            to_agent,
                            correlation_id,
                            tags_json,
                        ),
                    )) as cursor:
                        event_ids.append(cursor.lastrowid or 0)

                    if self._projection is not None:
                        follow_ups = self._projection.apply(self._conn, event)
                        all_follow_ups.extend(follow_ups)

                self._conn.execute("COMMIT")
                return event_ids, all_follow_ups
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        event_ids, follow_ups = await self._run_locked_write_with_retries("batch_append", _do_batch_append)

        # Process triggers and bus notifications for each event
        for idx, (_, _, _, _, _, _, to_agent, _, _, event) in enumerate(prepared):
            event_type = getattr(event, "event_type", None) or type(event).__name__
            if self._trigger_queue is not None and self._subscriptions is not None:
                matching_agents = await self._subscriptions.get_matching_agents(event)
                self._log_event_routing(event_type, to_agent, matching_agents)
                for agent_id in matching_agents:
                    await self._trigger_queue.put((agent_id, event_ids[idx], event))

            if self._event_bus is not None:
                await self._event_bus.emit(event)

        # Process follow-up events
        for follow_up in follow_ups:
            await self.append(graph_id, follow_up)

        return event_ids

    async def get_triggers(self) -> AsyncIterator[tuple[str, int, CoreEvent]]:
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
        if self._read_conn is None:
            await self.initialize()
        if self._read_conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._read_lock:
            rows = await asyncio.to_thread(
                store_queries.fetch_replay_rows,
                self._read_conn,
                graph_id=graph_id,
                event_types=event_types,
                since=since,
                until=until,
                after_id=after_id,
            )

        for row in rows:
            yield self._row_to_dict(row)

    async def get_agent_timeline(
        self,
        agent_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get events involving an agent as subject, sender, or recipient.

        Uses the dedicated read connection to avoid blocking on write operations.
        Returns dicts ordered newest-first (DESC by timestamp).
        """
        if self._read_conn is None:
            await self.initialize()
        if self._read_conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._read_lock:
            rows = await asyncio.to_thread(
                store_queries.fetch_agent_timeline_rows,
                self._read_conn,
                agent_id=agent_id,
                limit=limit,
            )

        return [self._row_to_dict(row) for row in rows]

    async def get_routed_messages(
        self,
        agent_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get routed messages where an agent is sender or recipient."""
        if self._read_conn is None:
            await self.initialize()
        if self._read_conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._read_lock:
            rows = await asyncio.to_thread(
                store_queries.fetch_routed_message_rows,
                self._read_conn,
                agent_id=agent_id,
                limit=limit,
            )

        return [self._row_to_dict(row) for row in rows]

    async def get_events_for_correlation(
        self,
        correlation_id: str,
    ) -> list[dict[str, Any]]:
        """Get all events for a correlation chain, ordered chronologically (ASC).

        Uses the dedicated read connection to avoid blocking on write operations.
        """
        if self._read_conn is None:
            await self.initialize()
        if self._read_conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._read_lock:
            rows = await asyncio.to_thread(
                store_queries.fetch_correlation_rows,
                self._read_conn,
                correlation_id=correlation_id,
            )

        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite Row to a standard event dict.

        The payload column stores the full ``model_dump()`` of the event, so
        all model fields (``message``, ``content``, ``tool_name``, …) live at
        the top level of that blob.  To reconstruct an event dict that
        panel.lua can render we:

        1. Use the stored model ``event_type`` (e.g. ``"HumanChatEvent"``)
           instead of the DB column which may contain the Python class name.

        2. Promote model-specific fields into a ``payload`` sub-dict so that
           ``ev.payload.message``, ``ev.payload.content``, etc. work in Lua.
        """
        return store_queries.row_to_event_dict(row)

    async def get_graph_ids(
        self,
        *,
        limit: int = 100,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent graph execution IDs with metadata."""
        if self._read_conn is None:
            await self.initialize()
        if self._read_conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._read_lock:
            rows = await asyncio.to_thread(
                store_queries.fetch_graph_id_rows,
                self._read_conn,
                limit=limit,
                since=since,
            )

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
        if self._read_conn is None:
            await self.initialize()
        if self._read_conn is None:
            raise RuntimeError("EventStore not initialized")
        async with self._read_lock:
            return await asyncio.to_thread(
                store_queries.fetch_event_count,
                self._read_conn,
                graph_id=graph_id,
            )

    async def delete_graph(self, graph_id: str) -> int:
        """Delete all events for a graph."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")
        async with self._lock:
            return await asyncio.to_thread(
                store_queries.delete_graph_events,
                self._conn,
                graph_id=graph_id,
            )

    async def checkpoint_wal(self, mode: str = "PASSIVE") -> tuple[int, int, int]:
        """Run a WAL checkpoint and return (busy, log_frames, checkpointed_frames)."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        mode_upper = mode.upper()
        if mode_upper not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
            raise ValueError(f"Unsupported checkpoint mode: {mode}")

        async with self._lock:
            result = await asyncio.to_thread(
                store_queries.checkpoint_wal,
                self._conn,
                mode_upper=mode_upper,
            )

        logger.info(
            "checkpoint_wal: mode=%s busy=%d log_frames=%d checkpointed_frames=%d",
            mode_upper,
            result[0],
            result[1],
            result[2],
        )
        return result

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            async with self._lock:
                try:
                    with contextlib.closing(self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")) as cursor:
                        cursor.fetchone()
                except Exception:
                    logger.debug("close: wal checkpoint failed", exc_info=True)
                await asyncio.to_thread(self._conn.close)
                self._conn = None
        if self._read_conn:
            await asyncio.to_thread(self._read_conn.close)
            self._read_conn = None
        self._node_store = None
        self._trigger_queue = None

    def _close_sync(self) -> None:
        """Best-effort synchronous cleanup used by the finalizer path."""
        conn = self._conn
        read_conn = self._read_conn
        self._conn = None
        self._read_conn = None
        self._node_store = None
        self._trigger_queue = None

        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
        if read_conn is not None:
            with contextlib.suppress(Exception):
                read_conn.close()

    def __del__(self) -> None:
        # Finalizer safeguard for tests that forget to await close().
        self._close_sync()

    def _serialize_event(self, event: StructuredEvent | CoreEvent) -> str:
        """Serialize an event to JSON."""
        if hasattr(event, "model_dump"):
            # Pydantic model (e.g. LSP AgentEvent subclasses)
            data = event.model_dump()
        elif is_dataclass(event):
            data = asdict(event)
        elif hasattr(event, "__dict__"):
            data = dict(vars(event))
        else:
            data = {"value": str(event)}

        return json.dumps(data, default=str)


__all__ = ["EventStore"]
