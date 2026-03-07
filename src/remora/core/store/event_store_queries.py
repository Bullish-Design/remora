"""Read/query helpers for EventStore."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from typing import Any


def row_to_event_dict(row: sqlite3.Row) -> dict[str, Any]:
    tags = row["tags"]
    if tags:
        tags = json.loads(tags)

    stored = json.loads(row["payload"])
    event_type = stored.get("event_type") or row["event_type"]
    meta_keys = {
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

    nested_payload: dict[str, Any] = {}
    original_payload = stored.get("payload")
    if isinstance(original_payload, dict) and original_payload:
        nested_payload.update(original_payload)

    for key, value in stored.items():
        if key not in meta_keys and value not in (None, "", {}, []):
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


def fetch_replay_rows(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    event_types: list[str] | None = None,
    since: float | None = None,
    until: float | None = None,
    after_id: int | None = None,
) -> list[sqlite3.Row]:
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
    with contextlib.closing(conn.execute(query, params)) as cursor:
        return cursor.fetchall()


def fetch_recent_event_rows(conn: sqlite3.Connection, *, agent_id: str, limit: int = 5) -> list[sqlite3.Row]:
    query = """
        SELECT * FROM events
        WHERE from_agent = ? OR to_agent = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
    """
    with contextlib.closing(conn.execute(query, (agent_id, agent_id, limit))) as cursor:
        return cursor.fetchall()


def fetch_correlation_rows(conn: sqlite3.Connection, *, correlation_id: str) -> list[sqlite3.Row]:
    query = """
        SELECT * FROM events
        WHERE correlation_id = ?
        ORDER BY timestamp ASC, id ASC
    """
    with contextlib.closing(conn.execute(query, (correlation_id,))) as cursor:
        return cursor.fetchall()


def fetch_graph_id_rows(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
    since: float | None = None,
) -> list[sqlite3.Row]:
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
    with contextlib.closing(conn.execute(query, params)) as cursor:
        return cursor.fetchall()


def fetch_event_count(conn: sqlite3.Connection, *, graph_id: str) -> int:
    with contextlib.closing(conn.execute("SELECT COUNT(*) FROM events WHERE graph_id = ?", (graph_id,))) as cursor:
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def delete_graph_events(conn: sqlite3.Connection, *, graph_id: str) -> int:
    with contextlib.closing(conn.execute("DELETE FROM events WHERE graph_id = ?", (graph_id,))) as cursor:
        return int(cursor.rowcount)


def fetch_node_row(conn: sqlite3.Connection, *, node_id: str) -> sqlite3.Row | None:
    with contextlib.closing(conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))) as cursor:
        return cursor.fetchone()


def fetch_node_rows(
    conn: sqlite3.Connection,
    *,
    file_path: str | None = None,
    node_type: str | None = None,
    columns: list[str] | None = None,
) -> list[sqlite3.Row]:
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

    with contextlib.closing(conn.execute(query, params)) as cursor:
        return cursor.fetchall()


def fetch_node_at_position_row(conn: sqlite3.Connection, *, file_path: str, line: int) -> sqlite3.Row | None:
    query = """SELECT * FROM nodes
               WHERE file_path = ? AND start_line <= ? AND end_line >= ?
               ORDER BY (end_line - start_line) ASC
               LIMIT 1"""
    with contextlib.closing(conn.execute(query, (file_path, line, line))) as cursor:
        return cursor.fetchone()


def update_node_status(conn: sqlite3.Connection, *, node_id: str, status: str) -> None:
    with contextlib.closing(conn.execute("UPDATE nodes SET status = ? WHERE node_id = ?", (status, node_id))):
        pass


def delete_nodes_for_file(conn: sqlite3.Connection, *, file_path: str) -> int:
    with contextlib.closing(conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))) as cursor:
        return int(cursor.rowcount)


def checkpoint_wal(conn: sqlite3.Connection, *, mode_upper: str) -> tuple[int, int, int]:
    with contextlib.closing(conn.execute(f"PRAGMA wal_checkpoint({mode_upper})")) as cursor:
        row = cursor.fetchone()
    if row is None:
        return (0, 0, 0)
    return (int(row[0]), int(row[1]), int(row[2]))
