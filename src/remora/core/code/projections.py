"""EventLog projections for materializing read models.

The NodeProjection processes events and maintains the `nodes` table.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from remora.core.events import CoreEvent
from remora.core.events.agent_events import AgentCompleteEvent, AgentErrorEvent, AgentStartEvent
from remora.core.events.code_events import NodeDiscoveredEvent, NodeRemovedEvent

logger = logging.getLogger(__name__)

_NODE_COLUMNS: tuple[str, ...] = (
    "node_id",
    "node_type",
    "name",
    "full_name",
    "file_path",
    "start_line",
    "end_line",
    "start_byte",
    "end_byte",
    "source_code",
    "source_hash",
    "parent_id",
    "caller_ids",
    "callee_ids",
    "status",
    "last_trigger_event",
    "last_completed_at",
    "extension_name",
    "custom_system_prompt",
    "mounted_workspaces",
    "extra_tools",
    "extra_subscriptions",
)

_INSERT_NODE_SQL = """
INSERT INTO nodes (
    node_id, node_type, name, full_name, file_path, start_line, end_line, start_byte, end_byte,
    source_code, source_hash, parent_id, caller_ids, callee_ids, status, last_trigger_event,
    last_completed_at, extension_name, custom_system_prompt, mounted_workspaces, extra_tools, extra_subscriptions
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    status = CASE
        WHEN nodes.status IN ('running', 'error')
        THEN nodes.status
        ELSE excluded.status
    END,
    extension_name = excluded.extension_name,
    custom_system_prompt = excluded.custom_system_prompt,
    mounted_workspaces = excluded.mounted_workspaces,
    extra_tools = excluded.extra_tools,
    extra_subscriptions = excluded.extra_subscriptions
"""


# Regex for stub patterns: def/class with only pass/... as body
_STUB_INLINE_RE = re.compile(
    r"^\s*(?:(?:async\s+)?def\s+\w+\s*\([^)]*\)\s*(?:->[^:]+)?\s*:\s*(?:pass|\.\.\.)"
    r"|class\s+\w+(?:\([^)]*\))?\s*:\s*(?:pass|\.\.\.))\s*$",
    re.DOTALL,
)

_STUB_BLOCK_RE = re.compile(
    r"^\s*(?:(?:async\s+)?def\s+\w+\s*\([^)]*\)\s*(?:->[^:]+)?\s*:"
    r"|class\s+\w+(?:\([^)]*\))?\s*:)"
    r"\s*\n"  # newline after colon
    r"(?:\s*(?:#[^\n]*|\"\"\"[^\"]*\"\"\"|\'\'\'[^\']*\'\'\')\s*\n)*"  # optional comments/docstrings
    r"\s*(?:pass|\.\.\.)\s*$",
    re.DOTALL,
)

# Content that is only comments, docstrings, and/or whitespace
_TRIVIAL_CONTENT_RE = re.compile(
    r"^(?:\s*(?:#[^\n]*|\"\"\"[^\"]*\"\"\"|\'\'\'[^\']*\'\'\')?\s*\n?)*$",
    re.DOTALL,
)


def _is_stub(source_code: str) -> bool:
    """Return True if source_code is empty, trivial, or a known stub pattern.

    Stub patterns include:
    - Empty or whitespace-only
    - Comments/docstrings only
    - ``class Foo: pass`` / ``class Foo: ...``
    - ``def foo(): pass`` / ``def foo(): ...``
    - Block form with optional docstring: ``def foo():\\n    pass``
    """
    stripped = source_code.strip()
    if not stripped:
        return True
    if _TRIVIAL_CONTENT_RE.fullmatch(source_code):
        return True
    if _STUB_INLINE_RE.fullmatch(stripped):
        return True
    if _STUB_BLOCK_RE.fullmatch(stripped):
        return True
    return False


def _dataclass_default(obj: Any) -> Any:
    """JSON serialization fallback for model/dataclass instances."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class NodeProjection:
    """Projects events into the `nodes` table."""

    def __init__(
        self,
        extension_matcher: Callable[[type, str, str, str, str], bool] | None = None,
        extension_configs: list[type] | None = None,
    ):
        self._extension_matcher = extension_matcher
        self._extension_configs = extension_configs or []

    def apply(self, conn: sqlite3.Connection, event: CoreEvent) -> list[CoreEvent]:
        """Apply a single event to the nodes table.

        Returns a (possibly empty) list of follow-up events that should be
        appended after the current transaction commits.

        Note: projection-originated scaffold follow-ups are currently disabled.
        See `_project_node_discovered()` for details and rationale.
        """
        if isinstance(event, NodeDiscoveredEvent):
            return self._project_node_discovered(conn, event)
        elif isinstance(event, NodeRemovedEvent):
            self._project_node_removed(conn, event)
        elif isinstance(event, AgentStartEvent):
            self._project_agent_start(conn, event)
        elif isinstance(event, AgentCompleteEvent):
            self._project_agent_complete(conn, event)
        elif isinstance(event, AgentErrorEvent):
            self._project_agent_error(conn, event)
        return []

    def _project_node_discovered(self, conn: sqlite3.Connection, event: NodeDiscoveredEvent) -> list[CoreEvent]:
        """Project a discovered node into the read model.

        Temporary behavior override (2026-03-05):
        scaffold/stub detection is intentionally disabled in this path.

        Why:
        - `_is_stub()` relies on regex patterns that can exhibit pathological
          backtracking on some multiline non-Python content (for example,
          markdown code-block nodes discovered from docs).
        - In production logs this manifested as ~10s stalls inside
          `EventStore.batch_append()` for a single `NodeDiscoveredEvent`.
        - Direct benchmark on a real offending payload (`node_id=rm_7m9iybrl`,
          `source_len=1340`) reproduced ~13s per `_is_stub()` call.
        - Because projection runs inside the active write transaction, this
          CPU stall appears as a scanner freeze and extends write-lock hold
          time, harming responsiveness.

        Operational tradeoff while disabled:
        - Newly discovered nodes are always stored with `status='idle'`.
        - Automatic projection-originated `ScaffoldRequestEvent` follow-ups are
          suppressed.
        - Explicit scaffold flows that emit `ScaffoldRequestEvent` directly
          (for example, `spawn_child`) still function.

        TODO:
        Re-enable scaffold detection after replacing the regex approach with a
        bounded-time implementation (AST/token-based or strictly linear checks).
        """
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
        if self._extension_matcher is not None:
            for ext in self._extension_configs:
                if self._extension_matcher(
                    ext,
                    row["node_type"],
                    row["name"],
                    file_path=row["file_path"],
                    source_code=row["source_code"],
                ):
                    ext_data = ext.get_extension_data()
                    for key, value in ext_data.items():
                        if key in row:
                            # Serialize lists/dicts to JSON strings for DB
                            if isinstance(value, (list, dict)):
                                row[key] = json.dumps(value, default=_dataclass_default)
                            else:
                                row[key] = value
                    break

        # Upsert: on conflict, update mutable fields.
        # Status updates to 'idle' when current status is idle/scaffold.
        # Running/error status is preserved so re-discovery does not clobber
        # active lifecycle state.
        conn.execute(
            _INSERT_NODE_SQL,
            [row[col] for col in _NODE_COLUMNS],
        )
        return []

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
