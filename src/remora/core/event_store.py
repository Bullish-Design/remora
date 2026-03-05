"""Event sourcing storage for Remora events."""

from __future__ import annotations

import asyncio
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
            self._conn = await asyncio.to_thread(
                sqlite3.connect,
                str(self._db_path),
                timeout=15.0,
                check_same_thread=False,
                isolation_level=None,
            )
            self._conn.row_factory = sqlite3.Row

            # Enable WAL mode for better concurrent read/write performance
            await asyncio.to_thread(self._conn.execute, "PRAGMA journal_mode=WAL")
            await asyncio.to_thread(self._conn.execute, "PRAGMA synchronous=NORMAL")

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

        # Migrate nodes table: add start_byte/end_byte for existing DBs
        cursor = await asyncio.to_thread(
            self._conn.execute,
            "PRAGMA table_info(nodes)",
        )
        node_columns = {row["name"] for row in cursor.fetchall()}

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
        cursor = await asyncio.to_thread(
            self._conn.execute,
            "PRAGMA table_info(proposals)",
        )
        proposal_columns = {row["name"] for row in cursor.fetchall()}
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
                cursor = self._conn.execute(
                    """
                    INSERT INTO events (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags_json),
                )
                ev_id = cursor.lastrowid or 0

                f_ups: list[RemoraEvent] = []
                if self._projection is not None:
                    f_ups = self._projection.apply(self._conn, event)

                self._conn.execute("COMMIT")
                return ev_id, f_ups
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        async with self._lock:
            for attempt in range(3):
                try:
                    event_id, follow_ups = await asyncio.to_thread(_do_append)
                    break
                except sqlite3.OperationalError as exc:
                    if "database is locked" in str(exc) and attempt < 2:
                        logger.warning(
                            "append: database locked (attempt %d/3), retrying...",
                            attempt + 1,
                        )
                        await asyncio.sleep(0.1 * (attempt + 1))
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
            yield self._row_to_dict(row)

    async def get_recent_events(
        self,
        agent_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get recent events involving an agent (as sender or recipient).

        Returns dicts ordered newest-first (DESC by timestamp).
        """
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        query = """
            SELECT * FROM events
            WHERE from_agent = ? OR to_agent = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
        """
        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                query,
                (agent_id, agent_id, limit),
            )
            rows = await asyncio.to_thread(cursor.fetchall)

        return [self._row_to_dict(row) for row in rows]

    async def get_events_for_correlation(
        self,
        correlation_id: str,
    ) -> list[dict[str, Any]]:
        """Get all events for a correlation chain, ordered chronologically (ASC)."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        query = """
            SELECT * FROM events
            WHERE correlation_id = ?
            ORDER BY timestamp ASC, id ASC
        """
        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                query,
                (correlation_id,),
            )
            rows = await asyncio.to_thread(cursor.fetchall)

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
            return cursor.rowcount

    async def get_node(self, node_id: str) -> "AgentNode | None":
        """Get a single AgentNode by ID from the nodes table."""
        from remora.core.agent_node import AgentNode

        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        def _fetch(conn: sqlite3.Connection) -> sqlite3.Row | None:
            cursor = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
            return cursor.fetchone()

        async with self._lock:
            row = await asyncio.to_thread(_fetch, self._conn)
            
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

        Args:
            file_path: Filter by file path.
            node_type: Filter by node type.
            columns: If provided, only SELECT these columns (optimization to
                     avoid fetching large source_code blobs).  When *columns*
                     is ``None`` (the default), ``SELECT *`` is used and full
                     ``AgentNode`` objects are returned.
        """
        from remora.core.agent_node import AgentNode

        if self._conn is None:
            await self.initialize()
        if self._conn is None:
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
            cursor = conn.execute(query, params)
            return cursor.fetchall()

        async with self._lock:
            rows = await asyncio.to_thread(_fetch, self._conn)
            
        return [AgentNode.from_row(row) for row in rows]

    async def get_node_at_position(
        self,
        file_path: str,
        line: int,
    ) -> "AgentNode | None":
        """Get the narrowest AgentNode containing the given line in a file."""
        from remora.core.agent_node import AgentNode

        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        def _fetch(conn: sqlite3.Connection) -> sqlite3.Row | None:
            cursor = conn.execute(
                """SELECT * FROM nodes
                   WHERE file_path = ? AND start_line <= ? AND end_line >= ?
                   ORDER BY (end_line - start_line) ASC
                   LIMIT 1""",
                (file_path, line, line),
            )
            return cursor.fetchone()

        async with self._lock:
            row = await asyncio.to_thread(_fetch, self._conn)
            
        if row is None:
            return None
        return AgentNode.from_row(row)

    async def set_node_status(self, node_id: str, status: str) -> None:
        """Update the status field of a node directly."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._lock:
            await asyncio.to_thread(
                self._conn.execute,
                "UPDATE nodes SET status = ? WHERE node_id = ?",
                (status, node_id),
            )

    async def remove_nodes_for_file(self, file_path: str) -> int:
        """Remove all nodes for a given file path. Returns count removed."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                "DELETE FROM nodes WHERE file_path = ?",
                (file_path,),
            )
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
