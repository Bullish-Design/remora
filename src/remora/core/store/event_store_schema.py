"""Schema and migration helpers for EventStore."""

from __future__ import annotations

import contextlib
import sqlite3


def create_graph_tables(conn: sqlite3.Connection) -> None:
    """Create generic bootstrap graph tables in the EventStore DB."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS graph_nodes (
            id          TEXT PRIMARY KEY,
            kind        TEXT NOT NULL,
            attrs_json  TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_gnode_kind ON graph_nodes(kind);

        CREATE TABLE IF NOT EXISTS graph_edges (
            from_id     TEXT NOT NULL,
            to_id       TEXT NOT NULL,
            kind        TEXT NOT NULL,
            attrs_json  TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (from_id, to_id, kind)
        );

        CREATE INDEX IF NOT EXISTS idx_gedge_from ON graph_edges(from_id);
        CREATE INDEX IF NOT EXISTS idx_gedge_to   ON graph_edges(to_id);
        """
    )


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
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
        """
    )

    conn.executescript(
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
        """
    )

    conn.executescript(
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
        """
    )

    create_graph_tables(conn)


def migrate(conn: sqlite3.Connection) -> None:
    """Add routing/position fields for existing databases."""

    def _get_columns(table: str) -> set[str]:
        with contextlib.closing(conn.execute(f"PRAGMA table_info({table})")) as cursor:
            return {row["name"] for row in cursor.fetchall()}

    columns = _get_columns("events")
    if "from_agent" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN from_agent TEXT")
    if "to_agent" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN to_agent TEXT")
    if "correlation_id" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN correlation_id TEXT")
    if "tags" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN tags TEXT")

    node_columns = _get_columns("nodes")
    if "start_byte" not in node_columns:
        conn.execute("ALTER TABLE nodes ADD COLUMN start_byte INTEGER NOT NULL DEFAULT 0")
    if "end_byte" not in node_columns:
        conn.execute("ALTER TABLE nodes ADD COLUMN end_byte INTEGER NOT NULL DEFAULT 0")
