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

from remora.core import event_store_connection as store_connection
from remora.core import event_store_queries as store_queries
from remora.core import event_store_schema as store_schema
from remora.core.events import CoreEvent
from remora.utils import PathLike, normalize_path

logger = logging.getLogger(__name__)

_NOISY_EVENT_TYPES = frozenset({"NodeDiscoveredEvent", "ScaffoldRequestEvent"})
_BATCH_APPEND_SLOW_PHASE_WARNING_MS = 1000.0
_T = TypeVar("_T")

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

    def set_subscriptions(self, subscriptions: SubscriptionRegistry) -> None:
        """Set the subscription registry for trigger matching."""
        self._subscriptions = subscriptions
        if self._trigger_queue is None:
            self._trigger_queue = asyncio.Queue()

    def set_event_bus(self, event_bus: EventBus) -> None:
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

            if self._subscriptions is not None:
                self._trigger_queue = asyncio.Queue()

    def _is_locked_error(self, exc: BaseException) -> bool:
        message = str(exc).lower()
        return "database is locked" in message or "database table is locked" in message

    def _retry_delay_seconds(self, attempt: int) -> float:
        # Jitter avoids synchronized retries across multiple writers.
        base = min(_LOCK_RETRY_CAP_SECONDS, _LOCK_RETRY_BASE_SECONDS * (2 ** attempt))
        return min(_LOCK_RETRY_CAP_SECONDS, base * random.uniform(0.6, 1.4))

    def _lock_diagnostics(self) -> dict[str, Any]:
        holders: list[int] = []
        try:
            proc = subprocess.run(
                ["lsof", "-t", str(self._db_path)],
                capture_output=True,
                text=True,
                timeout=0.5,
                check=False,
            )
            if proc.stdout:
                seen: set[int] = set()
                for line in proc.stdout.splitlines():
                    value = line.strip()
                    if not value:
                        continue
                    try:
                        pid = int(value)
                    except ValueError:
                        continue
                    if pid in seen:
                        continue
                    seen.add(pid)
                    holders.append(pid)
        except (FileNotFoundError, subprocess.SubprocessError):
            holders = []

        return {
            "pid": os.getpid(),
            "thread": threading.get_ident(),
            "db_path": str(self._db_path),
            "in_transaction": bool(self._conn and self._conn.in_transaction),
            "holder_pids": holders,
        }

    def _begin_immediate_with_recovery(self, op_name: str) -> None:
        """Start a write transaction, recovering from stale in-transaction state."""
        assert self._conn is not None
        if self._conn.in_transaction:
            logger.error(
                "%s: write connection already in_transaction before BEGIN IMMEDIATE; forcing rollback; diagnostics=%s",
                op_name,
                self._lock_diagnostics(),
            )
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                logger.warning(
                    "%s: rollback during stale transaction recovery failed; continuing",
                    op_name,
                    exc_info=True,
                )
        self._conn.execute("BEGIN IMMEDIATE")

    async def _run_locked_write_with_retries(self, op_name: str, op: Callable[[], _T]) -> _T:
        """Run write op under the store lock with lock retries and cancel-safe completion."""
        max_attempts = _LOCK_RETRY_MAX_ATTEMPTS
        for attempt in range(max_attempts):
            try:
                async with self._lock:
                    write_task = asyncio.create_task(asyncio.to_thread(op))
                    try:
                        return await asyncio.shield(write_task)
                    except asyncio.CancelledError:
                        logger.warning(
                            "%s: cancelled while write thread is in-flight; waiting for completion before releasing lock",
                            op_name,
                        )
                        try:
                            await write_task
                        except Exception:
                            logger.warning(
                                "%s: in-flight write failed after cancellation",
                                op_name,
                                exc_info=True,
                            )
                        raise
            except sqlite3.OperationalError as exc:
                if self._is_locked_error(exc) and attempt < max_attempts - 1:
                    delay = self._retry_delay_seconds(attempt)
                    if attempt in (0, max_attempts - 2):
                        logger.warning(
                            "%s: database locked (attempt %d/%d), retrying in %.2fs; diagnostics=%s",
                            op_name,
                            attempt + 1,
                            max_attempts,
                            delay,
                            self._lock_diagnostics(),
                        )
                    else:
                        logger.warning(
                            "%s: database locked (attempt %d/%d), retrying in %.2fs...",
                            op_name,
                            attempt + 1,
                            max_attempts,
                            delay,
                        )
                    await asyncio.sleep(delay)
                else:
                    raise

        raise RuntimeError(f"{op_name}: unreachable retry exhaustion")

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

        def _do_append() -> tuple[int, list[CoreEvent]]:
            assert self._conn is not None
            self._begin_immediate_with_recovery("append")
            try:
                with contextlib.closing(self._conn.execute(
                    """
                    INSERT INTO events (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags_json),
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

        # Pre-process all events
        prepare_start = time.monotonic()
        prepared: list[tuple[str, str, float, float, str | None, str | None, str | None, str | None, StructuredEvent | CoreEvent]] = []
        for event in events:
            event_type = getattr(event, "event_type", None) or type(event).__name__
            serialize_start = time.monotonic()
            payload = self._serialize_event(event)
            serialize_ms = (time.monotonic() - serialize_start) * 1000
            timestamp = getattr(event, "timestamp", time.time())
            created_at = time.time()
            from_agent = getattr(event, "from_agent", None)
            to_agent = getattr(event, "to_agent", None)
            correlation_id = getattr(event, "correlation_id", None)
            tags = getattr(event, "tags", None)
            tags_json = json.dumps(tags) if tags else None
            prepared.append((event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags_json, event))
            if serialize_ms > _BATCH_APPEND_SLOW_PHASE_WARNING_MS:
                logger.warning(
                    "batch_append: serialize SLOW event_type=%s node_id=%s file_path=%s payload_bytes=%d source_len=%s duration_ms=%.1f",
                    event_type,
                    str(getattr(event, "node_id", "")),
                    str(getattr(event, "file_path", "")),
                    len(payload),
                    self._source_length(event),
                    serialize_ms,
                )
            elif logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "batch_append: prepared event_type=%s node_id=%s file_path=%s payload_bytes=%d source_len=%s serialize_ms=%.1f",
                    event_type,
                    str(getattr(event, "node_id", "")),
                    str(getattr(event, "file_path", "")),
                    len(payload),
                    self._source_length(event),
                    serialize_ms,
                )
        prepare_ms = (time.monotonic() - prepare_start) * 1000
        if prepare_ms > _BATCH_APPEND_SLOW_PHASE_WARNING_MS:
            logger.warning("batch_append: prepare SLOW duration_ms=%.1f events=%d", prepare_ms, len(prepared))
        elif logger.isEnabledFor(logging.DEBUG):
            logger.debug("batch_append: prepare duration_ms=%.1f events=%d", prepare_ms, len(prepared))

        def _do_batch_append() -> tuple[list[int], list[CoreEvent]]:
            assert self._conn is not None
            tx_start = time.monotonic()
            begin_start = time.monotonic()
            self._begin_immediate_with_recovery("batch_append")
            begin_ms = (time.monotonic() - begin_start) * 1000
            if begin_ms > _BATCH_APPEND_SLOW_PHASE_WARNING_MS:
                logger.warning(
                    "batch_append: BEGIN IMMEDIATE SLOW duration_ms=%.1f events=%d diagnostics=%s",
                    begin_ms,
                    len(prepared),
                    self._lock_diagnostics(),
                )
            else:
                logger.debug("batch_append: BEGIN IMMEDIATE duration_ms=%.1f events=%d", begin_ms, len(prepared))

            current_idx = 0
            current_event_type = ""
            current_file_path = ""
            current_node_id = ""
            try:
                event_ids: list[int] = []
                all_follow_ups: list[CoreEvent] = []
                total_insert_ms = 0.0
                total_projection_ms = 0.0
                for idx, (
                    event_type,
                    payload,
                    timestamp,
                    created_at,
                    from_agent,
                    to_agent,
                    correlation_id,
                    tags_json,
                    event,
                ) in enumerate(prepared, start=1):
                    current_idx = idx
                    current_event_type = event_type
                    current_file_path = str(getattr(event, "file_path", ""))
                    current_node_id = str(getattr(event, "node_id", ""))
                    source_len = self._source_length(event)
                    payload_bytes = len(payload)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "batch_append: event start idx=%d/%d event_type=%s node_id=%s file_path=%s payload_bytes=%d source_len=%s",
                            idx,
                            len(prepared),
                            event_type,
                            current_node_id,
                            current_file_path,
                            payload_bytes,
                            source_len,
                        )
                    event_start = time.monotonic()
                    insert_start = time.monotonic()
                    with contextlib.closing(self._conn.execute(
                        """
                        INSERT INTO events (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags_json),
                    )) as cursor:
                        event_ids.append(cursor.lastrowid or 0)
                    insert_ms = (time.monotonic() - insert_start) * 1000
                    total_insert_ms += insert_ms
                    if insert_ms > _BATCH_APPEND_SLOW_PHASE_WARNING_MS:
                        logger.warning(
                            "batch_append: insert SLOW idx=%d/%d event_type=%s node_id=%s file_path=%s payload_bytes=%d source_len=%s duration_ms=%.1f",
                            idx,
                            len(prepared),
                            event_type,
                            current_node_id,
                            current_file_path,
                            payload_bytes,
                            source_len,
                            insert_ms,
                        )

                    projection_ms = 0.0
                    f_ups: list[CoreEvent] = []
                    if self._projection is not None:
                        projection_start = time.monotonic()
                        f_ups = self._projection.apply(self._conn, event)
                        all_follow_ups.extend(f_ups)
                        projection_ms = (time.monotonic() - projection_start) * 1000
                        total_projection_ms += projection_ms
                        if projection_ms > _BATCH_APPEND_SLOW_PHASE_WARNING_MS:
                            logger.warning(
                                "batch_append: projection SLOW idx=%d/%d event_type=%s node_id=%s file_path=%s payload_bytes=%d source_len=%s follow_ups=%d duration_ms=%.1f",
                                idx,
                                len(prepared),
                                event_type,
                                current_node_id,
                                current_file_path,
                                payload_bytes,
                                source_len,
                                len(f_ups),
                                projection_ms,
                            )

                    event_total_ms = (time.monotonic() - event_start) * 1000
                    if event_total_ms > _BATCH_APPEND_SLOW_PHASE_WARNING_MS:
                        logger.warning(
                            "batch_append: event SLOW idx=%d/%d event_type=%s node_id=%s file_path=%s payload_bytes=%d source_len=%s insert_ms=%.1f projection_ms=%.1f total_ms=%.1f follow_ups=%d",
                            idx,
                            len(prepared),
                            event_type,
                            current_node_id,
                            current_file_path,
                            payload_bytes,
                            source_len,
                            insert_ms,
                            projection_ms,
                            event_total_ms,
                            len(f_ups),
                        )
                    elif logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "batch_append: event end idx=%d/%d event_type=%s node_id=%s file_path=%s insert_ms=%.1f projection_ms=%.1f total_ms=%.1f follow_ups=%d",
                            idx,
                            len(prepared),
                            event_type,
                            current_node_id,
                            current_file_path,
                            insert_ms,
                            projection_ms,
                            event_total_ms,
                            len(f_ups),
                        )

                    if idx % 25 == 0:
                        logger.debug(
                            "batch_append: progress idx=%d/%d total_insert_ms=%.1f total_projection_ms=%.1f",
                            idx,
                            len(prepared),
                            total_insert_ms,
                            total_projection_ms,
                        )

                commit_start = time.monotonic()
                self._conn.execute("COMMIT")
                commit_ms = (time.monotonic() - commit_start) * 1000
                total_ms = (time.monotonic() - tx_start) * 1000
                if commit_ms > _BATCH_APPEND_SLOW_PHASE_WARNING_MS:
                    logger.warning(
                        "batch_append: COMMIT SLOW duration_ms=%.1f events=%d follow_ups=%d",
                        commit_ms,
                        len(prepared),
                        len(all_follow_ups),
                    )
                logger.debug(
                    "batch_append: tx complete duration_ms=%.1f events=%d follow_ups=%d total_insert_ms=%.1f total_projection_ms=%.1f commit_ms=%.1f",
                    total_ms,
                    len(prepared),
                    len(all_follow_ups),
                    total_insert_ms,
                    total_projection_ms,
                    commit_ms,
                )
                return event_ids, all_follow_ups
            except Exception:
                logger.exception(
                    "batch_append: failed idx=%d/%d event_type=%s node_id=%s file_path=%s; rolling back",
                    current_idx,
                    len(prepared),
                    current_event_type,
                    current_node_id,
                    current_file_path,
                )
                self._conn.execute("ROLLBACK")
                raise

        locked_write_start = time.monotonic()
        event_ids, follow_ups = await self._run_locked_write_with_retries("batch_append", _do_batch_append)
        locked_write_ms = (time.monotonic() - locked_write_start) * 1000
        if locked_write_ms > _BATCH_APPEND_SLOW_PHASE_WARNING_MS:
            logger.warning(
                "batch_append: locked write SLOW duration_ms=%.1f events=%d follow_ups=%d diagnostics=%s",
                locked_write_ms,
                len(prepared),
                len(follow_ups),
                self._lock_diagnostics(),
            )
        else:
            logger.debug(
                "batch_append: locked write duration_ms=%.1f events=%d follow_ups=%d",
                locked_write_ms,
                len(prepared),
                len(follow_ups),
            )

        # Process triggers and bus notifications for each event
        for idx, (_, _, _, _, _, to_agent, _, _, event) in enumerate(prepared):
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

        async with self._read_lock:
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

        async with self._read_lock:
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

    async def get_node(self, node_id: str) -> AgentNode | None:
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

        async with self._read_lock:
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
    ) -> list[AgentNode]:
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

        async with self._read_lock:
            rows = await asyncio.to_thread(_fetch, self._read_conn)

        return [AgentNode.from_row(row) for row in rows]

    async def get_node_at_position(
        self,
        file_path: str,
        line: int,
    ) -> AgentNode | None:
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

        async with self._read_lock:
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

    async def checkpoint_wal(self, mode: str = "PASSIVE") -> tuple[int, int, int]:
        """Run a WAL checkpoint and return (busy, log_frames, checkpointed_frames)."""
        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        mode_upper = mode.upper()
        if mode_upper not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
            raise ValueError(f"Unsupported checkpoint mode: {mode}")

        def _checkpoint() -> tuple[int, int, int]:
            assert self._conn is not None
            with contextlib.closing(self._conn.execute(f"PRAGMA wal_checkpoint({mode_upper})")) as cursor:
                row = cursor.fetchone()
            if row is None:
                return (0, 0, 0)
            return (int(row[0]), int(row[1]), int(row[2]))

        async with self._lock:
            result = await asyncio.to_thread(_checkpoint)

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
        self._trigger_queue = None

    def _source_length(self, event: StructuredEvent | CoreEvent) -> int | None:
        """Return source length for events that carry source_code."""
        source_code = getattr(event, "source_code", None)
        if isinstance(source_code, str):
            return len(source_code)
        return None

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
