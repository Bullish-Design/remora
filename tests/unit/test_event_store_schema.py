from __future__ import annotations

import sqlite3

from remora.core.store.event_store_schema import create_tables


def test_create_tables_creates_bootstrap_graph_tables(tmp_path) -> None:
    db_path = tmp_path / "schema.db"
    conn = sqlite3.connect(str(db_path))
    try:
        create_tables(conn)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "graph_nodes" in tables
        assert "graph_edges" in tables
    finally:
        conn.close()

