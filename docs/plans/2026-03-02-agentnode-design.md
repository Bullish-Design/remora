# AgentNode Unified Model: Implementation Design

> **Status:** Implementation-ready design spec  
> **Extracted from:** `docs/EventBased_Concept.md` Section 1.7 + related sections  
> **Companion:** `docs/plans/2026-03-01-architectural-unification.md` (implementation plan)  
> **Date:** 2026-03-02

## 1. Problem

The current codebase has four separate representations for agent data:

| Current Model | Location | Role |
|--------------|----------|------|
| `CSTNode` | `src/remora/core/discovery.py` | Tree-sitter discovery output (frozen dataclass) |
| `AgentState` | `src/remora/core/agent_state.py` | Runtime state persisted to JSONL files |
| `ASTAgentNode` | `src/remora/lsp/models.py` | Pydantic model for LSP responses |
| `ExtensionNode` | `src/remora/lsp/extensions.py` | Base class for behavioral specialization via inheritance |

This split causes: manual conversion code between representations, inconsistent field sets, `isinstance` checks for extension behavior, and two persistence mechanisms (JSONL + SQLite).

## 2. Solution

Replace `AgentState`, `ASTAgentNode`, and `ExtensionNode` with a single `AgentNode` Pydantic `BaseModel`. `CSTNode` stays as the tree-sitter output — it feeds into `AgentNode` via the EventLog projection.

**No subclasses. No isinstance. Specialization is data.**

## 3. The Model

```python
from pydantic import BaseModel, ConfigDict, Field

class AgentNode(BaseModel):
    """Unified agent model: DB row, LLM prompt, and LSP response in one object."""
    model_config = ConfigDict(frozen=False)

    # --- Identity (from CSTNode via event projection) ---
    node_id: str                    # SHA256(file_path:name:start_line:end_line)[:16]
    node_type: str                  # "function", "class", "method", "file", "section", "table"
    name: str                       # e.g., "calculate_total"
    full_name: str                  # e.g., "function:calculate_total"
    file_path: str                  # absolute path to source file
    start_line: int                 # 1-based
    end_line: int                   # 1-based
    source_code: str                # raw source text
    source_hash: str                # SHA256 of source_code for change detection

    # --- Graph context (from edges table) ---
    parent_id: str | None = None
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)

    # --- Runtime state (from event projections) ---
    status: str = "idle"            # "idle", "running", "error", "pending_approval"
    last_trigger_event: str = ""    # event_type that last triggered this agent
    last_completed_at: float | None = None

    # --- Specialization (from extension config matching) ---
    extension_name: str | None = None
    custom_system_prompt: str = ""
    mounted_workspaces: list[str] = Field(default_factory=list)
    extra_tools: list[ToolSchema] = Field(default_factory=list)
    extra_subscriptions: list[SubscriptionPattern] = Field(default_factory=list)
```

### Supporting Types

```python
from dataclasses import dataclass

@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: dict  # JSON Schema object

    def to_code_action(self, node_id: str) -> lsp.CodeAction:
        return lsp.CodeAction(
            title=self.description,
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(
                title=self.name,
                command=f"remora.tool.{self.name}",
                arguments=[node_id],
            ),
        )
```

`SubscriptionPattern` already exists in `src/remora/core/subscriptions.py` — no changes needed.

## 4. Database Schema

### `nodes` Table

```sql
CREATE TABLE IF NOT EXISTS nodes (
    node_id         TEXT PRIMARY KEY,
    node_type       TEXT NOT NULL,
    name            TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    source_code     TEXT NOT NULL,
    source_hash     TEXT NOT NULL,
    parent_id       TEXT,
    caller_ids      TEXT NOT NULL DEFAULT '[]',      -- JSON array of strings
    callee_ids      TEXT NOT NULL DEFAULT '[]',      -- JSON array of strings
    status          TEXT NOT NULL DEFAULT 'idle',
    last_trigger_event TEXT NOT NULL DEFAULT '',
    last_completed_at  REAL,
    extension_name  TEXT,
    custom_system_prompt TEXT NOT NULL DEFAULT '',
    mounted_workspaces TEXT NOT NULL DEFAULT '[]',   -- JSON array of strings
    extra_tools     TEXT NOT NULL DEFAULT '[]',      -- JSON array of ToolSchema dicts
    extra_subscriptions TEXT NOT NULL DEFAULT '[]'   -- JSON array of SubscriptionPattern dicts
);

CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_parent_id ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_node_type ON nodes(node_type);
```

### Hydration

```python
import json
import sqlite3

@classmethod
def from_row(cls, row: sqlite3.Row) -> AgentNode:
    data = dict(row)
    data["caller_ids"] = json.loads(data.get("caller_ids", "[]"))
    data["callee_ids"] = json.loads(data.get("callee_ids", "[]"))
    data["extra_tools"] = [ToolSchema(**t) for t in json.loads(data.get("extra_tools", "[]"))]
    data["extra_subscriptions"] = [
        SubscriptionPattern(**s) for s in json.loads(data.get("extra_subscriptions", "[]"))
    ]
    data["mounted_workspaces"] = json.loads(data.get("mounted_workspaces", "[]"))
    return cls(**data)
```

### Serialization

```python
def to_row(self) -> dict:
    data = self.model_dump()
    data["caller_ids"] = json.dumps(data["caller_ids"])
    data["callee_ids"] = json.dumps(data["callee_ids"])
    data["extra_tools"] = json.dumps([t.__dict__ for t in self.extra_tools])
    data["extra_subscriptions"] = json.dumps([s.__dict__ for s in self.extra_subscriptions])
    data["mounted_workspaces"] = json.dumps(data["mounted_workspaces"])
    return data
```

## 5. Extension Config Pattern

Extension configs live in `.remora/models/`. They are Python classes with two static methods:

```python
from remora.extensions import AgentExtension, ToolSchema, SubscriptionPattern

class SomeExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        """Return True if this extension should apply to the given node."""
        ...

    @staticmethod
    def get_extension_data() -> dict:
        """Return field overrides for the AgentNode."""
        return {
            "extension_name": "SomeName",
            "custom_system_prompt": "...",
            "extra_tools": [...],
            "extra_subscriptions": [...],
            "mounted_workspaces": [...],
        }
```

### Loading

Extension configs are loaded from `.remora/models/*.py` with mtime-based caching. On each discovery pass, changed files are re-imported. The loader:

1. Scans `.remora/models/*.py`
2. For each file with updated mtime, import the module
3. Find all classes that subclass `AgentExtension`
4. Cache them in a list sorted by specificity (most specific matches first)

### Matching Priority

First match wins. Extension configs are checked in file-alphabetical order. If multiple extensions could match the same node, the developer controls priority through file naming (e.g., `00_test_agent.py` before `50_generic.py`).

## 6. Projection Logic

The EventLog projection processes events and maintains the `nodes` table:

### NodeDiscoveredEvent

```python
def project_node_discovered(self, event, db):
    row = {
        "node_id": event.node_id,
        "node_type": event.node_type,
        "name": event.name,
        "full_name": event.full_name,
        "file_path": event.file_path,
        "start_line": event.start_line,
        "end_line": event.end_line,
        "source_code": event.source_code,
        "source_hash": event.source_hash,
        "parent_id": event.parent_id,
    }
    # Match extension configs
    for ext in self.extension_configs:
        if ext.matches(row["node_type"], row["name"]):
            row.update(ext.get_extension_data())
            break  # first match wins

    # Serialize JSON columns
    for col in ("caller_ids", "callee_ids", "extra_tools", "extra_subscriptions", "mounted_workspaces"):
        if col in row and not isinstance(row[col], str):
            row[col] = json.dumps(row[col], default=lambda o: o.__dict__)

    db.execute("INSERT OR REPLACE INTO nodes (...) VALUES (...)", row)
```

### AgentStartEvent / AgentCompleteEvent / AgentErrorEvent

```python
def project_agent_start(self, event, db):
    db.execute(
        "UPDATE nodes SET status = 'running', last_trigger_event = ? WHERE node_id = ?",
        (event.trigger_event_type, event.agent_id)
    )

def project_agent_complete(self, event, db):
    db.execute(
        "UPDATE nodes SET status = 'idle', last_completed_at = ? WHERE node_id = ?",
        (event.timestamp, event.agent_id)
    )

def project_agent_error(self, event, db):
    db.execute(
        "UPDATE nodes SET status = 'error' WHERE node_id = ?",
        (event.agent_id,)
    )
```

### NodeRemovedEvent

```python
def project_node_removed(self, event, db):
    db.execute("DELETE FROM subscriptions WHERE agent_id = ?", (event.node_id,))
    db.execute("DELETE FROM nodes WHERE node_id = ?", (event.node_id,))
```

## 7. Conversion Methods

### to_system_prompt()

Generates the LLM system prompt from all fields:

```python
def to_system_prompt(self) -> str:
    prompt = f"""You are an autonomous AI agent embodying a Python {self.node_type}: `{self.name}`

# Identity
- Node ID: {self.node_id}
- Location: {self.file_path}:{self.start_line}-{self.end_line}
- Parent: {self.parent_id or "None (top-level)"}

# Your Source Code
```python
{self.source_code}
```

# Graph Context
- Called by: {", ".join(self.caller_ids) or "None"}
- You call: {", ".join(self.callee_ids) or "None"}

# Core Rules
1. You may ONLY edit your own body using `rewrite_self()`.
2. To request changes elsewhere, use `message_node(target_id, request)`.
3. All edits are proposals -- the human must approve before they apply.
"""
    if self.custom_system_prompt:
        prompt += f"\n# Specialization ({self.extension_name})\n{self.custom_system_prompt}\n"
    if self.mounted_workspaces:
        prompt += "\n# Available Workspaces\n" + "\n".join(f"- {w}" for w in self.mounted_workspaces) + "\n"
    return prompt
```

### to_code_lens()

```python
def to_code_lens(self) -> lsp.CodeLens:
    status_icon = {"idle": "●", "running": "▶", "pending_approval": "⏸", "error": "○"}
    return lsp.CodeLens(
        range=lsp.Range(
            start=lsp.Position(line=self.start_line - 1, character=0),
            end=lsp.Position(line=self.start_line - 1, character=0),
        ),
        command=lsp.Command(
            title=f"{status_icon.get(self.status, '?')} {self.node_id}",
            command="remora.selectAgent",
            arguments=[self.node_id],
        ),
    )
```

### to_hover(recent_events)

```python
def to_hover(self, recent_events: list | None = None) -> lsp.Hover:
    lines = [
        f"## {self.name}",
        f"**ID:** `{self.node_id}`  **Type:** {self.node_type}  **Status:** {self.status}",
        f"**Parent:** `{self.parent_id or 'None'}`",
        f"**Callers:** {', '.join(f'`{c}`' for c in self.caller_ids) or 'None'}",
        f"**Callees:** {', '.join(f'`{c}`' for c in self.callee_ids) or 'None'}",
    ]
    if self.extension_name:
        lines.append(f"**Extension:** {self.extension_name}")
    if recent_events:
        lines.extend(["", "---", "", "### Recent Events"])
        for ev in recent_events:
            lines.append(f"- `{ev.event_type}` {ev.summary}")
    return lsp.Hover(
        contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value="\n".join(lines)),
        range=self.to_range(),
    )
```

### to_code_actions()

```python
def to_code_actions(self) -> list[lsp.CodeAction]:
    actions = [
        lsp.CodeAction(title="Chat with this agent", kind=lsp.CodeActionKind.Empty,
                        command=lsp.Command(title="Chat", command="remora.chat", arguments=[self.node_id])),
        lsp.CodeAction(title="Ask agent to rewrite itself", kind=lsp.CodeActionKind.RefactorRewrite,
                        command=lsp.Command(title="Rewrite", command="remora.requestRewrite", arguments=[self.node_id])),
        lsp.CodeAction(title="Message another agent", kind=lsp.CodeActionKind.Empty,
                        command=lsp.Command(title="Message", command="remora.messageNode", arguments=[self.node_id])),
    ]
    for tool in self.extra_tools:
        actions.append(tool.to_code_action(self.node_id))
    return actions
```

### to_document_symbol()

```python
def to_document_symbol(self) -> lsp.DocumentSymbol:
    kind_map = {
        "function": lsp.SymbolKind.Function,
        "method": lsp.SymbolKind.Method,
        "class": lsp.SymbolKind.Class,
        "file": lsp.SymbolKind.File,
        "section": lsp.SymbolKind.String,
        "table": lsp.SymbolKind.Object,
    }
    return lsp.DocumentSymbol(
        name=f"{self.name} [{self.status}]",
        kind=kind_map.get(self.node_type, lsp.SymbolKind.Variable),
        range=self.to_range(),
        selection_range=self.to_range(),
        detail=self.extension_name or self.node_type,
    )
```

### to_range() (helper)

```python
def to_range(self) -> lsp.Range:
    return lsp.Range(
        start=lsp.Position(line=self.start_line - 1, character=0),
        end=lsp.Position(line=self.end_line - 1, character=0),
    )
```

## 8. Migration Plan

### Files to Create
- `src/remora/core/agent_node.py` — the `AgentNode` model + `ToolSchema`

### Files to Modify
- `src/remora/core/__init__.py` — export `AgentNode`
- `src/remora/lsp/server.py` — use `AgentNode.from_row()` in LSP handlers
- `src/remora/core/runner.py` — load `AgentNode` from nodes table instead of JSONL
- `src/remora/core/executor.py` — use `agent.to_system_prompt()` + `agent.extra_tools`

### Files to Remove (after migration)
- `src/remora/core/agent_state.py` — replaced by `AgentNode`
- `src/remora/lsp/models.py` — `ASTAgentNode` replaced by `AgentNode` (keep `RewriteProposal`)
- `src/remora/lsp/extensions.py` — `ExtensionNode` base class replaced by `AgentExtension`

### New Files
- `src/remora/extensions.py` — `AgentExtension` base class + config loader

### Database Migration
- Add `nodes` table with schema from Section 4
- Existing `.remora/agents/*.jsonl` files can be migrated to nodes table rows on first run, then ignored

## 9. Testing Strategy

- Unit tests for `AgentNode.from_row()` / `.to_row()` round-trip
- Unit tests for each conversion method (`.to_system_prompt()`, `.to_code_lens()`, `.to_hover()`, `.to_code_actions()`)
- Unit tests for extension config loading and matching
- Integration test for projection: emit `NodeDiscoveredEvent` → verify nodes table row → hydrate `AgentNode`
- Integration test for status updates: emit `AgentStartEvent`/`AgentCompleteEvent` → verify status field changes
- Regression tests for LSP handlers producing valid LSP types
