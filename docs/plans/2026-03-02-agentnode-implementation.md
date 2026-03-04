# AgentNode Unified Model: Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> **CRITICAL RULE: NO SUBAGENTS. All work must be done in a single agent context. NEVER use the Task tool or dispatch parallel agents.**

**Goal:** Replace `AgentState`, `ASTAgentNode`, and `ExtensionNode` with a single `AgentNode` Pydantic model backed by an EventLog-projected `nodes` table.

**Architecture:** `AgentNode` is a materialized view — the EventLog is the source of truth, a projection writes to the `nodes` SQLite table, and `AgentNode.from_row()` hydrates the model. CSTNode stays as tree-sitter output. Specialization is data fields populated by extension configs (no subclasses, no isinstance).

**Tech Stack:** Python 3.12+, Pydantic v2, SQLite, tree-sitter, pytest, lsprotocol/pygls

**Design Spec:** `docs/plans/2026-03-02-agentnode-design.md`

---

## Task 1: Create AgentNode Model

**Files:**
- Create: `src/remora/core/agent_node.py`
- Test: `tests/unit/test_agent_node.py`

### Step 1: Write the failing test

```python
# tests/unit/test_agent_node.py
"""Tests for AgentNode unified model."""
from __future__ import annotations

import json
import sqlite3

import pytest

from remora.core.agent_node import AgentNode, ToolSchema


def _make_node(**overrides) -> AgentNode:
    """Helper to create a test AgentNode with sensible defaults."""
    defaults = {
        "node_id": "abc123def456",
        "node_type": "function",
        "name": "calculate_total",
        "full_name": "function:calculate_total",
        "file_path": "/src/billing.py",
        "start_line": 10,
        "end_line": 25,
        "source_code": "def calculate_total(items): return sum(items)",
        "source_hash": "aabbccdd11223344",
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


class TestAgentNodeCreation:
    def test_create_minimal(self):
        node = _make_node()
        assert node.node_id == "abc123def456"
        assert node.node_type == "function"
        assert node.status == "idle"
        assert node.extension_name is None
        assert node.extra_tools == []
        assert node.extra_subscriptions == []

    def test_create_with_extension_fields(self):
        tool = ToolSchema(
            name="run_test",
            description="Run this test",
            parameters={"type": "object", "properties": {}},
        )
        node = _make_node(
            extension_name="TestAgent",
            custom_system_prompt="You are a test agent.",
            extra_tools=[tool],
        )
        assert node.extension_name == "TestAgent"
        assert len(node.extra_tools) == 1
        assert node.extra_tools[0].name == "run_test"
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/unit/test_agent_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'remora.core.agent_node'`

### Step 3: Write minimal implementation

```python
# src/remora/core/agent_node.py
"""AgentNode unified model.

Single Pydantic model that serves as DB row, LLM prompt source,
and LSP protocol response. No subclasses. Specialization is data.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from remora.core.subscriptions import SubscriptionPattern


@dataclass
class ToolSchema:
    """Schema for an agent tool."""

    name: str
    description: str
    parameters: dict  # JSON Schema object

    def to_llm_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class AgentNode(BaseModel):
    """Unified agent model: DB row, LLM prompt, and LSP response in one object.

    No subclasses. Specialization via data fields populated by extension configs.
    """

    model_config = ConfigDict(frozen=False)

    # --- Identity (from CSTNode via event projection) ---
    node_id: str
    node_type: str  # "function", "class", "method", "file", "section", "table"
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    source_code: str
    source_hash: str

    # --- Graph context (from edges table) ---
    parent_id: str | None = None
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)

    # --- Runtime state (from event projections) ---
    status: str = "idle"  # "idle", "running", "error", "pending_approval"
    last_trigger_event: str = ""
    last_completed_at: float | None = None

    # --- Specialization (from extension config matching) ---
    extension_name: str | None = None
    custom_system_prompt: str = ""
    mounted_workspaces: list[str] = Field(default_factory=list)
    extra_tools: list[ToolSchema] = Field(default_factory=list)
    extra_subscriptions: list[SubscriptionPattern] = Field(default_factory=list)
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/unit/test_agent_node.py::TestAgentNodeCreation -v`
Expected: PASS

### Step 5: Commit

```bash
git add src/remora/core/agent_node.py tests/unit/test_agent_node.py
git commit -m "feat: add AgentNode model with basic creation tests"
```

---

## Task 2: AgentNode Serialization Round-Trip (to_row / from_row)

**Files:**
- Modify: `src/remora/core/agent_node.py`
- Modify: `tests/unit/test_agent_node.py`

### Step 1: Write the failing test

Append to `tests/unit/test_agent_node.py`:

```python
class TestAgentNodeSerialization:
    def test_to_row_basic(self):
        node = _make_node()
        row = node.to_row()
        assert row["node_id"] == "abc123def456"
        assert row["caller_ids"] == "[]"
        assert row["callee_ids"] == "[]"
        assert row["extra_tools"] == "[]"
        assert row["extra_subscriptions"] == "[]"
        assert row["mounted_workspaces"] == "[]"

    def test_to_row_with_json_fields(self):
        from remora.core.subscriptions import SubscriptionPattern

        tool = ToolSchema(
            name="run_test",
            description="Run test",
            parameters={"type": "object"},
        )
        sub = SubscriptionPattern(event_types=["ContentChangedEvent"])
        node = _make_node(
            caller_ids=["id1", "id2"],
            extra_tools=[tool],
            extra_subscriptions=[sub],
            mounted_workspaces=["/workspace/a"],
        )
        row = node.to_row()
        assert json.loads(row["caller_ids"]) == ["id1", "id2"]
        assert json.loads(row["mounted_workspaces"]) == ["/workspace/a"]
        tools_data = json.loads(row["extra_tools"])
        assert len(tools_data) == 1
        assert tools_data[0]["name"] == "run_test"

    def test_from_row_round_trip(self):
        from remora.core.subscriptions import SubscriptionPattern

        tool = ToolSchema(
            name="run_test",
            description="Run test",
            parameters={"type": "object"},
        )
        sub = SubscriptionPattern(event_types=["ContentChangedEvent"])
        original = _make_node(
            caller_ids=["id1"],
            callee_ids=["id2"],
            extra_tools=[tool],
            extra_subscriptions=[sub],
            mounted_workspaces=["/ws"],
            extension_name="TestAgent",
            custom_system_prompt="You are a test agent.",
            status="running",
            last_trigger_event="ContentChangedEvent",
            last_completed_at=1234567890.0,
        )
        row = original.to_row()

        # Simulate SQLite row (dict with string values for JSON columns)
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" * len(row))
        db.execute(f"CREATE TABLE nodes ({cols})")
        db.execute(f"INSERT INTO nodes VALUES ({placeholders})", list(row.values()))
        sqlite_row = db.execute("SELECT * FROM nodes").fetchone()

        restored = AgentNode.from_row(sqlite_row)
        assert restored.node_id == original.node_id
        assert restored.caller_ids == ["id1"]
        assert restored.callee_ids == ["id2"]
        assert len(restored.extra_tools) == 1
        assert restored.extra_tools[0].name == "run_test"
        assert len(restored.extra_subscriptions) == 1
        assert restored.extra_subscriptions[0].event_types == ["ContentChangedEvent"]
        assert restored.extension_name == "TestAgent"
        assert restored.status == "running"
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/unit/test_agent_node.py::TestAgentNodeSerialization -v`
Expected: FAIL with `AttributeError: 'AgentNode' object has no attribute 'to_row'`

### Step 3: Write minimal implementation

Add these methods to the `AgentNode` class in `src/remora/core/agent_node.py`:

```python
    def to_row(self) -> dict[str, Any]:
        """Serialize to a dict suitable for SQLite INSERT."""
        data = self.model_dump()
        data["caller_ids"] = json.dumps(data["caller_ids"])
        data["callee_ids"] = json.dumps(data["callee_ids"])
        data["extra_tools"] = json.dumps(
            [t.__dict__ if isinstance(t, ToolSchema) else t for t in self.extra_tools]
        )
        data["extra_subscriptions"] = json.dumps(
            [s.__dict__ if hasattr(s, "__dict__") else s for s in self.extra_subscriptions]
        )
        data["mounted_workspaces"] = json.dumps(data["mounted_workspaces"])
        return data

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict) -> AgentNode:
        """Hydrate from a SQLite row."""
        data = dict(row)
        data["caller_ids"] = json.loads(data.get("caller_ids") or "[]")
        data["callee_ids"] = json.loads(data.get("callee_ids") or "[]")
        data["extra_tools"] = [
            ToolSchema(**t) for t in json.loads(data.get("extra_tools") or "[]")
        ]
        data["extra_subscriptions"] = [
            SubscriptionPattern(**s)
            for s in json.loads(data.get("extra_subscriptions") or "[]")
        ]
        data["mounted_workspaces"] = json.loads(data.get("mounted_workspaces") or "[]")
        return cls(**data)
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/unit/test_agent_node.py::TestAgentNodeSerialization -v`
Expected: PASS

### Step 5: Commit

```bash
git add src/remora/core/agent_node.py tests/unit/test_agent_node.py
git commit -m "feat: add AgentNode to_row/from_row serialization"
```

---

## Task 3: AgentNode Conversion Methods (to_system_prompt, LSP methods)

**Files:**
- Modify: `src/remora/core/agent_node.py`
- Modify: `tests/unit/test_agent_node.py`

### Step 1: Write the failing tests

Append to `tests/unit/test_agent_node.py`:

```python
from lsprotocol import types as lsp


class TestAgentNodeToSystemPrompt:
    def test_basic_prompt(self):
        node = _make_node()
        prompt = node.to_system_prompt()
        assert "calculate_total" in prompt
        assert "abc123def456" in prompt
        assert "/src/billing.py" in prompt
        assert "def calculate_total" in prompt

    def test_prompt_with_extension(self):
        node = _make_node(
            extension_name="TestAgent",
            custom_system_prompt="You specialize in testing.",
            mounted_workspaces=["/data/fixtures"],
        )
        prompt = node.to_system_prompt()
        assert "TestAgent" in prompt
        assert "You specialize in testing." in prompt
        assert "/data/fixtures" in prompt

    def test_prompt_with_graph_context(self):
        node = _make_node(
            caller_ids=["caller1", "caller2"],
            callee_ids=["callee1"],
        )
        prompt = node.to_system_prompt()
        assert "caller1" in prompt
        assert "caller2" in prompt
        assert "callee1" in prompt


class TestAgentNodeLSP:
    def test_to_range(self):
        node = _make_node(start_line=10, end_line=25)
        r = node.to_range()
        assert r.start.line == 9  # 0-based
        assert r.end.line == 24

    def test_to_code_lens(self):
        node = _make_node()
        lens = node.to_code_lens()
        assert lens.command.command == "remora.selectAgent"
        assert "abc123def456" in lens.command.arguments[0]

    def test_to_code_lens_status_icons(self):
        for status, icon in [("idle", "\u25cf"), ("running", "\u25b6"), ("error", "\u25cb")]:
            node = _make_node(status=status)
            lens = node.to_code_lens()
            assert icon in lens.command.title

    def test_to_hover(self):
        node = _make_node()
        hover = node.to_hover()
        assert "abc123def456" in hover.contents.value
        assert "calculate_total" in hover.contents.value

    def test_to_hover_with_events(self):
        class FakeEvent:
            event_type = "ContentChangedEvent"
            summary = "file changed"

        node = _make_node()
        hover = node.to_hover(recent_events=[FakeEvent()])
        assert "ContentChangedEvent" in hover.contents.value

    def test_to_code_actions(self):
        node = _make_node()
        actions = node.to_code_actions()
        commands = {a.command.command for a in actions if a.command}
        assert "remora.chat" in commands
        assert "remora.requestRewrite" in commands
        assert "remora.messageNode" in commands

    def test_to_code_actions_with_extra_tools(self):
        tool = ToolSchema(
            name="run_test",
            description="Run this test",
            parameters={"type": "object"},
        )
        node = _make_node(extra_tools=[tool])
        actions = node.to_code_actions()
        tool_commands = [
            a for a in actions
            if a.command and "remora.tool.run_test" in a.command.command
        ]
        assert len(tool_commands) == 1

    def test_to_document_symbol(self):
        node = _make_node()
        sym = node.to_document_symbol()
        assert sym.kind == lsp.SymbolKind.Function
        assert "idle" in sym.name
```

### Step 2: Run tests to verify they fail

Run: `python -m pytest tests/unit/test_agent_node.py::TestAgentNodeToSystemPrompt tests/unit/test_agent_node.py::TestAgentNodeLSP -v`
Expected: FAIL with `AttributeError: 'AgentNode' object has no attribute 'to_system_prompt'`

### Step 3: Write minimal implementation

Add these methods to `AgentNode` in `src/remora/core/agent_node.py`:

```python
    # --- LSP helper ---

    def to_range(self) -> "lsp.Range":
        from lsprotocol import types as lsp
        return lsp.Range(
            start=lsp.Position(line=self.start_line - 1, character=0),
            end=lsp.Position(line=self.end_line - 1, character=0),
        )

    # --- LLM prompt ---

    def to_system_prompt(self) -> str:
        """Generate the LLM system prompt from all fields."""
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
            prompt += "\n# Available Workspaces\n" + "\n".join(
                f"- {w}" for w in self.mounted_workspaces
            ) + "\n"
        return prompt

    # --- LSP conversions ---

    def to_code_lens(self) -> "lsp.CodeLens":
        from lsprotocol import types as lsp
        status_icon = {
            "idle": "\u25cf",
            "running": "\u25b6",
            "pending_approval": "\u23f8",
            "error": "\u25cb",
        }
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

    def to_hover(self, recent_events: list | None = None) -> "lsp.Hover":
        from lsprotocol import types as lsp
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
            contents=lsp.MarkupContent(
                kind=lsp.MarkupKind.Markdown, value="\n".join(lines)
            ),
            range=self.to_range(),
        )

    def to_code_actions(self) -> "list[lsp.CodeAction]":
        from lsprotocol import types as lsp
        actions = [
            lsp.CodeAction(
                title="Chat with this agent",
                kind=lsp.CodeActionKind.Empty,
                command=lsp.Command(
                    title="Chat",
                    command="remora.chat",
                    arguments=[self.node_id],
                ),
            ),
            lsp.CodeAction(
                title="Ask agent to rewrite itself",
                kind=lsp.CodeActionKind.RefactorRewrite,
                command=lsp.Command(
                    title="Rewrite",
                    command="remora.requestRewrite",
                    arguments=[self.node_id],
                ),
            ),
            lsp.CodeAction(
                title="Message another agent",
                kind=lsp.CodeActionKind.Empty,
                command=lsp.Command(
                    title="Message",
                    command="remora.messageNode",
                    arguments=[self.node_id],
                ),
            ),
        ]
        for tool in self.extra_tools:
            actions.append(tool.to_code_action(self.node_id))
        return actions

    def to_document_symbol(self) -> "lsp.DocumentSymbol":
        from lsprotocol import types as lsp
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

Also add `to_code_action` to `ToolSchema`:

```python
@dataclass
class ToolSchema:
    # ... existing fields ...

    def to_code_action(self, node_id: str) -> "lsp.CodeAction":
        from lsprotocol import types as lsp
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

### Step 4: Run tests to verify they pass

Run: `python -m pytest tests/unit/test_agent_node.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add src/remora/core/agent_node.py tests/unit/test_agent_node.py
git commit -m "feat: add AgentNode conversion methods (prompt, LSP)"
```

---

## Task 4: Create AgentExtension Base Class and Loader

**Files:**
- Create: `src/remora/extensions.py`
- Test: `tests/unit/test_extensions.py`

### Step 1: Write the failing test

```python
# tests/unit/test_extensions.py
"""Tests for AgentExtension base class and loader."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from remora.extensions import AgentExtension, load_extensions


class TestAgentExtensionBase:
    def test_base_matches_returns_false(self):
        assert AgentExtension.matches("function", "foo") is False

    def test_base_get_extension_data_returns_empty(self):
        data = AgentExtension.get_extension_data()
        assert data == {}


class TestLoadExtensions:
    def test_load_from_empty_dir(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        exts = load_extensions(models_dir)
        assert exts == []

    def test_load_from_nonexistent_dir(self, tmp_path: Path):
        exts = load_extensions(tmp_path / "nonexistent")
        assert exts == []

    def test_load_valid_extension(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        ext_file = models_dir / "test_agent.py"
        ext_file.write_text(textwrap.dedent("""\
            from remora.extensions import AgentExtension

            class TestExtension(AgentExtension):
                @staticmethod
                def matches(node_type: str, name: str) -> bool:
                    return node_type == "function" and name.startswith("test_")

                @staticmethod
                def get_extension_data() -> dict:
                    return {
                        "extension_name": "TestAgent",
                        "custom_system_prompt": "You are a test runner.",
                    }
        """))

        exts = load_extensions(models_dir)
        assert len(exts) == 1
        assert exts[0].matches("function", "test_foo") is True
        assert exts[0].matches("function", "calculate") is False
        data = exts[0].get_extension_data()
        assert data["extension_name"] == "TestAgent"

    def test_mtime_caching(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        ext_file = models_dir / "test_agent.py"
        ext_file.write_text(textwrap.dedent("""\
            from remora.extensions import AgentExtension

            class TestExtension(AgentExtension):
                @staticmethod
                def matches(node_type: str, name: str) -> bool:
                    return False

                @staticmethod
                def get_extension_data() -> dict:
                    return {"extension_name": "Test"}
        """))

        exts1 = load_extensions(models_dir)
        exts2 = load_extensions(models_dir)
        # Same objects returned from cache (same list contents)
        assert len(exts1) == len(exts2) == 1

    def test_load_order_alphabetical(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        for name in ["50_generic.py", "00_specific.py"]:
            (models_dir / name).write_text(textwrap.dedent(f"""\
                from remora.extensions import AgentExtension

                class Ext_{name.split('.')[0]}(AgentExtension):
                    @staticmethod
                    def matches(node_type: str, name: str) -> bool:
                        return True

                    @staticmethod
                    def get_extension_data() -> dict:
                        return {{"extension_name": "{name}"}}
            """))

        exts = load_extensions(models_dir)
        assert len(exts) == 2
        # 00_specific should come first (alphabetical by filename)
        assert exts[0].get_extension_data()["extension_name"] == "00_specific.py"
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/unit/test_extensions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'remora.extensions'`

### Step 3: Write minimal implementation

```python
# src/remora/extensions.py
"""AgentExtension base class and config loader.

Extension configs live in `.remora/models/`. They are Python classes
with two static methods: matches() and get_extension_data().
First match wins. File-alphabetical order controls priority.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Type

logger = logging.getLogger(__name__)


class AgentExtension:
    """Base class for agent extension configs.

    Subclass this in `.remora/models/*.py` files. Override:
    - matches(node_type, name) -> bool
    - get_extension_data() -> dict of AgentNode field overrides
    """

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        """Return True if this extension applies to the given node."""
        return False

    @staticmethod
    def get_extension_data() -> dict:
        """Return field overrides for the AgentNode."""
        return {}


# Module-level cache: {dir_path: (mtimes_dict, extensions_list)}
_cache: dict[str, tuple[dict[Path, float], list[Type[AgentExtension]]]] = {}


def load_extensions(models_dir: Path) -> list[Type[AgentExtension]]:
    """Load extension configs from a directory with mtime-based caching.

    Returns extensions sorted by filename (alphabetical).
    First match wins, so developers control priority via naming
    (e.g., 00_specific.py before 50_generic.py).
    """
    global _cache

    if not models_dir.exists():
        return []

    cache_key = str(models_dir)

    # Collect current mtimes
    current_mtimes: dict[Path, float] = {}
    for py_file in sorted(models_dir.glob("*.py")):
        try:
            current_mtimes[py_file] = py_file.stat().st_mtime
        except OSError:
            pass

    # Check cache
    if cache_key in _cache:
        cached_mtimes, cached_extensions = _cache[cache_key]
        if current_mtimes == cached_mtimes and cached_mtimes:
            return cached_extensions

    # Reload
    extensions: list[Type[AgentExtension]] = []

    for py_file in sorted(current_mtimes.keys()):
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for obj in module.__dict__.values():
                if (
                    isinstance(obj, type)
                    and issubclass(obj, AgentExtension)
                    and obj is not AgentExtension
                ):
                    extensions.append(obj)
        except Exception as e:
            logger.warning("Failed to load extension from %s: %s", py_file, e)
            continue

    _cache[cache_key] = (current_mtimes, extensions)
    return extensions
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/unit/test_extensions.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add src/remora/extensions.py tests/unit/test_extensions.py
git commit -m "feat: add AgentExtension base class and loader"
```

---

## Task 5: Add NodeDiscoveredEvent and NodeRemovedEvent

**Files:**
- Modify: `src/remora/core/events.py`
- Test: `tests/unit/test_node_events.py`

### Step 1: Write the failing test

```python
# tests/unit/test_node_events.py
"""Tests for node lifecycle events."""
from __future__ import annotations

import time

from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent


class TestNodeDiscoveredEvent:
    def test_create(self):
        event = NodeDiscoveredEvent(
            node_id="abc123",
            node_type="function",
            name="calculate_total",
            full_name="function:calculate_total",
            file_path="/src/billing.py",
            start_line=10,
            end_line=25,
            source_code="def calculate_total(): pass",
            source_hash="aabb",
        )
        assert event.node_id == "abc123"
        assert event.node_type == "function"
        assert event.parent_id is None
        assert event.timestamp > 0

    def test_frozen(self):
        import pytest

        event = NodeDiscoveredEvent(
            node_id="abc123",
            node_type="function",
            name="test",
            full_name="function:test",
            file_path="/test.py",
            start_line=1,
            end_line=5,
            source_code="",
            source_hash="",
        )
        with pytest.raises(AttributeError):
            event.node_id = "changed"


class TestNodeRemovedEvent:
    def test_create(self):
        event = NodeRemovedEvent(node_id="abc123")
        assert event.node_id == "abc123"
        assert event.timestamp > 0
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/unit/test_node_events.py -v`
Expected: FAIL with `ImportError: cannot import name 'NodeDiscoveredEvent'`

### Step 3: Write minimal implementation

Add to `src/remora/core/events.py`, after the `ManualTriggerEvent` class (before the Union Type section):

```python
# ============================================================================
# Node Lifecycle Events (for EventLog projection -> nodes table)
# ============================================================================


@dataclass(frozen=True, slots=True)
class NodeDiscoveredEvent:
    """Emitted when a code node is discovered or re-discovered."""

    node_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    source_code: str
    source_hash: str
    parent_id: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class NodeRemovedEvent:
    """Emitted when a code node is no longer found in source."""

    node_id: str
    timestamp: float = field(default_factory=time.time)
```

Also update the `RemoraEvent` union type:

```python
RemoraEvent = (
    # Agent events
    AgentStartEvent
    | AgentCompleteEvent
    | AgentErrorEvent
    |
    # Human-in-the-loop events
    HumanInputRequestEvent
    | HumanInputResponseEvent
    |
    # Reactive swarm events
    AgentMessageEvent
    | FileSavedEvent
    | ContentChangedEvent
    | ManualTriggerEvent
    |
    # Node lifecycle events
    NodeDiscoveredEvent
    | NodeRemovedEvent
    |
    # Re-exported structured-agents events
    KernelStartEvent
    | KernelEndEvent
    | ToolCallEvent
    | ToolResultEvent
    | ModelRequestEvent
    | ModelResponseEvent
    | TurnCompleteEvent
)
```

And update `__all__` to include:
```python
    "NodeDiscoveredEvent",
    "NodeRemovedEvent",
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/unit/test_node_events.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add src/remora/core/events.py tests/unit/test_node_events.py
git commit -m "feat: add NodeDiscoveredEvent and NodeRemovedEvent"
```

---

## Task 6: Add `nodes` Table to EventStore

**Files:**
- Modify: `src/remora/core/event_store.py:52-92` (the `initialize` method)
- Test: `tests/unit/test_nodes_table.py`

### Step 1: Write the failing test

```python
# tests/unit/test_nodes_table.py
"""Tests for the nodes table in EventStore."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from remora.core.event_store import EventStore


@pytest.fixture
async def store(tmp_path: Path):
    s = EventStore(tmp_path / "test.db")
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_nodes_table_exists(store: EventStore):
    """The nodes table should be created during initialization."""
    conn = store._conn
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nodes'"
    )
    assert cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_nodes_table_schema(store: EventStore):
    """The nodes table should have all required columns."""
    conn = store._conn
    cursor = conn.execute("PRAGMA table_info(nodes)")
    columns = {row[1] for row in cursor.fetchall()}
    expected = {
        "node_id", "node_type", "name", "full_name", "file_path",
        "start_line", "end_line", "source_code", "source_hash",
        "parent_id", "caller_ids", "callee_ids",
        "status", "last_trigger_event", "last_completed_at",
        "extension_name", "custom_system_prompt",
        "mounted_workspaces", "extra_tools", "extra_subscriptions",
    }
    assert expected.issubset(columns)


@pytest.mark.asyncio
async def test_nodes_table_indexes(store: EventStore):
    """The nodes table should have required indexes."""
    conn = store._conn
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_nodes_file_path" in indexes
    assert "idx_nodes_parent_id" in indexes
    assert "idx_nodes_node_type" in indexes
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/unit/test_nodes_table.py -v`
Expected: FAIL (table "nodes" doesn't exist yet)

### Step 3: Write minimal implementation

In `src/remora/core/event_store.py`, modify the `initialize` method. After the existing `executescript` call that creates the `events` table (around line 92, before `await self._migrate_routing_fields()`), add:

```python
            await asyncio.to_thread(
                self._conn.executescript,
                """
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
                """,
            )
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/unit/test_nodes_table.py -v`
Expected: ALL PASS

### Step 5: Run existing EventStore tests to check for regressions

Run: `python -m pytest tests/unit/test_event_store.py -v`
Expected: ALL PASS

### Step 6: Commit

```bash
git add src/remora/core/event_store.py tests/unit/test_nodes_table.py
git commit -m "feat: add nodes table to EventStore schema"
```

---

## Task 7: Write Node Projection Logic

**Files:**
- Create: `src/remora/core/projections.py`
- Test: `tests/unit/test_projections.py`

The projection processes events and writes to the `nodes` table.

### Step 1: Write the failing test

```python
# tests/unit/test_projections.py
"""Tests for EventLog -> nodes table projection."""
from __future__ import annotations

import json
import sqlite3
import textwrap
from pathlib import Path

import pytest

from remora.core.agent_node import AgentNode
from remora.core.event_store import EventStore
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
)
from remora.core.projections import NodeProjection
from remora.extensions import AgentExtension, load_extensions


@pytest.fixture
async def store(tmp_path: Path):
    s = EventStore(tmp_path / "test.db")
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def projection():
    return NodeProjection(extension_configs=[])


def _discovered_event(**overrides) -> NodeDiscoveredEvent:
    defaults = {
        "node_id": "abc123",
        "node_type": "function",
        "name": "calculate_total",
        "full_name": "function:calculate_total",
        "file_path": "/src/billing.py",
        "start_line": 10,
        "end_line": 25,
        "source_code": "def calculate_total(): pass",
        "source_hash": "aabb",
    }
    defaults.update(overrides)
    return NodeDiscoveredEvent(**defaults)


class TestProjectNodeDiscovered:
    @pytest.mark.asyncio
    async def test_insert_new_node(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event()
        projection.apply(store._conn, event)

        row = store._conn.execute(
            "SELECT * FROM nodes WHERE node_id = ?", ("abc123",)
        ).fetchone()
        assert row is not None
        assert row["name"] == "calculate_total"
        assert row["status"] == "idle"

    @pytest.mark.asyncio
    async def test_upsert_existing_node(self, store: EventStore, projection: NodeProjection):
        event1 = _discovered_event(source_hash="v1")
        projection.apply(store._conn, event1)

        event2 = _discovered_event(source_hash="v2", source_code="def calculate_total(x): pass")
        projection.apply(store._conn, event2)

        row = store._conn.execute(
            "SELECT * FROM nodes WHERE node_id = ?", ("abc123",)
        ).fetchone()
        assert row["source_hash"] == "v2"

    @pytest.mark.asyncio
    async def test_extension_matching(self, store: EventStore):
        class TestExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str) -> bool:
                return name.startswith("test_")

            @staticmethod
            def get_extension_data() -> dict:
                return {
                    "extension_name": "TestAgent",
                    "custom_system_prompt": "You run tests.",
                }

        proj = NodeProjection(extension_configs=[TestExt])
        event = _discovered_event(name="test_foo", full_name="function:test_foo")
        proj.apply(store._conn, event)

        row = store._conn.execute(
            "SELECT * FROM nodes WHERE node_id = ?", ("abc123",)
        ).fetchone()
        assert row["extension_name"] == "TestAgent"
        assert row["custom_system_prompt"] == "You run tests."

    @pytest.mark.asyncio
    async def test_no_extension_match(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event()
        projection.apply(store._conn, event)

        row = store._conn.execute(
            "SELECT * FROM nodes WHERE node_id = ?", ("abc123",)
        ).fetchone()
        assert row["extension_name"] is None

    @pytest.mark.asyncio
    async def test_hydrate_from_projection(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event()
        projection.apply(store._conn, event)

        row = store._conn.execute(
            "SELECT * FROM nodes WHERE node_id = ?", ("abc123",)
        ).fetchone()
        node = AgentNode.from_row(row)
        assert node.node_id == "abc123"
        assert node.name == "calculate_total"


class TestProjectStatusUpdates:
    @pytest.mark.asyncio
    async def test_agent_start_sets_running(self, store: EventStore, projection: NodeProjection):
        projection.apply(store._conn, _discovered_event())

        start = AgentStartEvent(
            graph_id="swarm", agent_id="abc123", node_name="calculate_total"
        )
        projection.apply(store._conn, start)

        row = store._conn.execute(
            "SELECT status FROM nodes WHERE node_id = ?", ("abc123",)
        ).fetchone()
        assert row["status"] == "running"

    @pytest.mark.asyncio
    async def test_agent_complete_sets_idle(self, store: EventStore, projection: NodeProjection):
        projection.apply(store._conn, _discovered_event())
        projection.apply(
            store._conn,
            AgentStartEvent(graph_id="s", agent_id="abc123", node_name="x"),
        )
        complete = AgentCompleteEvent(
            graph_id="s", agent_id="abc123", result_summary="done"
        )
        projection.apply(store._conn, complete)

        row = store._conn.execute(
            "SELECT status, last_completed_at FROM nodes WHERE node_id = ?",
            ("abc123",),
        ).fetchone()
        assert row["status"] == "idle"
        assert row["last_completed_at"] is not None

    @pytest.mark.asyncio
    async def test_agent_error_sets_error(self, store: EventStore, projection: NodeProjection):
        projection.apply(store._conn, _discovered_event())
        error = AgentErrorEvent(
            graph_id="s", agent_id="abc123", error="boom"
        )
        projection.apply(store._conn, error)

        row = store._conn.execute(
            "SELECT status FROM nodes WHERE node_id = ?", ("abc123",)
        ).fetchone()
        assert row["status"] == "error"


class TestProjectNodeRemoved:
    @pytest.mark.asyncio
    async def test_remove_deletes_row(self, store: EventStore, projection: NodeProjection):
        projection.apply(store._conn, _discovered_event())
        projection.apply(store._conn, NodeRemovedEvent(node_id="abc123"))

        row = store._conn.execute(
            "SELECT * FROM nodes WHERE node_id = ?", ("abc123",)
        ).fetchone()
        assert row is None
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/unit/test_projections.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'remora.core.projections'`

### Step 3: Write minimal implementation

```python
# src/remora/core/projections.py
"""EventLog projections for materializing read models.

The NodeProjection processes events and maintains the `nodes` table.
"""
from __future__ import annotations

import json
import logging
import sqlite3
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


class NodeProjection:
    """Projects events into the `nodes` table."""

    def __init__(self, extension_configs: list[Type] | None = None):
        self._extension_configs = extension_configs or []

    def apply(self, conn: sqlite3.Connection, event: RemoraEvent) -> None:
        """Apply a single event to the nodes table."""
        event_type = type(event).__name__

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

    def _project_node_discovered(
        self, conn: sqlite3.Connection, event: NodeDiscoveredEvent
    ) -> None:
        row: dict[str, Any] = {
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
                            row[key] = json.dumps(
                                value, default=lambda o: o.__dict__
                            )
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
        conn.commit()

    def _project_node_removed(
        self, conn: sqlite3.Connection, event: NodeRemovedEvent
    ) -> None:
        conn.execute("DELETE FROM nodes WHERE node_id = ?", (event.node_id,))
        conn.commit()

    def _project_agent_start(
        self, conn: sqlite3.Connection, event: AgentStartEvent
    ) -> None:
        conn.execute(
            "UPDATE nodes SET status = 'running' WHERE node_id = ?",
            (event.agent_id,),
        )
        conn.commit()

    def _project_agent_complete(
        self, conn: sqlite3.Connection, event: AgentCompleteEvent
    ) -> None:
        conn.execute(
            "UPDATE nodes SET status = 'idle', last_completed_at = ? WHERE node_id = ?",
            (event.timestamp, event.agent_id),
        )
        conn.commit()

    def _project_agent_error(
        self, conn: sqlite3.Connection, event: AgentErrorEvent
    ) -> None:
        conn.execute(
            "UPDATE nodes SET status = 'error' WHERE node_id = ?",
            (event.agent_id,),
        )
        conn.commit()
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/unit/test_projections.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add src/remora/core/projections.py tests/unit/test_projections.py
git commit -m "feat: add NodeProjection for EventLog -> nodes table"
```

---

## Task 8: Wire Projection into EventStore.append()

**Files:**
- Modify: `src/remora/core/event_store.py`
- Test: `tests/unit/test_event_store_projection.py`

This wires the projection so that when events are appended, the nodes table is automatically updated.

### Step 1: Write the failing test

```python
# tests/unit/test_event_store_projection.py
"""Test that EventStore.append() triggers node projection."""
from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.agent_node import AgentNode
from remora.core.event_store import EventStore
from remora.core.events import (
    AgentCompleteEvent,
    AgentStartEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
)
from remora.core.projections import NodeProjection


@pytest.fixture
async def store_with_projection(tmp_path: Path):
    projection = NodeProjection(extension_configs=[])
    s = EventStore(tmp_path / "test.db", projection=projection)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_append_node_discovered_projects_to_table(store_with_projection: EventStore):
    event = NodeDiscoveredEvent(
        node_id="abc123",
        node_type="function",
        name="foo",
        full_name="function:foo",
        file_path="/test.py",
        start_line=1,
        end_line=5,
        source_code="def foo(): pass",
        source_hash="hash1",
    )
    await store_with_projection.append("swarm", event)

    row = store_with_projection._conn.execute(
        "SELECT * FROM nodes WHERE node_id = ?", ("abc123",)
    ).fetchone()
    assert row is not None
    assert row["name"] == "foo"


@pytest.mark.asyncio
async def test_append_status_events_update_nodes(store_with_projection: EventStore):
    # First create the node
    await store_with_projection.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="abc123",
            node_type="function",
            name="foo",
            full_name="function:foo",
            file_path="/test.py",
            start_line=1,
            end_line=5,
            source_code="",
            source_hash="",
        ),
    )

    # Start the agent
    await store_with_projection.append(
        "swarm",
        AgentStartEvent(graph_id="s", agent_id="abc123", node_name="foo"),
    )
    row = store_with_projection._conn.execute(
        "SELECT status FROM nodes WHERE node_id = ?", ("abc123",)
    ).fetchone()
    assert row["status"] == "running"

    # Complete it
    await store_with_projection.append(
        "swarm",
        AgentCompleteEvent(graph_id="s", agent_id="abc123", result_summary="done"),
    )
    row = store_with_projection._conn.execute(
        "SELECT status FROM nodes WHERE node_id = ?", ("abc123",)
    ).fetchone()
    assert row["status"] == "idle"


@pytest.mark.asyncio
async def test_append_node_removed_deletes_from_table(store_with_projection: EventStore):
    await store_with_projection.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="abc123",
            node_type="function",
            name="foo",
            full_name="function:foo",
            file_path="/test.py",
            start_line=1,
            end_line=5,
            source_code="",
            source_hash="",
        ),
    )
    await store_with_projection.append("swarm", NodeRemovedEvent(node_id="abc123"))

    row = store_with_projection._conn.execute(
        "SELECT * FROM nodes WHERE node_id = ?", ("abc123",)
    ).fetchone()
    assert row is None
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/unit/test_event_store_projection.py -v`
Expected: FAIL (EventStore constructor doesn't accept `projection` parameter)

### Step 3: Write minimal implementation

Modify `src/remora/core/event_store.py`:

1. Add `projection` parameter to `__init__`:

In the `__init__` method signature (line 28-33), add `projection` parameter:

```python
    def __init__(
        self,
        db_path: PathLike,
        subscriptions: "SubscriptionRegistry | None" = None,
        event_bus: "EventBus | None" = None,
        projection: "NodeProjection | None" = None,
    ):
```

And store it:
```python
        self._projection = projection
```

Add at top of file:
```python
if TYPE_CHECKING:
    from remora.core.event_bus import EventBus
    from remora.core.projections import NodeProjection
    from remora.core.subscriptions import SubscriptionRegistry
```

2. In the `append` method (around line 175, after `await asyncio.to_thread(self._conn.commit)`), add projection call:

```python
        # Apply projection (synchronous, same connection)
        if self._projection is not None and self._conn is not None:
            self._projection.apply(self._conn, event)
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/unit/test_event_store_projection.py -v`
Expected: ALL PASS

### Step 5: Run existing tests for regression

Run: `python -m pytest tests/unit/test_event_store.py -v`
Expected: ALL PASS

### Step 6: Commit

```bash
git add src/remora/core/event_store.py tests/unit/test_event_store_projection.py
git commit -m "feat: wire NodeProjection into EventStore.append()"
```

---

## Task 9: Add AgentNode Query Methods to EventStore

**Files:**
- Modify: `src/remora/core/event_store.py`
- Test: `tests/unit/test_event_store_nodes_query.py`

Convenience methods to read AgentNodes from the nodes table.

### Step 1: Write the failing test

```python
# tests/unit/test_event_store_nodes_query.py
"""Tests for AgentNode query methods on EventStore."""
from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.agent_node import AgentNode
from remora.core.event_store import EventStore
from remora.core.events import NodeDiscoveredEvent
from remora.core.projections import NodeProjection


@pytest.fixture
async def store(tmp_path: Path):
    s = EventStore(tmp_path / "test.db", projection=NodeProjection())
    await s.initialize()

    # Seed two nodes
    for name, ntype in [("foo", "function"), ("Bar", "class")]:
        await s.append(
            "swarm",
            NodeDiscoveredEvent(
                node_id=f"id_{name}",
                node_type=ntype,
                name=name,
                full_name=f"{ntype}:{name}",
                file_path="/test.py",
                start_line=1,
                end_line=5,
                source_code=f"def {name}(): pass",
                source_hash=f"hash_{name}",
            ),
        )

    yield s
    await s.close()


@pytest.mark.asyncio
async def test_get_node(store: EventStore):
    node = await store.get_node("id_foo")
    assert node is not None
    assert node.name == "foo"
    assert isinstance(node, AgentNode)


@pytest.mark.asyncio
async def test_get_node_not_found(store: EventStore):
    node = await store.get_node("nonexistent")
    assert node is None


@pytest.mark.asyncio
async def test_list_nodes(store: EventStore):
    nodes = await store.list_nodes()
    assert len(nodes) == 2


@pytest.mark.asyncio
async def test_list_nodes_by_file(store: EventStore):
    nodes = await store.list_nodes(file_path="/test.py")
    assert len(nodes) == 2


@pytest.mark.asyncio
async def test_list_nodes_by_type(store: EventStore):
    nodes = await store.list_nodes(node_type="class")
    assert len(nodes) == 1
    assert nodes[0].name == "Bar"
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/unit/test_event_store_nodes_query.py -v`
Expected: FAIL with `AttributeError: 'EventStore' object has no attribute 'get_node'`

### Step 3: Write minimal implementation

Add these methods to `EventStore` in `src/remora/core/event_store.py`:

```python
    async def get_node(self, node_id: str) -> "AgentNode | None":
        """Get a single AgentNode by ID."""
        from remora.core.agent_node import AgentNode

        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        def _fetch(conn):
            cursor = conn.execute(
                "SELECT * FROM nodes WHERE node_id = ?", (node_id,)
            )
            return cursor.fetchone()

        row = await asyncio.to_thread(_fetch, self._conn)
        if row is None:
            return None
        return AgentNode.from_row(row)

    async def list_nodes(
        self,
        *,
        file_path: str | None = None,
        node_type: str | None = None,
    ) -> "list[AgentNode]":
        """List AgentNodes with optional filters."""
        from remora.core.agent_node import AgentNode

        if self._conn is None:
            await self.initialize()
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        query = "SELECT * FROM nodes"
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

        def _fetch(conn):
            cursor = conn.execute(query, params)
            return cursor.fetchall()

        rows = await asyncio.to_thread(_fetch, self._conn)
        return [AgentNode.from_row(row) for row in rows]
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/unit/test_event_store_nodes_query.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add src/remora/core/event_store.py tests/unit/test_event_store_nodes_query.py
git commit -m "feat: add get_node/list_nodes query methods to EventStore"
```

---

## Task 10: Update core/__init__.py Exports

**Files:**
- Modify: `src/remora/core/__init__.py`

### Step 1: Update imports and __all__

Add these imports:
```python
from remora.core.agent_node import AgentNode, ToolSchema as AgentToolSchema
from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent
from remora.core.projections import NodeProjection
```

Add to `__all__`:
```python
    "AgentNode",
    "AgentToolSchema",
    "NodeDiscoveredEvent",
    "NodeProjection",
    "NodeRemovedEvent",
```

### Step 2: Run existing tests

Run: `python -m pytest tests/unit/ -v --timeout=30`
Expected: ALL PASS

### Step 3: Commit

```bash
git add src/remora/core/__init__.py
git commit -m "feat: export AgentNode and related types from core"
```

---

## Task 11: Integration Test - Full Pipeline

**Files:**
- Create: `tests/integration/test_agent_node_pipeline.py`

This tests the full flow: emit NodeDiscoveredEvent -> projection creates row -> hydrate AgentNode -> verify all fields.

### Step 1: Write the test

```python
# tests/integration/test_agent_node_pipeline.py
"""Integration test: full EventLog -> nodes table -> AgentNode pipeline."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from remora.core.agent_node import AgentNode
from remora.core.event_store import EventStore
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
)
from remora.core.projections import NodeProjection
from remora.extensions import AgentExtension


class _TestExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return name.startswith("test_")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "TestAgent",
            "custom_system_prompt": "You are a test runner.",
        }


@pytest.fixture
async def store(tmp_path: Path):
    proj = NodeProjection(extension_configs=[_TestExtension])
    s = EventStore(tmp_path / "test.db", projection=proj)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_full_lifecycle(store: EventStore):
    # 1. Discover a test function
    await store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="node_test_foo",
            node_type="function",
            name="test_foo",
            full_name="function:test_foo",
            file_path="/tests/test_billing.py",
            start_line=10,
            end_line=20,
            source_code="def test_foo(): assert True",
            source_hash="hash1",
        ),
    )

    # Verify extension was matched
    node = await store.get_node("node_test_foo")
    assert node is not None
    assert node.extension_name == "TestAgent"
    assert node.custom_system_prompt == "You are a test runner."
    assert node.status == "idle"

    # 2. Start the agent
    await store.append(
        "swarm",
        AgentStartEvent(graph_id="s", agent_id="node_test_foo", node_name="test_foo"),
    )
    node = await store.get_node("node_test_foo")
    assert node.status == "running"

    # 3. Complete the agent
    await store.append(
        "swarm",
        AgentCompleteEvent(graph_id="s", agent_id="node_test_foo", result_summary="done"),
    )
    node = await store.get_node("node_test_foo")
    assert node.status == "idle"
    assert node.last_completed_at is not None

    # 4. Verify prompt generation
    prompt = node.to_system_prompt()
    assert "test_foo" in prompt
    assert "TestAgent" in prompt

    # 5. Verify LSP output
    lens = node.to_code_lens()
    assert lens.command.command == "remora.selectAgent"

    # 6. Remove the node
    await store.append("swarm", NodeRemovedEvent(node_id="node_test_foo"))
    node = await store.get_node("node_test_foo")
    assert node is None


@pytest.mark.asyncio
async def test_re_discovery_preserves_status(store: EventStore):
    """Re-discovering a node should update source but preserve runtime status."""
    await store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="node_1",
            node_type="function",
            name="calc",
            full_name="function:calc",
            file_path="/src/a.py",
            start_line=1,
            end_line=5,
            source_code="v1",
            source_hash="h1",
        ),
    )
    await store.append(
        "swarm",
        AgentStartEvent(graph_id="s", agent_id="node_1", node_name="calc"),
    )

    # Re-discover with new source
    await store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="node_1",
            node_type="function",
            name="calc",
            full_name="function:calc",
            file_path="/src/a.py",
            start_line=1,
            end_line=8,
            source_code="v2",
            source_hash="h2",
        ),
    )

    node = await store.get_node("node_1")
    assert node.source_hash == "h2"
    assert node.end_line == 8
    # Status preserved from before re-discovery (projection upsert preserves status)
    assert node.status == "running"
```

### Step 2: Run the test

Run: `python -m pytest tests/integration/test_agent_node_pipeline.py -v`
Expected: ALL PASS

### Step 3: Commit

```bash
git add tests/integration/test_agent_node_pipeline.py
git commit -m "test: add AgentNode full pipeline integration test"
```

---

## What Comes Next (Phase 2 - Migration)

Tasks 12+ will migrate existing consumers to use AgentNode. These are planned but should be done in a separate session after Phase 1 is verified:

### Task 12: Update reconciler.py to emit NodeDiscoveredEvent
- Replace `AgentState` creation + JSONL save + `SwarmState.upsert()` with emitting `NodeDiscoveredEvent`
- Replace `swarm_state.mark_orphaned()` with emitting `NodeRemovedEvent`
- Remove `AgentMetadata` usage

### Task 13: Update agent_runner.py to load from nodes table
- Replace `load_agent_state()` from JSONL with `event_store.get_node()`
- `ExecutionContext.state` changes type from `AgentState` to `AgentNode`

### Task 14: Update swarm_executor.py to use AgentNode
- `run_agent()` accepts `AgentNode` instead of `AgentState`
- Use `agent.to_system_prompt()` instead of manual prompt building
- Remove `_state_to_cst_node()` helper
- Use `agent.extra_tools` for tool discovery

### Task 15: Update LSP handlers to use AgentNode
- Replace `ASTAgentNode` with `AgentNode` in `server.py` and handler modules
- Use `AgentNode.from_row()` instead of `ASTAgentNode.from_agent_state()`
- All handler code already exists in AgentNode methods

### Task 16: Remove deprecated files
- Delete `src/remora/core/agent_state.py`
- Delete `src/remora/lsp/extensions.py` (replaced by `src/remora/extensions.py`)
- Remove `ASTAgentNode` from `src/remora/lsp/models.py` (keep `RewriteProposal`, event wrappers)
- Remove `AgentMetadata` and simplify or remove `src/remora/core/swarm_state.py`
- Update all `__init__.py` and `__all__` exports

### Task 17: Final regression test pass
- Run full test suite: `python -m pytest tests/ -v`
- Fix any remaining references to old types
