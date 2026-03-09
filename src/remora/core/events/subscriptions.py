"""Subscription registry for reactive event routing.

This module provides the SubscriptionRegistry that enables push-based
event triggering. Agents subscribe to events and are notified when
matching events occur.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from remora.utils import PathLike, normalize_path

if TYPE_CHECKING:
    from remora.core.events import CoreEvent

logger = logging.getLogger(__name__)


def _event_name(event: CoreEvent) -> str:
    """Resolve the routing event name.

    Uses event.event_type when present (bootstrap/dynamic envelopes),
    otherwise falls back to the concrete Python class name.
    """
    event_type = getattr(event, "event_type", None)
    if isinstance(event_type, str) and event_type:
        return event_type
    return type(event).__name__


class SubscriptionPattern(BaseModel):
    """Pattern for matching events.

    All fields are optional. A None field means "match anything".
    Multiple values in a list are treated as OR (any match).
    """

    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None

    def matches(self, event: CoreEvent) -> bool:
        """Check if this pattern matches the given event."""
        event_type = _event_name(event)

        if self.event_types is not None:
            if event_type not in self.event_types:
                return False

        if self.from_agents is not None:
            from_agent = getattr(event, "from_agent", None)
            if from_agent is None or from_agent not in self.from_agents:
                return False

        if self.to_agent is not None:
            to_agent = getattr(event, "to_agent", None)
            if to_agent != self.to_agent:
                return False

        if self.path_glob is not None:
            path = getattr(event, "path", None)
            if path is None:
                return False
            try:
                normalized = normalize_path(path).as_posix()
                if not PurePath(normalized).match(self.path_glob):
                    return False
            except Exception:
                return False

        if self.tags is not None:
            event_tags = getattr(event, "tags", None) or []
            if not any(tag in event_tags for tag in self.tags):
                return False

        return True


class Subscription(BaseModel):
    """A registered subscription."""

    id: int
    agent_id: str
    pattern: SubscriptionPattern
    is_default: bool = False
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class SubscriptionRegistry:
    """Registry for agent event subscriptions.

    Manages persistent subscriptions in SQLite and provides
    pattern matching for event routing.

    Can operate in two modes:
    - **Standalone**: pass ``db_path`` and the registry opens its own SQLite
      connection and creates the subscriptions table.
    - **Shared**: pass ``connection`` and ``lock`` from an ``EventStore``
      instance.  The subscriptions table is assumed to already exist
      (created by ``EventStore.initialize()``).
    """

    def __init__(
        self,
        db_path: PathLike | None = None,
        *,
        connection: Any = None,
        lock: asyncio.Lock | None = None,
    ):
        # Shared-connection mode
        if connection is not None:
            self._db_path: Path | None = None
            self._conn = connection
            self._lock = lock or asyncio.Lock()
            self._shared = True
        else:
            # Standalone mode (backward compat)
            if db_path is None:
                raise TypeError("Either db_path or connection must be provided")
            self._db_path = normalize_path(db_path)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn: Any = None
            self._lock = asyncio.Lock()
            self._shared = False

        # In-memory cache: maps event_type -> list of (agent_id, SubscriptionPattern)
        # None means cache is invalidated and must be rebuilt from DB.
        self._cache: dict[str, list[tuple[str, SubscriptionPattern]]] | None = None

    async def initialize(self) -> None:
        """Initialize the database and create tables.

        No-op when using a shared connection (tables created by EventStore).
        """
        if self._shared:
            # Tables already created by EventStore.initialize()
            return

        async with self._lock:
            if self._conn is not None:
                return

            import sqlite3

            self._conn = sqlite3.connect(
                str(self._db_path),
                timeout=15.0,
                check_same_thread=False,
                isolation_level=None,
            )
            self._conn.row_factory = sqlite3.Row

            def _init_db(conn: Any) -> None:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agent_id TEXT NOT NULL,
                        pattern_json TEXT NOT NULL,
                        is_default INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_agent_id ON subscriptions(agent_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_is_default ON subscriptions(is_default)")

            await asyncio.to_thread(_init_db, self._conn)

    async def register(
        self,
        agent_id: str,
        pattern: SubscriptionPattern,
        is_default: bool = False,
    ) -> Subscription:
        """Register a new subscription."""
        if self._conn is None:
            await self.initialize()

        now = time.time()
        pattern_json = json.dumps(pattern.model_dump())

        def _exec(conn: Any) -> int:
            cursor = conn.execute(
                """
                INSERT INTO subscriptions (agent_id, pattern_json, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (agent_id, pattern_json, 1 if is_default else 0, now, now),
            )
            return cursor.lastrowid

        async with self._lock:
            lastrowid = await asyncio.to_thread(_exec, self._conn)
            
        self._cache = None  # Invalidate cache

        return Subscription(
            id=lastrowid,
            agent_id=agent_id,
            pattern=pattern,
            is_default=is_default,
            created_at=now,
            updated_at=now,
        )

    async def register_defaults(self, agent_id: str, file_path: str) -> list[Subscription]:
        """Register default subscriptions for an agent.

        Creates:
        - Direct message subscription (to_agent = agent_id)
        - Source file subscription (ContentChanged for agent's file)
        """
        subscriptions = []

        direct_pattern = SubscriptionPattern(to_agent=agent_id)
        sub = await self.register(agent_id, direct_pattern, is_default=True)
        subscriptions.append(sub)

        file_pattern = SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob=file_path)
        sub = await self.register(agent_id, file_pattern, is_default=True)
        subscriptions.append(sub)

        return subscriptions

    async def unregister_all(self, agent_id: str) -> int:
        """Remove all subscriptions for an agent."""
        if self._conn is None:
            await self.initialize()

        def _exec(conn: Any) -> int:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE agent_id = ?",
                (agent_id,),
            )
            return cursor.rowcount

        async with self._lock:
            count = await asyncio.to_thread(_exec, self._conn)
            
        self._cache = None  # Invalidate cache
        return count

    async def unregister(self, subscription_id: int) -> bool:
        """Remove a specific subscription by ID."""
        if self._conn is None:
            await self.initialize()

        def _exec(conn: Any) -> bool:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE id = ?",
                (subscription_id,),
            )
            return cursor.rowcount > 0

        async with self._lock:
            removed = await asyncio.to_thread(_exec, self._conn)
            
        self._cache = None  # Invalidate cache
        return removed

    async def get_subscriptions(self, agent_id: str) -> list[Subscription]:
        """Get all subscriptions for an agent."""
        if self._conn is None:
            await self.initialize()

        def _fetch(conn: Any) -> list[Subscription]:
            cursor = conn.execute(
                "SELECT * FROM subscriptions WHERE agent_id = ? ORDER BY id",
                (agent_id,),
            )
            rows = cursor.fetchall()

            subscriptions = []
            for row in rows:
                pattern_data = json.loads(row["pattern_json"])
                pattern = SubscriptionPattern(**pattern_data)
                subscriptions.append(
                    Subscription(
                        id=row["id"],
                        agent_id=row["agent_id"],
                        pattern=pattern,
                        is_default=bool(row["is_default"]),
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
            return subscriptions

        async with self._lock:
            return await asyncio.to_thread(_fetch, self._conn)

    async def get_matching_agents(self, event: CoreEvent) -> list[str]:
        """Get all agent IDs whose subscriptions match the event.

        Uses an in-memory cache indexed by event_type for O(1) lookup.
        The cache is rebuilt from DB on first call and after any mutation.
        """
        if self._conn is None:
            await self.initialize()

        if self._cache is None:
            await self._rebuild_cache()

        assert self._cache is not None
        event_type = _event_name(event)

        # Collect candidates: subscriptions indexed under this event_type + wildcards (key "")
        candidates = self._cache.get(event_type, []) + self._cache.get("", [])

        matching_agents: list[str] = []
        seen_agents: set[str] = set()

        for agent_id, pattern in candidates:
            if agent_id not in seen_agents and pattern.matches(event):
                matching_agents.append(agent_id)
                seen_agents.add(agent_id)

        return matching_agents

    async def _rebuild_cache(self) -> None:
        """Rebuild the in-memory subscription cache from the database.

        Indexes subscriptions by event_type. Subscriptions with no event_type
        filter (wildcards) are stored under the empty string key "".
        """

        def _fetch(conn: Any) -> list[dict[str, Any]]:
            cursor = conn.execute("SELECT * FROM subscriptions ORDER BY id")
            return [dict(row) for row in cursor.fetchall()]

        async with self._lock:
            rows = await asyncio.to_thread(_fetch, self._conn)

        cache: dict[str, list[tuple[str, SubscriptionPattern]]] = {}
        for row in rows:
            pattern_data = json.loads(row["pattern_json"])
            pattern = SubscriptionPattern(**pattern_data)
            agent_id = row["agent_id"]
            entry = (agent_id, pattern)

            if pattern.event_types:
                for et in pattern.event_types:
                    cache.setdefault(et, []).append(entry)
            else:
                # Wildcard — no event_type filter, matches all event types
                cache.setdefault("", []).append(entry)

        self._cache = cache

    async def close(self) -> None:
        """Close the database connection.

        Skips closing when using a shared connection (owned by EventStore).
        """
        self._cache = None
        if self._shared:
            # Don't close shared connection — it's owned by EventStore
            return
        if self._conn:
            self._conn.close()
            self._conn = None

    def _close_sync(self) -> None:
        """Best-effort synchronous cleanup used by the finalizer path."""
        self._cache = None
        if self._shared:
            return
        if self._conn:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def __del__(self) -> None:
        # Finalizer safeguard for tests that forget to await close().
        self._close_sync()


__all__ = ["Subscription", "SubscriptionPattern", "SubscriptionRegistry"]
