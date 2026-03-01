import json
import time
from pathlib import Path
from typing import Any
import sqlite3

from .models import ASTAgentNode, AgentEvent


class RemoraDB:
    def __init__(self, db_path: str = ".remora/indexer.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cursor = self.conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                start_col INTEGER DEFAULT 0,
                end_col INTEGER DEFAULT 0,
                source_code TEXT,
                source_hash TEXT,
                status TEXT DEFAULT 'active',
                pending_proposal_id TEXT,
                parent_id TEXT REFERENCES nodes(id)
            );

            CREATE TABLE IF NOT EXISTS edges (
                from_id TEXT NOT NULL REFERENCES nodes(id),
                to_id TEXT NOT NULL REFERENCES nodes(id),
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

            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                timestamp REAL NOT NULL,
                correlation_id TEXT,
                agent_id TEXT,
                payload JSON NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proposals (
                proposal_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL REFERENCES nodes(id),
                old_source TEXT NOT NULL,
                new_source TEXT NOT NULL,
                diff TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
            CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id);
            CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id);
            CREATE INDEX IF NOT EXISTS idx_chain_correlation ON activation_chain(correlation_id);
        """)
        self.conn.commit()

    def upsert_nodes(self, nodes: list[ASTAgentNode]):
        cursor = self.conn.cursor()
        for node in nodes:
            cursor.execute(
                """
                INSERT OR REPLACE INTO nodes 
                (id, node_type, name, file_path, start_line, end_line, start_col, end_col,
                 source_code, source_hash, status, pending_proposal_id, parent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    node.remora_id,
                    node.node_type,
                    node.name,
                    node.file_path,
                    node.start_line,
                    node.end_line,
                    node.start_col,
                    node.end_col,
                    node.source_code,
                    node.source_hash,
                    node.status,
                    node.pending_proposal_id,
                    node.parent_id,
                ),
            )
        self.conn.commit()

    def get_node(self, node_id: str) -> dict | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_nodes_for_file(self, uri: str) -> list[dict]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE file_path = ?", (uri,))
        return [dict(row) for row in cursor.fetchall()]

    def get_node_at_position(self, uri: str, line: int, character: int) -> dict | None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM nodes 
            WHERE file_path = ? AND start_line <= ? AND end_line >= ?
            ORDER BY start_line DESC LIMIT 1
        """,
            (uri, line, line),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def set_status(self, node_id: str, status: str):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE nodes SET status = ? WHERE id = ?", (status, node_id))
        self.conn.commit()

    def set_pending_proposal(self, node_id: str, proposal_id: str | None):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE nodes SET pending_proposal_id = ? WHERE id = ?", (proposal_id, node_id))
        self.conn.commit()

    def clear_pending_proposal(self, node_id: str):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE nodes SET pending_proposal_id = NULL, status = 'active' WHERE id = ?", (node_id,))
        self.conn.commit()

    def get_recent_events(self, agent_id: str, limit: int = 5) -> list[AgentEvent]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM events 
            WHERE agent_id = ? 
            ORDER BY timestamp DESC LIMIT ?
        """,
            (agent_id, limit),
        )
        events = []
        for row in cursor.fetchall():
            payload = json.loads(row["payload"])
            payload["event_id"] = row["event_id"]
            payload["event_type"] = row["event_type"]
            payload["timestamp"] = row["timestamp"]
            payload["correlation_id"] = row["correlation_id"]
            payload["agent_id"] = row["agent_id"]
            events.append(AgentEvent(**payload))
        return events

    def store_event(self, event: AgentEvent):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO events (event_id, event_type, timestamp, correlation_id, agent_id, payload)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                event.event_id,
                event.event_type,
                event.timestamp,
                event.correlation_id,
                event.agent_id,
                json.dumps(event.payload),
            ),
        )
        self.conn.commit()

    def get_events_for_correlation(self, correlation_id: str) -> list[AgentEvent]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM events 
            WHERE correlation_id = ?
            ORDER BY timestamp ASC
        """,
            (correlation_id,),
        )
        events = []
        for row in cursor.fetchall():
            payload = json.loads(row["payload"])
            payload["event_id"] = row["event_id"]
            payload["event_type"] = row["event_type"]
            payload["timestamp"] = row["timestamp"]
            payload["correlation_id"] = row["correlation_id"]
            payload["agent_id"] = row["agent_id"]
            events.append(AgentEvent(**payload))
        return events

    def add_to_chain(self, correlation_id: str, agent_id: str):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO activation_chain (correlation_id, agent_id, depth, timestamp)
            VALUES (?, ?, 1, ?)
        """,
            (correlation_id, agent_id, time.time()),
        )
        self.conn.commit()

    def get_activation_chain(self, correlation_id: str) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT agent_id FROM activation_chain 
            WHERE correlation_id = ?
            ORDER BY depth ASC
        """,
            (correlation_id,),
        )
        return [row["agent_id"] for row in cursor.fetchall()]

    def update_edges(self, nodes: list[ASTAgentNode]):
        cursor = self.conn.cursor()
        for node in nodes:
            if node.parent_id:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO edges (from_id, to_id, edge_type)
                    VALUES (?, ?, 'parent_of')
                """,
                    (node.parent_id, node.remora_id),
                )
            for callee in node.callee_ids:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO edges (from_id, to_id, edge_type)
                    VALUES (?, ?, 'calls')
                """,
                    (node.remora_id, callee),
                )
        self.conn.commit()

    def get_neighborhood(self, node_id: str, depth: int = 2) -> list[dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            WITH RECURSIVE neighbors(from_id, to_id, edge_type, d) AS (
                SELECT NULL, ?, 'self', 0
                UNION ALL
                SELECT e.from_id, e.to_id, e.edge_type, n.d + 1
                FROM edges e
                JOIN neighbors n ON e.from_id = n.to_id OR e.to_id = n.from_id
                WHERE n.d < ?
            )
            SELECT DISTINCT id FROM nodes
            WHERE id IN (SELECT from_id FROM neighbors) OR id IN (SELECT to_id FROM neighbors)
        """,
            (node_id, depth),
        )
        node_ids = [row["id"] for row in cursor.fetchall()]

        if not node_ids:
            return []

        placeholders = ",".join("?" * len(node_ids))
        cursor.execute(f"SELECT * FROM nodes WHERE id IN ({placeholders})", node_ids)
        return [dict(row) for row in cursor.fetchall()]

    def get_edges_for_nodes(self, node_ids: list[str]) -> list[dict]:
        if not node_ids:
            return []
        cursor = self.conn.cursor()
        placeholders = ",".join("?" * len(node_ids))
        cursor.execute(
            f"""
            SELECT * FROM edges 
            WHERE from_id IN ({placeholders}) AND to_id IN ({placeholders})
        """,
            node_ids + node_ids,
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_proposals_for_file(self, file_path: str) -> list[dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT p.*, n.file_path as node_file_path FROM proposals p
            JOIN nodes n ON p.agent_id = n.id
            WHERE n.file_path = ? AND p.status = 'pending'
        """,
            (file_path,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def store_proposal(self, proposal_id: str, agent_id: str, old_source: str, new_source: str, diff: str):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO proposals (proposal_id, agent_id, old_source, new_source, diff, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """,
            (proposal_id, agent_id, old_source, new_source, diff, time.time()),
        )
        self.conn.commit()

    def update_proposal_status(self, proposal_id: str, status: str):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE proposals SET status = ? WHERE proposal_id = ?", (status, proposal_id))
        self.conn.commit()

    def get_proposal(self, proposal_id: str) -> dict | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def close(self):
        self.conn.close()
