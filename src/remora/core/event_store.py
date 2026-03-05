"""Event sourcing storage for Remora events."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
import time
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator

from structured_agents.events import Event as StructuredEvent

from remora.core.events import RemoraEvent
from remora.utils import PathLike, normalize_path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from remora.core.agent_node import AgentNode
    from remora.core.event_bus import EventBus
    from remora.core.projections import NodeProjection
    from remora.core.subscriptions import SubscriptionRegistry


class EventStore:
    """SQLite-backed event store for event sourcing with reactive triggers."""

    def __init__(
        self,
        db_path: PathLike,
        subscriptions: "SubscriptionRegistry | None" = None,
        event_bus: "EventBus | None" = None,
        projection: "NodeProjection | None" = None,
    ):
        self._db_path = normalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._read_conn: sqlite3.Connection | None = None  # Separate connection for reads (no lock needed)
        self._lock = asyncio.Lock()
        self._subscriptions = subscriptions
        self._event_bus = event_bus
        self._projection = projection
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

            # Create a separate read-only connection for queries.
            # With WAL mode, readers don't block writers and vice versa,
            # so this connection can be used without acquiring _lock.
            self._read_conn = await asyncio.to_thread(
                sqlite3.connect,
                str(self._db_path),
                timeout=2.0,
                check_same_thread=False,
            )
            self._read_conn.row_factory = sqlite3.Row
            # Mark read connection as read-only via query_only pragma
            await asyncio.to_thread(self._read_conn.execute, "PRAGMA query_only=ON")

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

            await asyncio.to_thread(
                self._conn.executescript,
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id         TEXT PRIMARY KEY,
                    node_type       TEXT NOT NULL,
                    name            TEXT NOT NULL,
                    full_name       TEXT NOT NULL,
                    file_path       TEXT NOT NULL,
                    start_line      INTEGER NOT NULL,
                    end_line        INTEGER NOT NULL,
                    start_byte      INTEGER NOT NULL DEFAULT 0,
                    end_byte        INTEGER NOT NULL DEFAULT 0,
                    source_code     TEXT NOT NULL,
                    source_hash     TEXT NOT NULL,
                    parent_id       TEXT,
                    caller_ids      TEXT NOT NULL DEFAULT '[]',
                    callee_ids      TEXT NOT NULL DEFAULT '[]',
                    status          TEXT NOT NULL DEFAULT 'idle',
                    last_trigger_event TEXT NOT NULL DEFAULT '',
                    last_completed_at  REAL,
                    extension_name  TEXT,
                    custom_system_prompt TEXT NOT NULL DEFAULT '',
                    mounted_workspaces TEXT NOT NULL DEFAULT '[]',
                    extra_tools     TEXT NOT NULL DEFAULT '[]',
                    extra_subscriptions TEXT NOT NULL DEFAULT '[]'
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);
                CREATE INDEX IF NOT EXISTS idx_nodes_parent_id ON nodes(parent_id);
                CREATE INDEX IF NOT EXISTS idx_nodes_node_type ON nodes(node_type);
                """,
            )

            # Subscriptions table (shared with SubscriptionRegistry)
            await asyncio.to_thread(
                self._conn.executescript,
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    pattern_json TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_subscriptions_agent_id
                ON subscriptions(agent_id);

                CREATE INDEX IF NOT EXISTS idx_subscriptions_is_default
                ON subscriptions(is_default);
                """,
            )

            # RemoraDB operational tables (shared with RemoraDB)
            await asyncio.to_thread(
                self._conn.executescript,
                """
                CREATE TABLE IF NOT EXISTS edges (
                    from_id TEXT NOT NULL,
                    to_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    PRIMARY KEY (from_id, to_id, edge_type)
                );

                CREATE TABLE IF NOT EXISTS activation_chain (
                    correlation_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    PRIMARY KEY (correlation_id, agent_id)
                );

                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    old_source TEXT NOT NULL,
                    new_source TEXT NOT NULL,
                    diff TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    file_path TEXT
                );

                CREATE TABLE IF NOT EXISTS cursor_focus (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    agent_id TEXT,
                    file_path TEXT,
                    line INTEGER,
                    timestamp REAL
                );

                CREATE TABLE IF NOT EXISTS command_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_type TEXT NOT NULL,
                    agent_id TEXT,
                    payload JSON NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    processed_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_chain_correlation
                ON activation_chain(correlation_id);
                """,
            )

            await self._migrate_routing_fields()

            if self._subscriptions is not None:
                self._trigger_queue = asyncio.Queue()

    async def _migrate_routing_fields(self) -> None:
        """Add routing fields to existing tables."""
        assert self._conn is not None, "_migrate_routing_fields called before connection"
        
        def _get_columns(table: str) -> set[str]:
            assert self._conn is not None
            with contextlib.closing(self._conn.execute(f"PRAGMA table_info({table})")) as cursor:
                return {row["name"] for row in cursor.fetchall()}

        columns = await asyncio.to_thread(_get_columns, "events")

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

        # Migrate nodes table: add start_byte/end_byte for existing DBs
        node_columns = await asyncio.to_thread(_get_columns, "nodes")

        if "start_byte" not in node_columns:
            await asyncio.to_thread(
                self._conn.execute,
                "ALTER TABLE nodes ADD COLUMN start_byte INTEGER NOT NULL DEFAULT 0",
            )
        if "end_byte" not in node_columns:
            await asyncio.to_thread(
                self._conn.execute,
                "ALTER TABLE nodes ADD COLUMN end_byte INTEGER NOT NULL DEFAULT 0",
            )

        # Migrate proposals table: add file_path for existing DBs
        proposal_columns = await asyncio.to_thread(_get_columns, "proposals")
        if "file_path" not in proposal_columns:
            await asyncio.to_thread(
                self._conn.execute,
                "ALTER TABLE proposals ADD COLUMN file_path TEXT",
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

        # Prefer the model's event_type field (e.g. "HumanChatEvent") over
        # the Python class name (e.g. "LspHumanChatEvent") so panel.lua can
        # match on the canonical event_type string.
        event_type = getattr(event, "event_type", None) or type(event).__name__
        payload = self._serialize_event(event)
        timestamp = getattr(event, "timestamp", time.time())
        created_at = time.time()

        from_agent = getattr(event, "from_agent", None)
        to_agent = getattr(event, "to_agent", None)
        correlation_id = getattr(event, "correlation_id", None)
        tags = getattr(event, "tags", None)
        tags_json = json.dumps(tags) if tags else None

        def _do_append() -> tuple[int, list[RemoraEvent]]:
            assert self._conn is not None
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                with contextlib.closing(self._conn.execute(
                    """
                    INSERT INTO events (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags_json),
                )) as cursor:
                    ev_id = cursor.lastrowid or 0

                f_ups: list[RemoraEvent] = []
                if self._projection is not None:
                    f_ups = self._projection.apply(self._conn, event)

                self._conn.execute("COMMIT")
                return ev_id, f_ups
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        # Retry with fast exponential backoff. With a 100ms connection timeout and
        # 10 attempts, worst-case wait is about 2.5s total, and most operations
        # succeed quickly since the background scan now yields between files.
        # IMPORTANT: Lock is released before sleeping to allow other queries to proceed.
        max_attempts = 10
        for attempt in range(max_attempts):
            try:
                async with self._lock:
                    event_id, follow_ups = await asyncio.to_thread(_do_append)
                break
            except sqlite3.OperationalError as exc:
                if "database is locked" in str(exc) and attempt < max_attempts - 1:
                    # Fast exponential backoff: 50ms, 100ms, 200ms, 400ms, ...
                    delay = 0.05 * (2 ** attempt)
                    logger.warning(
                        "append: database locked (attempt %d/%d), retrying in %.2fs...",
                        attempt + 1,
                        max_attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        if self._trigger_queue is not None and self._subscriptions is not None:
            matching_agents = await self._subscriptions.get_matching_agents(event)
            logger.info(
                "Event %s to_agent=%s matched %d agents: %s",
                event_type,
                to_agent,
                len(matching_agents),
                matching_agents,
            )
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
        events: list[StructuredEvent | RemoraEvent],
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

        # Pre-process all events
        prepared: list[tuple[str, str, float, float, str | None, str | None, str | None, str | None, StructuredEvent | RemoraEvent]] = []
        for event in events:
            event_type = getattr(event, "event_type", None) or type(event).__name__
            payload = self._serialize_event(event)
            timestamp = getattr(event, "timestamp", time.time())
            created_at = time.time()
            from_agent = getattr(event, "from_agent", None)
            to_agent = getattr(event, "to_agent", None)
            correlation_id = getattr(event, "correlation_id", None)
            tags = getattr(event, "tags", None)
            tags_json = json.dumps(tags) if tags else None
            prepared.append((event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags_json, event))

        def _do_batch_append() -> tuple[list[int], list[RemoraEvent]]:
            assert self._conn is not None
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                event_ids: list[int] = []
                all_follow_ups: list[RemoraEvent] = []
                for event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags_json, event in prepared:
                    with contextlib.closing(self._conn.execute(
                        """
                        INSERT INTO events (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags_json),
                    )) as cursor:
                        event_ids.append(cursor.lastrowid or 0)

                    if self._projection is not None:
                        f_ups = self._projection.apply(self._conn, event)
                        all_follow_ups.extend(f_ups)

                self._conn.execute("COMMIT")
                return event_ids, all_follow_ups
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        # IMPORTANT: Lock is released before sleeping to allow other queries to proceed.
        max_attempts = 10
        for attempt in range(max_attempts):
            try:
                async with self._lock:
                    event_ids, follow_ups = await asyncio.to_thread(_do_batch_append)
                break
            except sqlite3.OperationalError as exc:
                if "database is locked" in str(exc) and attempt < max_attempts - 1:
                    # Fast exponential backoff: 50ms, 100ms, 200ms, 400ms, ...
                    delay = 0.05 * (2 ** attempt)
                    logger.warning(
                        "batch_append: database locked (attempt %d/%d), retrying in %.2fs...",
                        attempt + 1,
                        max_attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        # Process triggers and bus notifications for each event
        for idx, (_, _, _, _, _, to_agent, _, _, event) in enumerate(prepared):
            event_type = getattr(event, "event_type", None) or type(event).__name__
            if self._trigger_queue is not None and self._subscriptions is not None:
                matching_agents = await self._subscriptions.get_matching_agents(event)
                logger.info(
                    "Event %s to_agent=%s matched %d agents: %s",
                    event_type,
                    to_agent,
                    len(matching_agents),
                    matching_agents,
                )
                for agent_id in matching_agents:
                    await self._trigger_queue.put((agent_id, event_ids[idx], event))

            if self._event_bus is not None:
                await self._event_bus.emit(event)

        # Process follow-up events
        for follow_up in follow_ups:
            await self.append(graph_id, follow_up)

        return event_ids

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

        def _fetch() -> list[sqlite3.Row]:
            assert self._conn is not None
            with contextlib.closing(self._conn.execute(query, params)) as cursor:
                return cursor.fetchall()

        async with self._lock:
            rows = await asyncio.to_thread(_fetch)

        for row in rows:
            yield self._row_to_dict(row)

    async def get_recent_events(
        self,
        agent_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get recent events involving an agent (as sender or recipient).

        Uses the dedicated read connection to avoid blocking on write operations.
        Returns dicts ordered newest-first (DESC by timestamp).
        """
        if self._read_conn is None:
            await self.initialize()
        if self._read_conn is None:
            raise RuntimeError("EventStore not initialized")

        query = """
            SELECT * FROM events
            WHERE from_agent = ? OR to_agent = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
        """
        def _fetch() -> list[sqlite3.Row]:
            assert self._read_conn is not None
            with contextlib.closing(self._read_conn.execute(query, (agent_id, agent_id, limit))) as cursor:
                return cursor.fetchall()

        # No lock needed for reads with WAL mode
        rows = await asyncio.to_thread(_fetch)

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

        query = """
            SELECT * FROM events
            WHERE correlation_id = ?
            ORDER BY timestamp ASC, id ASC
        """
        def _fetch() -> list[sqlite3.Row]:
            assert self._read_conn is not None
            with contextlib.closing(self._read_conn.execute(query, (correlation_id,))) as cursor:
                return cursor.fetchall()

        # No lock needed for reads with WAL mode
        rows = await asyncio.to_thread(_fetch)

        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite Row to a standard event dict.

        The payload column stores the full ``model_dump()`` of the event, so
        all model fields (``message``, ``content``, ``tool_name``, …) live at
        the top level of that blob.  To reconstruct an event dict that
        panel.lua can render we:

        1. Use the stored model ``event_type`` (e.g. ``"HumanChatEvent"``)
           instead of the DB column which may contain the Python class name
           (e.g. ``"LspHumanChatEvent"``).

        2. Promote model-specific fields into a ``payload`` sub-dict so that
           ``ev.payload.message``, ``ev.payload.content``, etc. work in Lua.
        """
        tags = row["tags"]
        if tags:
            tags = json.loads(tags)

        stored = json.loads(row["payload"])  # full model_dump()

        # Prefer the event_type from the serialised model (handles both old
        # events stored with the Python class name and new ones).
        event_type = stored.get("event_type") or row["event_type"]

        # Top-level metadata keys that should NOT go into the payload sub-dict
        _META_KEYS = {
            "event_id",
            "event_type",
            "timestamp",
            "correlation_id",
            "agent_id",
            "summary",
            "payload",
            "from_agent",
            "to_agent",
            "tags",
            "graph_id",
            "created_at",
            "id",
        }

        # Build the nested payload from model-specific fields (message,
        # content, tool_name, diff, proposal_id, feedback, target_id, …).
        # If the stored model already had a non-empty ``payload`` dict (e.g.
        # AgentTextResponse sets payload={"content": ...}), merge those too.
        nested_payload: dict[str, Any] = {}
        original_payload = stored.get("payload")
        if isinstance(original_payload, dict) and original_payload:
            nested_payload.update(original_payload)

        for key, value in stored.items():
            if key not in _META_KEYS and value not in (None, "", {}, []):
                nested_payload[key] = value

        return {
            "id": row["id"],
            "graph_id": row["graph_id"],
            "event_type": event_type,
            "payload": nested_payload,
            "summary": stored.get("summary", ""),
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

        def _fetch() -> list[sqlite3.Row]:
            assert self._conn is not None
            with contextlib.closing(self._conn.execute(query, params)) as cursor:
                return cursor.fetchall()

        async with self._lock:
            rows = await asyncio.to_thread(_fetch)

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

        def _fetch() -> sqlite3.Row | None:
            assert self._conn is not None
            with contextlib.closing(self._conn.execute("SELECT COUNT(*) FROM events WHERE graph_id = ?", (graph_id,))) as cursor:
                return cursor.fetchone()

        async with self._lock:
            row = await asyncio.to_thread(_fetch)

        return row[0] if row else 0

    async def delete_graph(self, graph_id: str) -> int:
        """Delete all events for a graph."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        def _delete() -> int:
            assert self._conn is not None
            with contextlib.closing(self._conn.execute("DELETE FROM events WHERE graph_id = ?", (graph_id,))) as cursor:
                return cursor.rowcount

        async with self._lock:
            return await asyncio.to_thread(_delete)

    async def get_node(self, node_id: str) -> "AgentNode | None":
        """Get a single AgentNode by ID from the nodes table.

        Uses the dedicated read connection to avoid blocking on write operations.
        """
        from remora.core.agent_node import AgentNode

        if self._read_conn is None:
            await self.initialize()
        if self._read_conn is None:
            raise RuntimeError("EventStore not initialized")

        def _fetch(conn: sqlite3.Connection) -> sqlite3.Row | None:
            with contextlib.closing(conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))) as cursor:
                return cursor.fetchone()

        # No lock needed for reads with WAL mode
        row = await asyncio.to_thread(_fetch, self._read_conn)

        if row is None:
            return None
        return AgentNode.from_row(row)

    async def list_nodes(
        self,
        *,
        file_path: str | None = None,
        node_type: str | None = None,
        columns: list[str] | None = None,
    ) -> "list[AgentNode]":
        """List AgentNodes with optional filters.

        Uses the dedicated read connection to avoid blocking on write operations.

        Args:
            file_path: Filter by file path.
            node_type: Filter by node type.
            columns: If provided, only SELECT these columns (optimization to
                     avoid fetching large source_code blobs).  When *columns*
                     is ``None`` (the default), ``SELECT *`` is used and full
                     ``AgentNode`` objects are returned.
        """
        from remora.core.agent_node import AgentNode

        if self._read_conn is None:
            await self.initialize()
        if self._read_conn is None:
            raise RuntimeError("EventStore not initialized")

        col_clause = ", ".join(columns) if columns else "*"
        query = f"SELECT {col_clause} FROM nodes"
        params: list[str] = []
        conditions: list[str] = []

        if file_path:
            conditions.append("file_path = ?")
            params.append(file_path)
        if node_type:
            conditions.append("node_type = ?")
            params.append(node_type)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY file_path, start_line"

        def _fetch(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            with contextlib.closing(conn.execute(query, params)) as cursor:
                return cursor.fetchall()

        # No lock needed for reads with WAL mode
        rows = await asyncio.to_thread(_fetch, self._read_conn)

        return [AgentNode.from_row(row) for row in rows]

    async def get_node_at_position(
        self,
        file_path: str,
        line: int,
    ) -> "AgentNode | None":
        """Get the narrowest AgentNode containing the given line in a file.

        Uses the dedicated read connection to avoid blocking on write operations.
        With WAL mode, this read doesn't need the lock since readers and writers
        don't block each other.
        """
        from remora.core.agent_node import AgentNode

        if self._read_conn is None:
            await self.initialize()
        if self._read_conn is None:
            raise RuntimeError("EventStore not initialized")

        def _fetch(conn: sqlite3.Connection) -> sqlite3.Row | None:
            with contextlib.closing(conn.execute(
                """SELECT * FROM nodes
                   WHERE file_path = ? AND start_line <= ? AND end_line >= ?
                   ORDER BY (end_line - start_line) ASC
                   LIMIT 1""",
                (file_path, line, line),
            )) as cursor:
                return cursor.fetchone()

        # No lock needed for reads with WAL mode
        row = await asyncio.to_thread(_fetch, self._read_conn)

        if row is None:
            return None
        return AgentNode.from_row(row)

    async def set_node_status(self, node_id: str, status: str) -> None:
        """Update the status field of a node directly."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        def _update() -> None:
            assert self._conn is not None
            with contextlib.closing(self._conn.execute("UPDATE nodes SET status = ? WHERE node_id = ?", (status, node_id))):
                pass
                
        async with self._lock:
            await asyncio.to_thread(_update)

    async def remove_nodes_for_file(self, file_path: str) -> int:
        """Remove all nodes for a given file path. Returns count removed."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        def _delete() -> int:
            assert self._conn is not None
            with contextlib.closing(self._conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))) as cursor:
                return cursor.rowcount

        async with self._lock:
            return await asyncio.to_thread(_delete)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            async with self._lock:
                await asyncio.to_thread(self._conn.close)
                self._conn = None
        self._trigger_queue = None

    def _serialize_event(self, event: StructuredEvent | RemoraEvent) -> str:
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
