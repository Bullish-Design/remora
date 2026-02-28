"""Subscription registry for reactive event routing.

This module provides the SubscriptionRegistry that enables push-based
event triggering. Agents subscribe to events and are notified when
matching events occur.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any

from remora.utils import PathLike, normalize_path

if TYPE_CHECKING:
    from remora.core.events import RemoraEvent


@dataclass
class SubscriptionPattern:
    """Pattern for matching events.

    All fields are optional. A None field means "match anything".
    Multiple values in a list are treated as OR (any match).
    """

    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None

    def matches(self, event: RemoraEvent) -> bool:
        """Check if this pattern matches the given event."""
        event_type = type(event).__name__

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


@dataclass
class Subscription:
    """A registered subscription."""

    id: int
    agent_id: str
    pattern: SubscriptionPattern
    is_default: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class SubscriptionRegistry:
    """Registry for agent event subscriptions.

    Manages persistent subscriptions in SQLite and provides
    pattern matching for event routing.
    """

    def __init__(self, db_path: PathLike):
        self._db_path = normalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Any = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the database and create tables."""
        async with self._lock:
            if self._conn is not None:
                return

            import sqlite3

            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
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
                conn.commit()
            
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
        pattern_json = json.dumps(asdict(pattern))

        def _exec(conn: Any) -> int:
            cursor = conn.execute(
                """
                INSERT INTO subscriptions (agent_id, pattern_json, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (agent_id, pattern_json, 1 if is_default else 0, now, now),
            )
            conn.commit()
            return cursor.lastrowid

        lastrowid = await asyncio.to_thread(_exec, self._conn)

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
            conn.commit()
            return cursor.rowcount

        return await asyncio.to_thread(_exec, self._conn)

    async def unregister(self, subscription_id: int) -> bool:
        """Remove a specific subscription by ID."""
        if self._conn is None:
            await self.initialize()

        def _exec(conn: Any) -> bool:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE id = ?",
                (subscription_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

        return await asyncio.to_thread(_exec, self._conn)

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

        return await asyncio.to_thread(_fetch, self._conn)

    async def get_matching_agents(self, event: RemoraEvent) -> list[str]:
        """Get all agent IDs whose subscriptions match the event."""
        if self._conn is None:
            await self.initialize()

        def _fetch(conn: Any) -> list[dict[str, Any]]:
            cursor = conn.execute("SELECT * FROM subscriptions ORDER BY id")
            return [dict(row) for row in cursor.fetchall()]

        rows = await asyncio.to_thread(_fetch, self._conn)

        matching_agents = []
        seen_agents = set()

        for row in rows:
            pattern_data = json.loads(row["pattern_json"])
            pattern = SubscriptionPattern(**pattern_data)

            if pattern.matches(event):
                agent_id = row["agent_id"]
                if agent_id not in seen_agents:
                    matching_agents.append(agent_id)
                    seen_agents.add(agent_id)

        return matching_agents

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


__all__ = ["Subscription", "SubscriptionPattern", "SubscriptionRegistry"]
