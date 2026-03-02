"""EventLog projections for materializing read models.

The NodeProjection processes events and maintains the `nodes` table.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, is_dataclass
from typing import Any, Type

from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    RemoraEvent,
)

logger = logging.getLogger(__name__)


def _dataclass_default(obj: Any) -> Any:
    """JSON serialization fallback for dataclass instances."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class NodeProjection:
    """Projects events into the `nodes` table."""

    def __init__(self, extension_configs: list[Type] | None = None):
        self._extension_configs = extension_configs or []

    def apply(self, conn: sqlite3.Connection, event: RemoraEvent) -> None:
        """Apply a single event to the nodes table."""
        if isinstance(event, NodeDiscoveredEvent):
            self._project_node_discovered(conn, event)
        elif isinstance(event, NodeRemovedEvent):
            self._project_node_removed(conn, event)
        elif isinstance(event, AgentStartEvent):
            self._project_agent_start(conn, event)
        elif isinstance(event, AgentCompleteEvent):
            self._project_agent_complete(conn, event)
        elif isinstance(event, AgentErrorEvent):
            self._project_agent_error(conn, event)

    def _project_node_discovered(self, conn: sqlite3.Connection, event: NodeDiscoveredEvent) -> None:
        row: dict[str, Any] = {
            "node_id": event.node_id,
            "node_type": event.node_type,
            "name": event.name,
            "full_name": event.full_name,
            "file_path": event.file_path,
            "start_line": event.start_line,
            "end_line": event.end_line,
            "start_byte": event.start_byte,
            "end_byte": event.end_byte,
            "source_code": event.source_code,
            "source_hash": event.source_hash,
            "parent_id": event.parent_id,
            "caller_ids": "[]",
            "callee_ids": "[]",
            "status": "idle",
            "last_trigger_event": "",
            "last_completed_at": None,
            "extension_name": None,
            "custom_system_prompt": "",
            "mounted_workspaces": "[]",
            "extra_tools": "[]",
            "extra_subscriptions": "[]",
        }

        # Match extension configs (first match wins)
        for ext in self._extension_configs:
            if ext.matches(row["node_type"], row["name"]):
                ext_data = ext.get_extension_data()
                for key, value in ext_data.items():
                    if key in row:
                        # Serialize lists/dicts to JSON strings for DB
                        if isinstance(value, (list, dict)):
                            row[key] = json.dumps(value, default=_dataclass_default)
                        else:
                            row[key] = value
                break

        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" * len(row))
        # Upsert: on conflict, update mutable fields but preserve status
        conn.execute(
            f"""INSERT INTO nodes ({cols}) VALUES ({placeholders})
                ON CONFLICT(node_id) DO UPDATE SET
                    node_type = excluded.node_type,
                    name = excluded.name,
                    full_name = excluded.full_name,
                    file_path = excluded.file_path,
                    start_line = excluded.start_line,
                    end_line = excluded.end_line,
                    start_byte = excluded.start_byte,
                    end_byte = excluded.end_byte,
                    source_code = excluded.source_code,
                    source_hash = excluded.source_hash,
                    parent_id = excluded.parent_id,
                    extension_name = excluded.extension_name,
                    custom_system_prompt = excluded.custom_system_prompt,
                    mounted_workspaces = excluded.mounted_workspaces,
                    extra_tools = excluded.extra_tools,
                    extra_subscriptions = excluded.extra_subscriptions
            """,
            list(row.values()),
        )

    def _project_node_removed(self, conn: sqlite3.Connection, event: NodeRemovedEvent) -> None:
        conn.execute("DELETE FROM nodes WHERE node_id = ?", (event.node_id,))

    def _project_agent_start(self, conn: sqlite3.Connection, event: AgentStartEvent) -> None:
        conn.execute(
            "UPDATE nodes SET status = 'running', last_trigger_event = ? WHERE node_id = ?",
            (event.trigger_event_type, event.agent_id),
        )

    def _project_agent_complete(self, conn: sqlite3.Connection, event: AgentCompleteEvent) -> None:
        conn.execute(
            "UPDATE nodes SET status = 'idle', last_completed_at = ? WHERE node_id = ?",
            (event.timestamp, event.agent_id),
        )

    def _project_agent_error(self, conn: sqlite3.Connection, event: AgentErrorEvent) -> None:
        conn.execute(
            "UPDATE nodes SET status = 'error' WHERE node_id = ?",
            (event.agent_id,),
        )
