# EVENT_BASED_DEMO_PLAN.md — Detailed MVP Demo Implementation Plan

> **Goal:** A fully specified, implementable plan for demonstrating the EventBased architecture to one person running locally. Neovim on the left, graph viewer in the browser on the right, same EventLog driving both.

---

## Table of Contents

### 1. Demo Overview and Success Criteria
What the demo must accomplish visually and architecturally. The "golden path" scenario scripted beat-by-beat. Definition of done.

### 2. Demo Project: `configlib`
The sample Python project used for the demo. Full file listing with source code. Extension configs in `.remora/models/`. `remora.yaml` configuration. Why this project structure demonstrates the architecture well.

### 3. Prerequisites and Migration Scope
Which tasks from the Option A migration plan are required for the demo vs. deferred. Minimum viable migration. What can stay on RemoraDB for now.

### 4. Enhanced MockLLMClient
Scripted responses for the golden path demo flow. Pattern-matching dispatch (trigger type + agent context -> canned response). Tool call generation (message_node, rewrite_self). Fallback to real LLM when `REMORA_LLM_URL` is set.

### 5. Graph Viewer Architecture
Module structure (`remora_demo/graph/`). Tech stack: Stario + Relay + Datastar (server-rendered everything). Process model (separate from LSP server, shared SQLite, internal Relay for SSE). Server-side graph layout. Entry point and CLI.

### 6. Graph Viewer: Server Implementation
Stario app with routes. Handlers using `w.patch()`, `w.alive()`, and Relay subscriptions. DB polling bridge that publishes changes to in-process Relay. View functions for graph, sidebar, event stream. Command queue write endpoint for web->LSP interaction.

### 7. Graph Viewer: Client Implementation
Server-rendered SVG graph with CSS transitions for smooth animation. No client-side JS framework — Datastar handles all DOM updates. Dark theme CSS. Node status colors, cursor highlight, activation pulse — all CSS. Datastar signals for UI state (selected node, sidebar tab).

### 8. Graph Viewer: Sidebar and Interaction
Agent detail panel (click node -> show info, subscriptions, recent events). Global event stream (scrolling log). Per-agent chat input -> command_queue -> LSP. Proposal display with approve/reject buttons. Subscription inspector view.

### 9. Cursor Tracking Integration
End-to-end flow: Neovim CursorHold -> LSP notification -> cursor_focus table -> SSE -> graph highlight + viewport pan. Debouncing. Smooth animation on the client.

### 10. LSP Server Modifications
Changes needed to `server.py`, `notifications.py` for graph viewer support. Ensuring `emit_event` bridges all relevant events to the shared DB. Command queue polling loop in the runner.

### 11. Demo Entry Points and Launcher
`remora_demo/__main__.py` updates. `remora_demo/graph/__main__.py` for the web server. Optional unified launcher script that starts both. Port configuration. DB path resolution.

### 12. Demo Script: The Golden Path
Step-by-step script for running the demo. Terminal layout. Exact commands. What to say/show at each step. Expected visual output at each beat.

### 13. File Manifest
Every file that needs to be created or modified, with a brief description of changes.

### 14. Implementation Order
Task dependency graph. Which tasks can be parallelized (by a human, not subagents). Estimated effort per task. Critical path.

---

## 1. Demo Overview and Success Criteria

### What The Demo Is

Two windows, side by side. Left: Neovim with the remora LSP plugin. Right: a browser tab with a force-directed graph viewer. Both are driven by the same SQLite database (the EventLog + projected tables). The developer edits code in Neovim; agents wake up, think, communicate, propose changes. The graph viewer makes all of this visible in real-time.

### The Golden Path (Beat by Beat)

| Beat | Neovim | Graph Viewer | Architecture |
|------|--------|-------------|--------------|
| 1. Launch | `nv2` opens. Remora LSP starts. | `python -m remora_demo.graph` opens `localhost:8420`. Empty graph. | LSP server creates/opens `.remora/indexer.db`. Graph viewer connects to same DB. |
| 2. Open files | Open `src/configlib/loader.py`. Code lenses appear above `load_config()`, `detect_format()`, `load_yaml()`. | Three function nodes + one file node appear, drift into position via d3-force. | `did_open` -> ASTWatcher parse -> NodeDiscoveredEvent -> projection -> nodes table -> SSE push to graph. |
| 3. More files | Open `schema.py`, `merge.py`, `test_loader.py`. More lenses. | Graph grows. Edges form (calls, parent_of, tests). Layout settles. | Same flow. LazyGraph builds edges. Graph viewer polls for new nodes/edges. |
| 4. Navigate | Cursor moves to `load_config()`. | That node gets a bright highlight ring. Viewport smoothly pans to center it. | CursorHold -> `$/remora/cursorMoved` -> `cursor_focus` table -> SSE -> client highlight. |
| 5. Chat | `:RemoraChat "what do you do?"` | Event stream shows HumanChatEvent, then AgentMessageEvent with response. Selected node briefly pulses. | HumanChatEvent -> EventLog -> runner triggers agent -> MockLLM responds -> AgentMessageEvent -> EventLog. |
| 6. Edit | Add `timeout: int = 30` parameter to `load_config()`. Save. | `load_config` node turns green (running). Pulse animation. | FileSavedEvent + ContentChangedEvent -> EventLog -> subscription match -> agent triggered. |
| 7. Agent thinks | Code lens: `▶ rm_... running`. Panel shows "Analyzing change..." | Running node pulses. ModelRequest/ModelResponse events scroll in event stream. | AgentStartEvent -> kernel turn -> ModelRequestEvent -> MockLLM -> ModelResponseEvent. |
| 8. Cascade | Agent calls `message_node` to `test_load_yaml`. Test agent's code lens changes to running. | Edge between `load_config` and `test_load_yaml` glows briefly. Test node turns green. | AgentMessageEvent -> subscription match -> test agent triggered -> second chain link. |
| 9. Proposal | Diagnostic squiggle appears on `test_load_yaml`. Panel shows proposed diff. | Test node turns amber (pending_approval). Sidebar shows the proposal with diff. | RewriteProposalEvent -> proposal stored -> diagnostic published -> status update. |
| 10. Approve | `:RemoraAccept`. Buffer updates. Diagnostic clears. | Node returns to idle (grey). Event stream shows RewriteAppliedEvent. | workspace/applyEdit -> RewriteAppliedEvent -> projection updates status. |
| 11. Reflect | Open panel, scroll through event history for `load_config`. | Click "Event Log" tab. See the full chain: ContentChanged -> AgentStart -> ... -> RewriteApplied. | All events in the EventLog, queryable and auditable. |

### Success Criteria

1. **Functional:** All 11 beats above work end-to-end without errors.
2. **Visual:** Graph viewer renders 15-25 nodes with smooth d3-force physics. Status colors update within 500ms. Cursor tracking highlight updates within 300ms.
3. **Architectural:** Events flow through the EventLog. The `nodes` table is updated by projection. Both Neovim and the graph viewer read from the same source.
4. **Reproducible:** Works on a fresh clone with `devenv shell` (or `uv pip install -e ".[dev]"`). No external services required (mock LLM). Optional real LLM via env var.
5. **Impressive:** A developer watching the demo should understand that agents are autonomous, reactive, and interconnected — not scripted bots.

### Non-Goals (for MVP)

- Multi-user support.
- Production-grade error handling.
- Real LLM as a requirement (mock is default).
- Mobile/responsive web design.
- Persistent graph layout across restarts.
- Full Option A migration (only what's needed for the demo path).

---

## 2. Demo Project: `configlib`

### Why This Project

The demo needs a Python project that is:
- Small enough to understand in 30 seconds (5-6 source files, ~150 lines total).
- Has natural graph structure: files contain functions, functions call functions, test functions test source functions.
- Has enough variety to demonstrate extensions: test functions get the `TestFunction` extension, `__init__.py` gets a `PackageInit` extension.
- References the concept doc's own example (Section 6 uses a config library).

### Directory Structure

```
remora_demo/project/
    remora.yaml                     # Remora configuration
    .remora/
        models/
            test_function.py        # TestFunction extension config
            package_init.py         # PackageInit extension config
    src/
        configlib/
            __init__.py             # Package exports
            loader.py               # load_config(), detect_format(), load_yaml()
            schema.py               # validate(), SchemaError class
            merge.py                # deep_merge(), merge_dicts()
    tests/
        test_loader.py              # test_load_yaml(), test_load_json(), test_detect_format()
        test_merge.py               # test_deep_merge(), test_merge_override()
```

### Source Files

#### `src/configlib/__init__.py`

```python
"""configlib - Configuration file handling library."""

from configlib.loader import load_config, detect_format
from configlib.schema import validate, SchemaError
from configlib.merge import deep_merge

__all__ = ["load_config", "detect_format", "validate", "SchemaError", "deep_merge"]
```

#### `src/configlib/loader.py`

```python
"""Configuration file loading utilities."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from configlib.schema import validate


def load_config(path: str | Path) -> dict[str, Any]:
    """Load and parse a configuration file."""
    path = Path(path)
    fmt = detect_format(path)
    raw = path.read_text(encoding="utf-8")

    if fmt == "json":
        data = json.loads(raw)
    elif fmt == "yaml":
        data = load_yaml(raw)
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    validate(data)
    return data


def detect_format(path: str | Path) -> str:
    """Detect config file format from extension."""
    suffix = Path(path).suffix.lower()
    mapping = {".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml"}
    fmt = mapping.get(suffix)
    if fmt is None:
        raise ValueError(f"Unknown config format: {suffix}")
    return fmt


def load_yaml(raw: str) -> dict[str, Any]:
    """Parse YAML content string into a dict."""
    # Simplified: real impl would use PyYAML
    import yaml
    return yaml.safe_load(raw)
```

#### `src/configlib/schema.py`

```python
"""Configuration schema validation."""
from __future__ import annotations

from typing import Any


class SchemaError(Exception):
    """Raised when config data fails validation."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"Schema error in '{field}': {message}")


def validate(data: dict[str, Any], required_fields: list[str] | None = None) -> None:
    """Validate configuration data against basic rules."""
    if not isinstance(data, dict):
        raise SchemaError("root", "Config must be a dict")

    required = required_fields or []
    for field in required:
        if field not in data:
            raise SchemaError(field, "Required field missing")
```

#### `src/configlib/merge.py`

```python
"""Deep merge utilities for configuration dicts."""
from __future__ import annotations

from typing import Any


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base. Override values win."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def merge_dicts(*dicts: dict[str, Any]) -> dict[str, Any]:
    """Merge multiple dicts left-to-right using deep_merge."""
    if not dicts:
        return {}
    result = dicts[0].copy()
    for d in dicts[1:]:
        result = deep_merge(result, d)
    return result
```

#### `tests/test_loader.py`

```python
"""Tests for configlib.loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from configlib.loader import detect_format, load_config, load_yaml


def test_load_yaml(tmp_path: Path) -> None:
    """Test loading a YAML configuration file."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("database:\n  host: localhost\n  port: 5432\n")
    result = load_config(config_file)
    assert result["database"]["host"] == "localhost"
    assert result["database"]["port"] == 5432


def test_load_json(tmp_path: Path) -> None:
    """Test loading a JSON configuration file."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"api_key": "test123", "debug": True}))
    result = load_config(config_file)
    assert result["api_key"] == "test123"


def test_detect_format() -> None:
    """Test format detection from file extensions."""
    assert detect_format("config.yaml") == "yaml"
    assert detect_format("config.yml") == "yaml"
    assert detect_format("config.json") == "json"
    with pytest.raises(ValueError, match="Unknown"):
        detect_format("config.txt")
```

#### `tests/test_merge.py`

```python
"""Tests for configlib.merge."""
from __future__ import annotations

from configlib.merge import deep_merge, merge_dicts


def test_deep_merge() -> None:
    """Test recursive dict merging."""
    base = {"a": 1, "b": {"x": 10, "y": 20}}
    override = {"b": {"y": 99, "z": 30}, "c": 3}
    result = deep_merge(base, override)
    assert result == {"a": 1, "b": {"x": 10, "y": 99, "z": 30}, "c": 3}


def test_merge_override() -> None:
    """Test that later dicts override earlier ones."""
    result = merge_dicts({"a": 1}, {"a": 2}, {"a": 3})
    assert result["a"] == 3
```

### Extension Configs

#### `.remora/models/test_function.py`

```python
"""Extension config for test functions."""
from remora.extensions import AgentExtension


class TestFunctionExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "function" and name.startswith("test_")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "TestFunction",
            "custom_system_prompt": (
                "You are a test function agent. Your job is to verify the correctness "
                "of the code under test. When the function you test changes, examine the "
                "diff and update your assertions to match the new behavior. Use "
                "`rewrite_self` to propose test updates. Use `read_node` to check "
                "the current source of the function you test."
            ),
        }
```

#### `.remora/models/package_init.py`

```python
"""Extension config for __init__.py package files."""
from remora.extensions import AgentExtension


class PackageInitExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "file" and name == "__init__.py"

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "PackageInit",
            "custom_system_prompt": (
                "You represent a Python package. You are aware of all modules in your "
                "package. When modules are added, removed, or have their public API "
                "changed, update your __all__ list and re-export statements to keep "
                "the package interface consistent."
            ),
        }
```

### `remora.yaml`

```yaml
discovery_paths:
  - src/
  - tests/

bundle_root: agents
bundle_mapping:
  function: python_function
  method: python_function
  class: python_class
  file: python_file

model_base_url: ${REMORA_LLM_URL:-http://localhost:8000/v1}
model_default: ${REMORA_MODEL:-mock}

swarm_root: .remora
max_concurrency: 2
max_turns: 5
max_trigger_depth: 6
trigger_cooldown_ms: 500
```

### Graph Topology

The demo project produces this graph:

```
configlib/__init__.py (file)
    ├── load_config (function) ── calls ──> validate (function)
    ├── detect_format (function)
    └── load_yaml (function)

configlib/schema.py (file)
    ├── SchemaError (class)
    └── validate (function)

configlib/merge.py (file)
    ├── deep_merge (function)
    └── merge_dicts (function) ── calls ──> deep_merge

tests/test_loader.py (file)
    ├── test_load_yaml (function) ── calls ──> load_config
    ├── test_load_json (function) ── calls ──> load_config
    └── test_detect_format (function) ── calls ──> detect_format

tests/test_merge.py (file)
    ├── test_deep_merge (function) ── calls ──> deep_merge
    └── test_merge_override (function) ── calls ──> merge_dicts
```

**Node count:** 4 files + 11 functions + 1 class = 16 nodes.
**Edge count:** ~6 call edges + 11 parent_of edges = ~17 edges.

This is the ideal size for a force-directed layout: complex enough to be interesting, small enough to layout cleanly.

---

## 3. Prerequisites and Migration Scope

### The Question

The full Option A migration plan (`.scratch/option-a-plan.md`) has 16 tasks that move the entire LSP subsystem from `ASTAgentNode + RemoraDB` to `AgentNode + EventStore`. The demo doesn't need all 16. Which tasks are required for the golden path to work, and which can be deferred?

### What The Demo Path Touches

Walking through the golden path beat-by-beat, here's what each beat requires:

| Beat | What Happens | Required Infrastructure |
|------|-------------|----------------------|
| 1. Launch | LSP starts, graph viewer starts | Both processes can access the same DB. EventStore exists (Phase 1 done). |
| 2. Open files | Tree-sitter discovers nodes, code lenses appear | Watcher -> events -> EventStore -> nodes table. LSP handlers read AgentNode. |
| 3. More files | Graph grows with edges | LazyGraph builds edges. Graph viewer reads nodes + edges. |
| 4. Navigate | Cursor tracking highlights graph node | `cursor_focus` table updated by LSP. Graph viewer reads it. |
| 5. Chat | User chats with agent | Runner gets AgentNode, builds system prompt, calls MockLLM. |
| 6. Edit | Agent activates on file save | ContentChangedEvent -> EventStore -> runner triggers agent. |
| 7. Agent thinks | LLM loop runs, events emitted | AgentStartEvent, ModelRequestEvent, ModelResponseEvent emitted. |
| 8. Cascade | Agent messages another agent | AgentMessageEvent -> runner triggers second agent. |
| 9. Proposal | Agent proposes rewrite | RewriteProposalEvent -> proposal stored -> diagnostic published. |
| 10. Approve | User approves, edit applied | workspace/applyEdit + RewriteAppliedEvent. |
| 11. Reflect | User browses event log | Graph viewer reads events from DB. |

### Minimum Viable Migration (What We Must Do)

From the 16-task Option A plan, the demo requires:

| Option A Task | Required? | Why |
|---|---|---|
| **1. get_node_at_position()** | **Yes** | Hover, code actions, cursor tracking all need this. |
| **2. set_node_status()** | **Yes** | Runner needs to update status (idle -> running -> idle). |
| **3. remove_nodes_for_file()** | **Yes** | Orphan cleanup when files are re-parsed. |
| **4. Watcher returns dicts** | **Yes** | Watcher output must feed into NodeDiscoveredEvents. |
| **5. documents.py uses EventStore** | **Yes** | did_open/did_save must emit events to EventStore. |
| **6. LSP handlers use AgentNode** | **Yes** | Code lens, hover, actions must read from EventStore. |
| **7. commands.py uses AgentNode** | **Yes** | `:RemoraChat`, `:RemoraAccept` etc. need AgentNode. |
| **8. runner.py uses AgentNode** | **Yes** | The entire agent execution loop uses AgentNode. |
| **9. notifications.py uses EventStore** | **Yes** | Cursor tracking uses `get_node_at_position()`. |
| **10. server.py cleanup** | **Yes** | Needs to wire EventStore, remove old imports. |
| **11. Clean up lsp/models.py** | **Defer** | Can delete ASTAgentNode later. For demo, it can coexist. |
| **12. Remove lsp/extensions.py** | **Defer** | Can coexist with core extensions.py during demo. |
| **13. Remove RemoraDB nodes table** | **Defer** | Can keep both tables during demo. Graph viewer reads from EventStore. |
| **14. Update LazyGraph** | **Partial** | LazyGraph needs nodes from EventStore but can keep edges from RemoraDB. |
| **15. Integration test** | **Yes** | Must verify the pipeline works end-to-end. |
| **16. Final cleanup** | **Defer** | Post-demo polish. |

**Summary:** Tasks 1-10, 14 (partial), and 15 are required. Tasks 11-13 and 16 are cleanup that can happen post-demo. This is still substantial — 12 tasks — but they're well-scoped and several are small (Task 9 is ~5 lines changed, Task 10 is import cleanup).

### What Stays On RemoraDB (For Now)

These tables remain in RemoraDB during the demo:

| Table | Purpose | Demo Usage |
|---|---|---|
| `edges` | Graph topology (caller->callee, parent->child) | LazyGraph reads them. Graph viewer reads them. |
| `proposals` | Rewrite proposals with diffs | Runner writes, commands.py reads, graph viewer displays. |
| `cursor_focus` | Current cursor position -> agent_id | Notifications write, graph viewer reads. |
| `command_queue` | Web -> LSP commands (chat, focus, approve) | Graph viewer writes, runner/commands reads. |
| `events` | LSP event log (chat, tool calls, model responses) | Runner writes, panel displays, graph viewer displays. |
| `activation_chain` | Trigger chain tracking | Runner reads/writes for cycle detection. |

The `nodes` table moves entirely to EventStore. Both databases live in the same `.remora/` directory.

### What Exists Already (Phase 1)

All of these are implemented and tested (120 tests passing):

- `AgentNode` Pydantic model with `to_code_lens()`, `to_hover()`, `to_code_actions()`, `to_system_prompt()`, `to_document_symbol()`, `from_row()`, `to_row()`.
- `EventStore` with `events` + `nodes` tables, WAL mode, `append()`, `get_node()`, `list_nodes()`.
- `NodeProjection` processing `NodeDiscoveredEvent`, `NodeRemovedEvent`, `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`.
- `AgentExtension` base class with mtime-cached `load_extensions()`.
- Full event hierarchy in `events.py`.
- `ToolSchema` dataclass with `to_llm_tool()` and `to_code_action()`.

### New Infrastructure Needed (Beyond Option A)

The demo also needs things not in the Option A plan:

| Component | Description | Section |
|---|---|---|
| Enhanced MockLLMClient | Scripted responses for golden path | Section 4 |
| Graph Viewer (Stario app) | Web UI for graph visualization | Sections 5-8 |
| DB polling bridge | Publishes DB changes to in-process Relay | Section 6 |
| Demo project files | configlib source + extension configs | Section 2 (done) |
| Demo launcher | Entry points for both processes | Section 11 |
| SVG element builders | Svg, Circle, Line, G, Text for Stario | Section 7 |
| Server-side graph layout | Python layout algorithm for node positions | Section 5 |

---

## 4. Enhanced MockLLMClient

### Why A Mock

The demo must work without any external LLM service. Running `ollama` or `vllm` locally is a heavy prerequisite — we want someone to clone the repo, `devenv shell`, and run the demo immediately. The mock also guarantees deterministic behavior: the golden path always produces the same cascade, the same proposal, the same event sequence. No temperature-dependent surprises.

But it can't feel fake. The text content must read like a real agent. The tool calls must have realistic arguments. The mock must be invisible to the demo viewer — they should believe they're watching a real LLM until told otherwise.

### Architecture

The enhanced `MockLLMClient` replaces the existing trivial mock in `tests/fixtures/mock_llm.py`. It implements the same `chat()` interface as `LLMClient` and returns `LLMResponse` objects directly (no adapter needed).

```
MockLLMClient
├── ScriptedDispatcher          # Pattern-matches (trigger_type, agent_name) → response
│   ├── ContentChangedScript    # Handles "file changed, analyze diff" triggers
│   ├── AgentMessageScript      # Handles "message from another agent" triggers
│   └── HumanChatScript         # Handles "user asked a question" triggers
└── FallbackDispatcher          # Optional: forwards to real LLM via REMORA_LLM_URL
```

### The `chat()` Interface

The runner calls `llm.chat(messages, tools)` where:
- `messages`: list of `{"role": "system"|"user"|"assistant", "content": str}` dicts
- `tools`: list of OpenAI-format tool definitions
- Returns: `LLMResponse(content=str|None, tool_calls=list[ToolCall])`

The mock inspects the messages to determine:
1. **Agent identity**: parsed from the system prompt (agent name, node type, extension info)
2. **Trigger type**: parsed from the most recent user message (human chat? agent message? file change context?)
3. **Round number**: how many assistant messages precede this call (for multi-round tool call loops)

### Pattern-Matching Dispatch

```python
"""Enhanced MockLLMClient for deterministic demo scenarios."""
from __future__ import annotations

import re
from typing import Any

from remora.lsp.runner import LLMResponse, ToolCall


class MockLLMClient:
    """Deterministic LLM mock that produces scripted responses for the demo.

    Dispatches based on (agent_identity, trigger_type, round_number) extracted
    from the messages list. Falls back to a generic acknowledgment if no script
    matches.
    """

    def __init__(self, scripts: list[Script] | None = None) -> None:
        self.scripts = scripts or default_scripts()
        self.call_count = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        ctx = parse_context(messages)

        for script in self.scripts:
            if script.matches(ctx):
                return script.respond(ctx)

        # Generic fallback: acknowledge with text, no tool calls
        return LLMResponse(
            content=f"Acknowledged. I'm {ctx.agent_name}, monitoring for changes.",
            tool_calls=[],
        )

    async def close(self) -> None:
        pass
```

### Context Extraction

```python
from dataclasses import dataclass, field


@dataclass
class MockContext:
    """Parsed context from the message list, used by scripts for dispatch."""

    agent_name: str = ""
    agent_type: str = ""            # "function", "class", "file"
    extension_name: str = ""        # "TestFunction", "PackageInit", ""
    trigger_type: str = ""          # "human_chat", "agent_message", "content_changed", "rejection"
    trigger_message: str = ""       # The actual user/agent message content
    from_agent: str = ""            # For agent_message triggers
    round_number: int = 0           # How many assistant messages precede this call
    has_tool: dict[str, bool] = field(default_factory=dict)  # Which tools are available
    system_prompt: str = ""         # Full system prompt for edge cases


def parse_context(messages: list[dict[str, Any]]) -> MockContext:
    """Extract dispatch context from the messages list."""
    ctx = MockContext()

    # System prompt is always first
    if messages and messages[0]["role"] == "system":
        sys = messages[0]["content"]
        ctx.system_prompt = sys

        # Extract agent name: "You are the agent for `load_config`" or similar
        m = re.search(r"agent for `([^`]+)`", sys)
        if m:
            ctx.agent_name = m.group(1)

        # Extract node type from system prompt
        for nt in ("function", "class", "file"):
            if f"node_type: {nt}" in sys or f"You are a {nt}" in sys:
                ctx.agent_type = nt
                break

        # Extension name
        if "TestFunction" in sys or "test function agent" in sys.lower():
            ctx.extension_name = "TestFunction"
        elif "PackageInit" in sys or "package" in sys.lower() and "__init__" in sys:
            ctx.extension_name = "PackageInit"

    # Count rounds (assistant messages = completed rounds)
    ctx.round_number = sum(1 for m in messages if m["role"] == "assistant")

    # Find the last user message to determine trigger type
    user_msgs = [m for m in messages if m["role"] == "user"]
    if user_msgs:
        last = user_msgs[-1]["content"]
        ctx.trigger_message = last

        if last.startswith("[From "):
            ctx.trigger_type = "agent_message"
            fm = re.match(r"\[From ([^\]]+)\]", last)
            if fm:
                ctx.from_agent = fm.group(1)
        elif "[Feedback on rejected proposal]" in last:
            ctx.trigger_type = "rejection"
        elif "[Tool result for" in last:
            # This is a tool result round, keep the previous trigger type
            ctx.trigger_type = "tool_followup"
        else:
            # Could be human chat or content-changed context
            # The runner puts HumanChatEvent messages as plain user messages
            # Content changes come through as trigger context in system prompt
            ctx.trigger_type = "human_chat"

    return ctx
```

### Script Base Class and Default Scripts

```python
from abc import ABC, abstractmethod


class Script(ABC):
    """Base class for mock response scripts."""

    @abstractmethod
    def matches(self, ctx: MockContext) -> bool:
        """Return True if this script handles the given context."""

    @abstractmethod
    def respond(self, ctx: MockContext) -> LLMResponse:
        """Generate the mock response."""


class ContentChangedAnalyzeScript(Script):
    """When a source function is triggered by ContentChanged, it analyzes the
    change and messages dependent test nodes.

    This is the core cascade mechanism: source agent detects a change, then
    uses message_node to tell the test agent to update its assertions.

    Matches: non-test functions on round 0 when system prompt mentions
    subscriptions or content changes.
    """

    def matches(self, ctx: MockContext) -> bool:
        return (
            ctx.extension_name != "TestFunction"
            and ctx.agent_type == "function"
            and ctx.round_number == 0
            and "content" in ctx.trigger_type.lower() or "parameter" in ctx.trigger_message.lower()
            or "changed" in ctx.trigger_message.lower() or "added" in ctx.trigger_message.lower()
        )

    def respond(self, ctx: MockContext) -> LLMResponse:
        # The agent notices the change and messages the test node
        # For the golden path: load_config changed → message test_load_yaml
        return LLMResponse(
            content=(
                f"I see that `{ctx.agent_name}` has been updated with a new `timeout` parameter. "
                f"This changes the function signature, which means callers and tests need to know "
                f"about it. Let me notify the test agent."
            ),
            tool_calls=[
                ToolCall(
                    name="message_node",
                    arguments={
                        "target_id": "test_load_yaml",
                        "message": (
                            "The function `load_config` now accepts an optional `timeout: int = 30` "
                            "parameter. Please update your test to verify the default timeout "
                            "behavior — you can check that the returned config dict works correctly "
                            "with the new parameter. No breaking change, but the test should "
                            "demonstrate awareness of the new capability."
                        ),
                    },
                    id="tc_msg_001",
                ),
            ],
        )


class TestAgentUpdateScript(Script):
    """When a test agent receives a message from a source agent, it reads the
    source node first (round 0), then proposes a rewrite (round 1).

    This is the second half of the cascade: test agent receives notification,
    reads the current source, and proposes updated test code.
    """

    def matches(self, ctx: MockContext) -> bool:
        return ctx.extension_name == "TestFunction" and ctx.trigger_type == "agent_message"

    def respond(self, ctx: MockContext) -> LLMResponse:
        if ctx.round_number == 0:
            # First round: read the source node to see what changed
            return LLMResponse(
                content="I received a notification about changes. Let me read the current source first.",
                tool_calls=[
                    ToolCall(
                        name="read_node",
                        arguments={"target_id": "load_config"},
                        id="tc_read_001",
                    ),
                ],
            )
        else:
            # Second round (after reading source): propose a rewrite
            return LLMResponse(
                content=(
                    "I can see that `load_config` now has a `timeout` parameter with a default "
                    "of 30. I'll update my test to verify the default behavior and add an "
                    "explicit timeout test."
                ),
                tool_calls=[
                    ToolCall(
                        name="rewrite_self",
                        arguments={
                            "new_source": (
                                'def test_load_yaml(tmp_path: Path) -> None:\n'
                                '    """Test loading a YAML configuration file."""\n'
                                '    config_file = tmp_path / "config.yaml"\n'
                                '    config_file.write_text("database:\\n  host: localhost\\n  port: 5432\\n")\n'
                                '    result = load_config(config_file)\n'
                                '    assert result["database"]["host"] == "localhost"\n'
                                '    assert result["database"]["port"] == 5432\n'
                                '\n'
                                '\n'
                                'def test_load_yaml_with_timeout(tmp_path: Path) -> None:\n'
                                '    """Test that load_config accepts timeout parameter."""\n'
                                '    config_file = tmp_path / "config.yaml"\n'
                                '    config_file.write_text("debug: true\\n")\n'
                                '    result = load_config(config_file, timeout=60)\n'
                                '    assert result["debug"] is True\n'
                            ),
                        },
                        id="tc_rewrite_001",
                    ),
                ],
            )


class HumanChatScript(Script):
    """When a human chats with an agent, respond with a description of what
    the agent does based on its system prompt context.

    For the golden path beat 5: user asks "what do you do?" to load_config.
    """

    def matches(self, ctx: MockContext) -> bool:
        return ctx.trigger_type == "human_chat" and ctx.round_number == 0

    def respond(self, ctx: MockContext) -> LLMResponse:
        # Generate a contextual response based on agent name
        responses = {
            "load_config": (
                "I'm the agent for `load_config`. I load configuration files by detecting "
                "their format (JSON or YAML), parsing them, and running schema validation. "
                "When my source code changes, I analyze the diff and notify dependent agents "
                "— like the test agents that verify my behavior — so they can update too."
            ),
            "detect_format": (
                "I handle format detection for configuration files. I map file extensions "
                "like `.json`, `.yaml`, `.yml`, and `.toml` to their format names. If I see "
                "an unrecognized extension, I raise a ValueError."
            ),
            "validate": (
                "I'm the schema validator. I check that configuration data is a dict and "
                "that all required fields are present. When validation rules change, I notify "
                "the agents that depend on me."
            ),
            "deep_merge": (
                "I recursively merge configuration dictionaries. Override values win over "
                "base values, and nested dicts are merged recursively rather than replaced."
            ),
        }

        content = responses.get(
            ctx.agent_name,
            f"I'm the agent for `{ctx.agent_name}`. I monitor my source code for changes "
            f"and coordinate with related agents when updates are needed.",
        )

        return LLMResponse(content=content, tool_calls=[])


class RejectionFeedbackScript(Script):
    """When a proposal is rejected, the agent reads the feedback and tries again.

    Not part of the golden path (the golden path always approves), but useful
    for extended demos.
    """

    def matches(self, ctx: MockContext) -> bool:
        return ctx.trigger_type == "rejection"

    def respond(self, ctx: MockContext) -> LLMResponse:
        return LLMResponse(
            content=(
                f"I see my previous proposal was rejected. Let me reconsider based on "
                f"the feedback: {ctx.trigger_message[:200]}"
            ),
            tool_calls=[],
        )


class ToolFollowupScript(Script):
    """After a tool result comes back (e.g., read_node result), continue
    the conversation naturally. This handles round > 0 for non-test agents.
    """

    def matches(self, ctx: MockContext) -> bool:
        return ctx.trigger_type == "tool_followup" and ctx.round_number > 0

    def respond(self, ctx: MockContext) -> LLMResponse:
        return LLMResponse(
            content=(
                f"Based on the current state of the code, everything looks consistent. "
                f"No further action needed from my end."
            ),
            tool_calls=[],
        )


def default_scripts() -> list[Script]:
    """The default script list used for the golden path demo.

    Order matters — first match wins.
    """
    return [
        TestAgentUpdateScript(),
        ContentChangedAnalyzeScript(),
        RejectionFeedbackScript(),
        ToolFollowupScript(),
        HumanChatScript(),
    ]
```

### How Scripts Map to Golden Path Beats

| Beat | Agent | Trigger | Script | Round(s) | Tool Calls |
|------|-------|---------|--------|----------|------------|
| 5. Chat | `load_config` | `human_chat` ("what do you do?") | `HumanChatScript` | 0 | None — text response |
| 7. Agent thinks | `load_config` | `content_changed` (timeout param added) | `ContentChangedAnalyzeScript` | 0 | `message_node(test_load_yaml, ...)` |
| 8. Cascade (read) | `test_load_yaml` | `agent_message` (from load_config) | `TestAgentUpdateScript` | 0 | `read_node(load_config)` |
| 8. Cascade (rewrite) | `test_load_yaml` | `tool_followup` (read result) | `TestAgentUpdateScript` | 1 | `rewrite_self(new test code)` |

### Fallback to Real LLM

For demos with an actual LLM available, the mock can be bypassed entirely. The `remora.yaml` config already supports this:

```yaml
model_base_url: ${REMORA_LLM_URL:-http://localhost:8000/v1}
model_default: ${REMORA_MODEL:-mock}
```

When `model_default` is `"mock"`, the server instantiates `MockLLMClient`. When it's anything else (e.g., `"qwen2.5-coder"`), it instantiates the real `LLMClient`. This selection happens in `server.py` during initialization:

```python
# In server.py startup
if config.model_default == "mock":
    from remora_demo.mock_llm import MockLLMClient
    llm = MockLLMClient()
else:
    llm = LLMClient(
        base_url=config.model_base_url,
        model=config.model_default,
    )
runner = AgentRunner(server, llm=llm)
```

### File Location

The enhanced mock lives at `remora_demo/mock_llm.py` (not in `tests/fixtures/` — it's demo infrastructure, not test infrastructure). The existing `tests/fixtures/mock_llm.py` stays as-is for unit tests that just need a silent mock.

### Testing the Mock

The mock itself should have a small test suite in `tests/test_mock_llm.py`:

```python
"""Tests for the enhanced MockLLMClient."""
import pytest
from remora_demo.mock_llm import MockLLMClient, parse_context


@pytest.fixture
def mock():
    return MockLLMClient()


def _system(name: str, node_type: str = "function", extension: str = "") -> dict:
    ext_line = f"\nExtension: {extension}" if extension else ""
    return {
        "role": "system",
        "content": f"You are the agent for `{name}`. node_type: {node_type}{ext_line}",
    }


@pytest.mark.asyncio
async def test_human_chat_known_agent(mock):
    messages = [_system("load_config"), {"role": "user", "content": "what do you do?"}]
    resp = await mock.chat(messages, tools=[])
    assert "load_config" in resp.content
    assert resp.tool_calls == []


@pytest.mark.asyncio
async def test_content_changed_triggers_message_node(mock):
    messages = [
        _system("load_config"),
        {"role": "user", "content": "The parameter `timeout` was added to load_config."},
    ]
    resp = await mock.chat(messages, tools=[])
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "message_node"
    assert "test_load_yaml" in resp.tool_calls[0].arguments["target_id"]


@pytest.mark.asyncio
async def test_test_agent_reads_then_rewrites(mock):
    # Round 0: agent_message → read_node
    messages = [
        _system("test_load_yaml", extension="TestFunction"),
        {"role": "user", "content": "[From load_config]: timeout param was added"},
    ]
    resp = await mock.chat(messages, tools=[])
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "read_node"

    # Round 1: tool result → rewrite_self
    messages.append({"role": "assistant", "content": resp.content or ""})
    messages.append({"role": "user", "content": "[Tool result for read_node]: ..."})
    resp = await mock.chat(messages, tools=[])
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "rewrite_self"
    assert "timeout" in resp.tool_calls[0].arguments["new_source"]


@pytest.mark.asyncio
async def test_fallback_for_unknown_agent(mock):
    messages = [_system("some_random_function"), {"role": "user", "content": "hello"}]
    resp = await mock.chat(messages, tools=[])
    assert "some_random_function" in resp.content
    assert resp.tool_calls == []


def test_parse_context_agent_message():
    messages = [
        {"role": "system", "content": "You are the agent for `validate`. node_type: function"},
        {"role": "user", "content": "[From load_config]: please check validation rules"},
    ]
    ctx = parse_context(messages)
    assert ctx.agent_name == "validate"
    assert ctx.trigger_type == "agent_message"
    assert ctx.from_agent == "load_config"
    assert ctx.round_number == 0
```

### Design Decisions

1. **First-match dispatch, not lookup table.** Scripts are ordered and the first matching script wins. This is more flexible than a `(trigger_type, agent_name)` dict because scripts can match on combinations of multiple fields (extension + trigger + round).

2. **Scripts are classes, not lambdas.** Each script has a docstring explaining what demo scenario it handles. This makes the mock self-documenting — you can read the script list to understand the golden path.

3. **Round-awareness.** The `TestAgentUpdateScript` produces different responses on round 0 (read_node) and round 1 (rewrite_self). This is how the runner's tool-call loop works: LLM → tool call → result → LLM → tool call → done. The mock must participate in this loop correctly.

4. **Hardcoded agent names.** Yes, `"test_load_yaml"` and `"load_config"` appear as string literals in the scripts. This is intentional — the demo is a specific scenario with specific agents. The mock doesn't need to be general-purpose. If someone changes the demo project, they update the scripts too.

5. **Realistic text content.** Every response includes natural-language `content` alongside tool calls. Real LLMs do this too — they explain what they're doing before calling tools. The graph viewer's event stream will show this text, making the demo feel authentic.

---

## 5. Graph Viewer Architecture

### The Migration: Starlette → Stario

The current v2 graph viewer (`remora_demo/graph/`) uses Starlette + datastar-py + d3-force. It works, but it's architecturally split: the server sends raw JSON signals via SSE, and the client runs a full d3-force simulation, manages SVG elements, handles zoom/pan, and renders everything. The server is thin; the client is thick.

The EventBased demo inverts this. Following the Stario philosophy ("server owns everything"), the server computes graph layout, renders SVG to HTML strings, and pushes DOM patches via SSE. The client has zero JavaScript framework — Datastar handles DOM morphing, and CSS transitions handle animation. The server is thick; the client is a thin Datastar shell.

### Why This Is Better For The Demo

1. **Debuggability.** When the layout looks wrong, you fix Python, not JavaScript. You can `print(render_graph(...))` and see the SVG.
2. **SSE as the single transport.** Every visual change — node appearing, status color changing, cursor highlight moving — arrives as a `w.patch()` DOM patch. No separate signal protocol.
3. **No client state.** No simulation to synchronize. No stale d3 state after a reconnect. Reconnect = re-render everything.
4. **Stario is already a dependency** (or will be for the broader project). No need for Starlette + datastar-py.
5. **CSS transitions give us smooth animation for free.** Node position changes → CSS `transition: transform 0.5s ease` → smooth motion. Status color changes → `transition: fill 0.3s`. No JavaScript animation loop.

### Module Structure

```
remora_demo/graph/
    __init__.py
    __main__.py              # CLI entry point (python -m remora_demo.graph)
    app.py                   # Stario app factory: routes, handlers
    state.py                 # GraphState: DB reader + change detection (keep existing)
    layout.py                # Server-side graph layout (force-directed or hierarchical)
    views/
        __init__.py
        graph.py             # render_graph(snapshot) → SVG HTML string
        sidebar.py           # render_sidebar(node, events, proposals, connections) → HTML
        shell.py             # render_shell() → full HTML page with Datastar init
        event_stream.py      # render_event_list(events) → HTML for scrolling event log
    svg.py                   # SVG element builders: Svg, G, Circle, Line, Text, Rect, Path
    bridge.py                # DB→Relay bridge: polls DB, publishes changes to Relay
    css.py                   # All CSS in one place (Catppuccin dark theme)
```

### Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| HTTP server | **Stario** (`stario.http.app`) | Routes, handlers, SSE streaming |
| SSE protocol | **Stario** (`w.patch()`, `w.alive()`) | DOM patches to client |
| HTML generation | **Stario** (`stario.html.core.Tag`) | SVG + HTML element builders |
| Reactivity | **Datastar** (CDN) | Client-side DOM morphing, signals |
| Pub/sub | **Stario Relay** (`stario.relay`) | In-process event bus |
| Real-time bridge | Custom `bridge.py` | DB polling → Relay publish |
| Graph layout | Custom `layout.py` | Python force-directed simulation |
| Database | SQLite (WAL mode, read-only) | Shared with LSP server |

### Process Model

```
┌─────────────────────────────┐     ┌──────────────────────────────┐
│   Neovim + LSP Server       │     │   Graph Viewer (Stario)      │
│                             │     │                              │
│   runner.py                 │     │   app.py (HTTP handlers)     │
│     ↕                       │     │     ↕                        │
│   EventStore                │     │   bridge.py                  │
│     ↕                       │     │     ↕ poll every 300ms       │
│   SQLite (.remora/          │────▶│   SQLite (read-only,         │
│     indexer.db)              │     │     same file, WAL mode)     │
│                             │     │     ↕                        │
│                             │     │   Relay                      │
│                             │     │     ↕ publish("graph.update") │
│                             │     │   SSE handlers               │
│                             │     │     ↕ w.patch(render(...))   │
│                             │     │   Browser (Datastar)         │
└─────────────────────────────┘     └──────────────────────────────┘
```

Two separate processes. The LSP server owns the database and writes events, nodes, edges, cursor_focus. The graph viewer reads the same database in WAL mode (concurrent readers are safe) and pushes visual updates to the browser.

The processes communicate only through the shared SQLite file. No sockets, no IPC, no shared memory. SQLite WAL mode allows the LSP server to write while the graph viewer reads concurrently without blocking.

The command queue works in reverse: the graph viewer writes to `command_queue`, and the LSP server's `AgentRunner.poll_command_queue()` reads and dispatches.

### Server-Side Graph Layout

The existing v2 uses d3-force on the client. We need an equivalent in Python. Three options:

**Option A: Simple spring-force simulation in Python.**
- Implement a basic force-directed layout in ~100 lines of Python.
- Forces: repulsion (all pairs), attraction (linked pairs), center gravity.
- Run 100-200 iterations on startup, then incrementally update when nodes change.
- Pros: Zero dependencies. Full control. Fast enough for 16 nodes.
- Cons: Won't match d3-force quality for large graphs. (We only have 16 nodes.)

**Option B: Hierarchical layout.**
- Parent nodes at top, children below. Test files on the right. Edges as curves.
- Deterministic: same graph always gets same layout.
- Pros: Clean, predictable. Great for demo with known structure.
- Cons: Less "alive" feeling than force-directed. New nodes appear at fixed positions.

**Option C: Use a Python graph layout library (e.g., networkx spring_layout).**
- `networkx.spring_layout()` does exactly what d3-force does.
- Pros: Battle-tested. One line of code.
- Cons: Heavy dependency (networkx) just for layout.

**Decision: Option A (custom spring-force) with hierarchical hints.**

For 16 nodes, a simple Python simulation is more than sufficient. We can seed initial positions using hierarchical hints (files at top, children below) so the layout converges quickly. The simulation runs server-side, positions are baked into the SVG, and CSS transitions handle the animation when positions change.

```python
"""Server-side force-directed graph layout."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class LayoutNode:
    id: str
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    node_type: str = "function"
    pinned: bool = False


@dataclass
class LayoutEdge:
    source: str
    target: str
    edge_type: str = "calls"


class ForceLayout:
    """Minimal force-directed layout for small graphs (<50 nodes).

    Forces:
    - Repulsion: all pairs, inverse-square
    - Attraction: linked pairs, spring
    - Center gravity: pulls everything toward center
    - Hierarchy: file nodes float up, children below
    """

    def __init__(
        self,
        width: float = 900,
        height: float = 600,
        repulsion: float = 5000.0,
        attraction: float = 0.005,
        gravity: float = 0.02,
        damping: float = 0.9,
    ) -> None:
        self.width = width
        self.height = height
        self.repulsion = repulsion
        self.attraction = attraction
        self.gravity = gravity
        self.damping = damping
        self.nodes: dict[str, LayoutNode] = {}
        self.edges: list[LayoutEdge] = []

    def set_graph(self, nodes: list[dict], edges: list[dict]) -> None:
        """Set the full graph. Preserves positions for existing nodes."""
        existing = {n.id: n for n in self.nodes.values()}
        self.nodes = {}
        for n in nodes:
            nid = n.get("remora_id") or n.get("id", "")
            if nid in existing:
                self.nodes[nid] = existing[nid]
                # Update metadata
                self.nodes[nid].node_type = n.get("node_type", "function")
            else:
                # Seed position: files at top, functions below
                nt = n.get("node_type", "function")
                y_seed = 100 if nt == "file" else 300 + random.uniform(-50, 50)
                x_seed = self.width / 2 + random.uniform(-200, 200)
                self.nodes[nid] = LayoutNode(
                    id=nid, x=x_seed, y=y_seed, node_type=nt,
                )

        self.edges = [
            LayoutEdge(
                source=e.get("from_id", ""),
                target=e.get("to_id", ""),
                edge_type=e.get("edge_type", "calls"),
            )
            for e in edges
        ]

    def step(self, iterations: int = 1) -> None:
        """Run N iterations of the force simulation."""
        node_list = list(self.nodes.values())
        n = len(node_list)
        if n == 0:
            return

        cx, cy = self.width / 2, self.height / 2

        for _ in range(iterations):
            # Repulsion (all pairs)
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = node_list[i], node_list[j]
                    dx = a.x - b.x
                    dy = a.y - b.y
                    dist_sq = dx * dx + dy * dy + 1.0
                    force = self.repulsion / dist_sq
                    dist = math.sqrt(dist_sq)
                    fx = force * dx / dist
                    fy = force * dy / dist
                    if not a.pinned:
                        a.vx += fx
                        a.vy += fy
                    if not b.pinned:
                        b.vx -= fx
                        b.vy -= fy

            # Attraction (linked pairs)
            for edge in self.edges:
                a = self.nodes.get(edge.source)
                b = self.nodes.get(edge.target)
                if not a or not b:
                    continue
                dx = b.x - a.x
                dy = b.y - a.y
                dist = math.sqrt(dx * dx + dy * dy + 1.0)
                # Shorter desired distance for parent_of edges
                desired = 80 if edge.edge_type == "parent_of" else 160
                force = self.attraction * (dist - desired)
                fx = force * dx / dist
                fy = force * dy / dist
                if not a.pinned:
                    a.vx += fx
                    a.vy += fy
                if not b.pinned:
                    b.vx -= fx
                    b.vy -= fy

            # Center gravity
            for node in node_list:
                if not node.pinned:
                    node.vx += (cx - node.x) * self.gravity
                    node.vy += (cy - node.y) * self.gravity

            # Apply velocity + damping
            for node in node_list:
                if not node.pinned:
                    node.vx *= self.damping
                    node.vy *= self.damping
                    node.x += node.vx
                    node.y += node.vy
                    # Clamp to bounds with padding
                    node.x = max(40, min(self.width - 40, node.x))
                    node.y = max(40, min(self.height - 40, node.y))

    def get_positions(self) -> dict[str, tuple[float, float]]:
        """Return {node_id: (x, y)} for all nodes."""
        return {n.id: (n.x, n.y) for n in self.nodes.values()}
```

On startup, the layout runs `step(150)` to converge. When the bridge detects new nodes or topology changes, it runs `step(50)` incrementally. Each `w.patch()` sends the SVG with updated `transform` attributes. CSS `transition: transform 0.5s ease-out` on the `<g>` elements makes the movement smooth on the client without any JavaScript animation.

### Entry Point and Lifecycle

```python
# remora_demo/graph/__main__.py
"""python -m remora_demo.graph [--port 8420] [--db .remora/indexer.db]"""

import argparse
from remora_demo.graph.app import create_app
from stario.http.app import App


def main() -> None:
    parser = argparse.ArgumentParser(description="Remora Graph Viewer")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db", default=".remora/indexer.db")
    args = parser.parse_args()

    app = create_app(db_path=args.db)
    app.serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

The Stario `App.serve()` method starts the HTTP server with an event loop. The bridge runs as a background task within that loop, polling the DB and publishing to Relay.

### Key Architectural Invariants

1. **The graph viewer never writes to the `nodes`, `edges`, or `events` tables.** It only writes to `command_queue`.
2. **The graph viewer opens the DB in read-only WAL mode.** The LSP server is the sole writer.
3. **All visual updates go through Relay → SSE.** No polling from the client. The browser opens one SSE connection and receives DOM patches.
4. **The layout is deterministic for a given graph.** Same nodes + edges → same positions (modulo initial random seed, which we fix for reproducibility).
5. **No client-side state survives a reconnect.** If the SSE drops and reconnects, the server re-sends the full view. Datastar morphs the DOM to match.

---

## 6. Graph Viewer: Server Implementation

### Stario App Factory

The app is created by a factory function that wires up dependencies (Go-style closures, same pattern as the Stario chat example).

```python
"""remora_demo/graph/app.py — Stario app for the graph viewer."""
from __future__ import annotations

import asyncio

from stario import Relay, Stario
from stario.telemetry.core import noop_tracer

from remora_demo.graph.bridge import DBBridge
from remora_demo.graph.layout import ForceLayout
from remora_demo.graph.state import GraphState
from remora_demo.graph import handlers


def create_app(db_path: str = ".remora/indexer.db") -> Stario:
    """Create the Stario graph viewer app.

    Dependencies:
    - GraphState: reads SQLite DB (same as current v2)
    - ForceLayout: computes node positions server-side
    - Relay: in-process pub/sub for SSE push
    - DBBridge: polls DB changes, publishes to Relay
    """
    app = Stario(tracer=noop_tracer)
    state = GraphState(db_path=db_path)
    layout = ForceLayout(width=900, height=600)
    relay: Relay[str] = Relay()
    bridge = DBBridge(state=state, layout=layout, relay=relay)

    # Routes
    app.get("/", handlers.index(layout, state))
    app.get("/subscribe", handlers.subscribe(state, layout, relay))
    app.get("/agent/{agent_id}", handlers.agent_detail(state))
    app.post("/command", handlers.post_command(state))
    app.get("/events", handlers.event_stream(state))

    # Start the DB polling bridge as a background task
    @app.on("startup")
    async def start_bridge():
        asyncio.create_task(bridge.run())

    return app
```

### Handlers

Each handler is a factory function that captures its dependencies and returns an `async def handler(c: Context, w: Writer)`. This is the Stario pattern — no global state, no middleware, just closures.

```python
"""remora_demo/graph/handlers.py"""
from __future__ import annotations

import json
from dataclasses import dataclass

from stario import Context, Relay, Writer

from remora_demo.graph.layout import ForceLayout
from remora_demo.graph.state import GraphState
from remora_demo.graph.views.graph import render_graph
from remora_demo.graph.views.shell import render_shell
from remora_demo.graph.views.sidebar import render_sidebar_content
from remora_demo.graph.views.event_stream import render_event_list


def index(layout: ForceLayout, state: GraphState):
    """GET / — Serve the full HTML page."""

    async def handler(c: Context, w: Writer) -> None:
        # Read initial snapshot and compute layout
        snapshot = state.read_snapshot()
        layout.set_graph(snapshot.nodes, snapshot.edges)
        layout.step(150)  # Converge the initial layout
        positions = layout.get_positions()

        w.html(render_shell(snapshot, positions))

    return handler


def subscribe(state: GraphState, layout: ForceLayout, relay: Relay[str]):
    """GET /subscribe — SSE endpoint. Pushes DOM patches on graph changes."""

    async def handler(c: Context, w: Writer) -> None:
        # Send initial full graph render
        snapshot = state.read_snapshot()
        positions = layout.get_positions()
        w.patch(render_graph(snapshot, positions))

        # Stream updates via Relay
        async for subject, change_type in w.alive(relay.subscribe("graph.*")):
            snapshot = state.read_snapshot()
            positions = layout.get_positions()

            if subject == "graph.topology":
                # Full graph re-render (nodes added/removed, edges changed)
                w.patch(render_graph(snapshot, positions))
            elif subject == "graph.status":
                # Only status changed — patch individual nodes
                w.patch(render_graph(snapshot, positions))
            elif subject == "graph.cursor":
                # Cursor focus changed — patch the highlight
                w.patch(render_graph(snapshot, positions))
            elif subject == "graph.events":
                # New events — update event stream if visible
                events = state.read_recent_events(limit=30)
                w.patch(render_event_list(events))

    return handler


def agent_detail(state: GraphState):
    """GET /agent/{agent_id} — Sidebar content for a selected node."""

    async def handler(c: Context, w: Writer) -> None:
        agent_id = c.req.params["agent_id"]
        node = state.read_node(agent_id)
        events = state.read_events_for_agent(agent_id) if node else []
        proposals = state.read_proposals_for_agent(agent_id) if node else []
        connections = state.read_edges_for_node(agent_id) if node else {}
        w.html(render_sidebar_content(node, events, proposals, connections))

    return handler


@dataclass
class CommandSignals:
    command_type: str = ""
    agent_id: str = ""
    payload: str = ""  # JSON string


def post_command(state: GraphState):
    """POST /command — Queue a command for the LSP server."""

    async def handler(c: Context, w: Writer) -> None:
        signals = await c.signals(CommandSignals)

        if not signals.command_type:
            w.text("command_type required", 400)
            return

        payload = json.loads(signals.payload) if signals.payload else {}
        cmd_id = state.push_command(
            signals.command_type,
            signals.agent_id or None,
            payload,
        )
        w.json({"status": "queued", "command_id": cmd_id})

    return handler


def event_stream(state: GraphState):
    """GET /events — Returns the recent event list HTML fragment."""

    async def handler(c: Context, w: Writer) -> None:
        events = state.read_recent_events(limit=30)
        w.html(render_event_list(events))

    return handler
```

### DB→Relay Bridge

The bridge is the glue between the shared SQLite database and the Stario Relay. It polls the DB for changes (reusing the existing `GraphState._fingerprint()` mechanism) and publishes to specific Relay subjects when things change. SSE handlers subscribe to these subjects and push DOM patches.

```python
"""remora_demo/graph/bridge.py — Polls DB, publishes changes to Relay."""
from __future__ import annotations

import asyncio
import logging

from stario import Relay

from remora_demo.graph.layout import ForceLayout
from remora_demo.graph.state import GraphState

logger = logging.getLogger("remora.graph.bridge")


class DBBridge:
    """Polls the shared SQLite DB and publishes changes to the in-process Relay.

    Change detection uses fingerprinting: a lightweight query that returns
    counts and max rowids for each table. When the fingerprint changes,
    we determine what changed and publish to the appropriate Relay subject.
    """

    def __init__(
        self,
        state: GraphState,
        layout: ForceLayout,
        relay: Relay[str],
        poll_interval: float = 0.3,
    ) -> None:
        self.state = state
        self.layout = layout
        self.relay = relay
        self.poll_interval = poll_interval
        self._last_fp: dict[str, str] = {}

    async def run(self) -> None:
        """Main polling loop. Runs until cancelled."""
        logger.info("DBBridge started, polling every %.1fs", self.poll_interval)
        while True:
            try:
                await self._poll_once()
            except Exception:
                logger.debug("Bridge poll error", exc_info=True)
            await asyncio.sleep(self.poll_interval)

    async def _poll_once(self) -> None:
        """Check each table's fingerprint and publish changes."""
        fp = await asyncio.to_thread(self._read_fingerprints)

        changed_subjects: list[str] = []

        # Topology change: nodes or edges added/removed
        if fp.get("nodes") != self._last_fp.get("nodes") or \
           fp.get("edges") != self._last_fp.get("edges"):
            # Re-read snapshot and update layout
            snapshot = await asyncio.to_thread(self.state.read_snapshot)
            self.layout.set_graph(snapshot.nodes, snapshot.edges)
            self.layout.step(50)  # Incremental settle
            changed_subjects.append("graph.topology")

        # Status change: node status updated (running, idle, pending_approval)
        if fp.get("node_status") != self._last_fp.get("node_status"):
            changed_subjects.append("graph.status")

        # Cursor change
        if fp.get("cursor") != self._last_fp.get("cursor"):
            changed_subjects.append("graph.cursor")

        # New events
        if fp.get("events") != self._last_fp.get("events"):
            changed_subjects.append("graph.events")

        self._last_fp = fp

        for subject in changed_subjects:
            self.relay.publish(subject, "changed")

    def _read_fingerprints(self) -> dict[str, str]:
        """Read lightweight fingerprints from the DB."""
        conn = self.state._get_conn()
        cursor = conn.cursor()
        fp: dict[str, str] = {}

        try:
            cursor.execute("SELECT count(*), max(rowid) FROM nodes")
            row = cursor.fetchone()
            fp["nodes"] = f"{row[0]}:{row[1]}"

            # Separate fingerprint for status changes
            cursor.execute(
                "SELECT group_concat(status) FROM "
                "(SELECT status FROM nodes WHERE status != 'orphaned' ORDER BY id)"
            )
            fp["node_status"] = str(cursor.fetchone()[0])

            cursor.execute("SELECT count(*), max(rowid) FROM edges")
            row = cursor.fetchone()
            fp["edges"] = f"{row[0]}:{row[1]}"

            cursor.execute("SELECT timestamp FROM cursor_focus WHERE id = 1")
            row = cursor.fetchone()
            fp["cursor"] = str(row[0]) if row else "0"

            cursor.execute("SELECT max(rowid) FROM events")
            fp["events"] = str(cursor.fetchone()[0])
        except Exception:
            pass  # Table may not exist yet

        return fp
```

### How Relay Subjects Map to Visual Updates

| Relay Subject | Trigger | Visual Update |
|---|---|---|
| `graph.topology` | Node discovered/removed, edge added | Full SVG re-render with new layout positions |
| `graph.status` | Node status changed (idle→running→idle) | SVG re-render (CSS transition animates color change) |
| `graph.cursor` | Cursor focus changed | SVG re-render (highlight ring moves to new node) |
| `graph.events` | New event in the event log | Event stream panel updates with new entries |

All of these result in `w.patch()` calls that send HTML fragments via SSE. Datastar morphs the existing DOM to match. CSS transitions handle the visual smoothness.

### `GraphState` Additions

The existing `GraphState` class needs one new method for the global event stream:

```python
# Added to remora_demo/graph/state.py

def read_recent_events(self, limit: int = 30) -> list[dict]:
    """Read the most recent events across all agents."""
    conn = self._get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT event_id, event_type, timestamp, correlation_id, agent_id,
               json_extract(payload, '$.message') as message,
               json_extract(payload, '$.content') as content
        FROM events
        ORDER BY timestamp DESC LIMIT ?
        """,
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]
```

### Request Flow Examples

**Initial page load:**
```
Browser GET /
  → index handler
  → state.read_snapshot()
  → layout.set_graph() + layout.step(150)
  → w.html(render_shell(snapshot, positions))
  → Full HTML page with embedded SVG, Datastar init, CSS

Browser auto-connects: data-on-load="@get('/subscribe')"
  → subscribe handler
  → w.patch(render_graph(snapshot, positions))  [initial full graph]
  → w.alive(relay.subscribe("graph.*"))  [wait for changes]
```

**User edits file in Neovim:**
```
Neovim: save file
  → LSP server: did_save → ASTWatcher → NodeDiscoveredEvent → EventStore → nodes table updated
  → LSP server: ContentChangedEvent → runner triggers agent → status → running

DB Bridge (300ms later): fingerprint changed
  → bridge._poll_once()
  → fp["nodes"] changed → graph.topology
  → fp["node_status"] changed → graph.status
  → relay.publish("graph.topology", "changed")
  → relay.publish("graph.status", "changed")

Subscribe handler: relay event received
  → snapshot = state.read_snapshot()
  → positions = layout.get_positions()  [layout already updated by bridge]
  → w.patch(render_graph(snapshot, positions))
  → SSE sends HTML fragment to browser
  → Datastar morphs DOM
  → CSS transition: node fill color changes smoothly to green (running)
```

**User clicks node in browser:**
```
Browser: click on SVG node group
  → Datastar action: @get('/agent/load_config')
  → agent_detail handler
  → state.read_node("load_config")
  → state.read_events_for_agent("load_config")
  → state.read_proposals_for_agent("load_config")
  → w.html(render_sidebar_content(...))
  → Response patches the sidebar div
```

**User sends chat from browser:**
```
Browser: click "Send" button
  → Datastar action: @post('/command')
  → post_command handler
  → state.push_command("chat", "load_config", {"message": "what do you do?"})
  → command_queue table written

LSP server: poll_command_queue() (1s interval)
  → reads command
  → _dispatch_command → HumanChatEvent → runner.trigger()
  → Agent executes → MockLLM responds
  → Events emitted to DB

DB Bridge (300ms later): fingerprint changed
  → relay.publish("graph.events", "changed")
  → relay.publish("graph.status", "changed")

Subscribe handler: patches event stream + graph
```

---

## 7. Graph Viewer: Client Implementation

### The Core Idea: Server-Rendered SVG + CSS Transitions

The server renders the entire graph as an SVG string. Each node is a `<g>` element positioned with `transform: translate(x, y)`. Each edge is a `<line>` or `<path>`. When positions or colors change, the server sends a new SVG via `w.patch()`. Datastar morphs the DOM (replacing the SVG content), and CSS `transition` properties make the change visually smooth.

There is **no JavaScript framework**. No d3. No React. No animation loop. The client-side code is:
1. Datastar (CDN script tag) — handles SSE connection, DOM morphing, signals, actions
2. ~30 lines of vanilla JS for click-to-select and keyboard shortcuts (optional)

### SVG Element Builders

Stario's `Tag` system works for HTML, but SVG elements need specific namespace handling. We create a small SVG builder module:

```python
"""remora_demo/graph/svg.py — SVG element builders for server-rendered graphs."""
from __future__ import annotations

from stario.html.core import Tag, render
from stario.html.safestring import SafeString


# SVG namespace elements — same API as Stario's Tag, but SVG-aware
Svg = Tag("svg")
G = Tag("g")
Circle = Tag("circle")
Line = Tag("line")
Text = Tag("text")
Rect = Tag("rect")
Path = Tag("path")
Defs = Tag("defs")
Filter = Tag("filter")
FeGaussianBlur = Tag("feGaussianBlur")
FeColorMatrix = Tag("feColorMatrix")
FeMerge = Tag("feMerge")
FeMergeNode = Tag("feMergeNode")
```

Stario's `Tag()` creates callables: `Circle(cx=100, cy=200, r=8, fill="#a6e3a1")` produces `<circle cx="100" cy="200" r="8" fill="#a6e3a1"></circle>`. The `render()` function turns the element tree into a string. Since `w.patch()` accepts `HtmlElement`, and SVG elements are valid HTML5, this works directly.

### View: `render_graph()`

This is the main rendering function. It takes a snapshot and layout positions and returns an SVG element tree.

```python
"""remora_demo/graph/views/graph.py — Server-rendered SVG graph."""
from __future__ import annotations

from stario.html.core import render
from stario.html.safestring import SafeString

from remora_demo.graph.svg import (
    Svg, G, Circle, Line, Text, Rect, Defs, Filter,
    FeGaussianBlur, FeColorMatrix, FeMerge, FeMergeNode,
)
from remora_demo.graph.state import GraphSnapshot

# Catppuccin Mocha palette
STATUS_FILL = {
    "active": "#a6e3a1",    # green
    "idle": "#6c7086",      # gray (most common resting state)
    "running": "#89b4fa",   # blue
    "pending_approval": "#f9e2af",  # yellow
    "error": "#f38ba8",     # red
    "orphaned": "#45475a",  # dark gray
}

NODE_RADIUS = {
    "file": 14,
    "class": 11,
    "function": 8,
    "method": 8,
}

EDGE_STYLE = {
    "parent_of": {"stroke": "#585b70", "width": 1.5, "opacity": 0.5, "dash": ""},
    "calls": {"stroke": "#89b4fa", "width": 1.0, "opacity": 0.4, "dash": "6,4"},
}


def render_graph(
    snapshot: GraphSnapshot,
    positions: dict[str, tuple[float, float]],
    cursor_focus: str | None = None,
    selected_node: str | None = None,
) -> SafeString:
    """Render the full SVG graph element.

    Returns a SafeString that can be passed to w.patch().
    The SVG has id="graph-svg" so Datastar can morph it in place.
    """
    # Build node lookup
    node_map = {}
    for n in snapshot.nodes:
        nid = n.get("remora_id") or n.get("id", "")
        node_map[nid] = n

    # Edges
    edge_elements = []
    for e in snapshot.edges:
        from_id = e.get("from_id", "")
        to_id = e.get("to_id", "")
        if from_id not in positions or to_id not in positions:
            continue
        x1, y1 = positions[from_id]
        x2, y2 = positions[to_id]
        edge_type = e.get("edge_type", "parent_of")
        style = EDGE_STYLE.get(edge_type, EDGE_STYLE["parent_of"])

        # Highlight edges connected to focused/selected node
        is_active = (cursor_focus and (from_id == cursor_focus or to_id == cursor_focus)) or \
                    (selected_node and (from_id == selected_node or to_id == selected_node))

        edge_elements.append(
            Line(
                x1=f"{x1:.1f}", y1=f"{y1:.1f}",
                x2=f"{x2:.1f}", y2=f"{y2:.1f}",
                stroke=style["stroke"],
                stroke_width=str(style["width"] + (1 if is_active else 0)),
                stroke_dasharray=style["dash"] or None,
                opacity=str(0.9 if is_active else style["opacity"]),
                class_="edge-line",
            )
        )

    # Nodes
    node_elements = []
    for nid, (x, y) in positions.items():
        n = node_map.get(nid, {})
        name = n.get("name", nid)
        node_type = n.get("node_type", "function")
        status = n.get("status", "idle")
        r = NODE_RADIUS.get(node_type, 8)
        fill = STATUS_FILL.get(status, "#6c7086")

        # Truncate long names
        display_name = name if len(name) <= 16 else name[:14] + ".."

        # Focus/selection state
        is_focused = nid == cursor_focus
        is_selected = nid == selected_node
        stroke = "#89b4fa" if is_focused else "#b4befe" if is_selected else "none"
        stroke_w = "3" if (is_focused or is_selected) else "0"

        # CSS filter for glow effect on focused node
        filter_attr = "url(#glow)" if is_focused else None

        group = G(
            transform=f"translate({x:.1f},{y:.1f})",
            class_="node-group",
            data_node_id=nid,
            data_on_click=f"@get('/agent/{nid}')",
        )(
            Circle(
                r=str(r),
                fill=fill,
                stroke=stroke,
                stroke_width=stroke_w,
                filter=filter_attr,
                class_="node-circle",
            ),
            Text(
                dy=str(r + 14),
                text_anchor="middle",
                class_="node-label",
                font_size="10px" if node_type == "file" else "9px",
            )(display_name),
        )
        node_elements.append(group)

    # SVG with glow filter definition
    glow_filter = Defs()(
        Filter(id="glow")(
            FeGaussianBlur(stdDeviation="3", result="blur"),
            FeColorMatrix(
                type="matrix",
                values="0 0 0 0 0.54  0 0 0 0 0.71  0 0 0 0 0.98  0 0 0 0.6 0",
                in_="blur",
                result="color",
            ),
            FeMerge()(
                FeMergeNode(in_="color"),
                FeMergeNode(in_="SourceGraphic"),
            ),
        )
    )

    svg = Svg(
        id="graph-svg",
        viewBox="0 0 900 600",
        xmlns="http://www.w3.org/2000/svg",
        class_="graph-svg",
    )(
        glow_filter,
        G(class_="edges")(*edge_elements),
        G(class_="nodes")(*node_elements),
    )

    return svg
```

### View: `render_shell()`

The shell is the full HTML page served on initial load. It sets up Datastar, loads CSS, and creates the layout structure.

```python
"""remora_demo/graph/views/shell.py — Full HTML shell."""
from __future__ import annotations

from stario.html.core import Tag

from remora_demo.graph.css import graph_css
from remora_demo.graph.views.graph import render_graph
from remora_demo.graph.state import GraphSnapshot

Html = Tag("html")
Head = Tag("head")
Body = Tag("body")
Meta = Tag("meta")
Title = Tag("title")
Style = Tag("style")
Script = Tag("script")
Div = Tag("div")
Header = Tag("header")
Button = Tag("button")


def render_shell(
    snapshot: GraphSnapshot,
    positions: dict[str, tuple[float, float]],
) -> ...:
    """Render the complete HTML page.

    The page structure:
    - Header bar with title and controls
    - Main area split into graph pane (left) and sidebar (right)
    - Datastar auto-connects to /subscribe for SSE updates
    """
    return Html(lang="en")(
        Head()(
            Meta(charset="UTF-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1.0"),
            Title()("Remora Graph"),
            Script(
                type="module",
                src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js",
            ),
            Style()(graph_css()),
        ),
        Body(
            data_on_load="@get('/subscribe')",
        )(
            Div(class_="app")(
                # Header
                Header(class_="header")(
                    Div(class_="header-title")("Remora Graph"),
                    Div(class_="header-controls")(
                        Div(class_="header-status", id="connection-status")("connecting..."),
                    ),
                ),
                # Main content
                Div(class_="main")(
                    # Graph pane
                    Div(class_="graph-pane", id="graph-pane")(
                        render_graph(snapshot, positions),
                    ),
                    # Sidebar
                    Div(class_="sidebar", id="sidebar")(
                        Div(id="sidebar-content")(
                            Div(class_="sidebar-empty")("Click a node to view details"),
                        ),
                    ),
                ),
            ),
        ),
    )
```

### CSS: Catppuccin Dark Theme + Transitions

All CSS lives in `remora_demo/graph/css.py`. The key innovation over v2 is the transition declarations on SVG elements.

```python
"""remora_demo/graph/css.py — All graph viewer CSS."""


def graph_css() -> str:
    return """
:root {
    --bg: #1e1e2e;
    --surface: #313244;
    --surface2: #45475a;
    --overlay: #585b70;
    --text: #cdd6f4;
    --subtext: #a6adc8;
    --green: #a6e3a1;
    --blue: #89b4fa;
    --yellow: #f9e2af;
    --red: #f38ba8;
    --gray: #6c7086;
    --lavender: #b4befe;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    background: var(--bg);
    color: var(--text);
    overflow: hidden;
    height: 100vh;
}

.app { display: flex; flex-direction: column; height: 100vh; }

/* ---- Header ---- */
.header {
    background: var(--surface);
    padding: 10px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--surface2);
    flex-shrink: 0;
}
.header-title { font-size: 14px; font-weight: 600; letter-spacing: 0.5px; }
.header-controls { display: flex; align-items: center; gap: 10px; }
.header-status {
    font-size: 11px; color: var(--gray);
    padding: 2px 8px; border-radius: 4px; background: var(--surface2);
}

/* ---- Layout ---- */
.main { display: flex; flex: 1; overflow: hidden; }
.graph-pane { flex: 1; position: relative; overflow: hidden; }
.graph-svg { width: 100%; height: 100%; }

/* ---- SVG Node transitions ---- */
/* THIS IS THE KEY: CSS transitions make server-side position changes smooth */
.node-group {
    transition: transform 0.5s ease-out;
    cursor: pointer;
}

.node-circle {
    transition: fill 0.3s ease, stroke 0.2s ease, stroke-width 0.2s ease;
}
.node-circle:hover {
    stroke-width: 3px;
    stroke: var(--lavender);
}

.node-label {
    font-family: 'JetBrains Mono', monospace;
    fill: var(--text);
    pointer-events: none;
    text-anchor: middle;
    transition: fill 0.3s ease;
}

.edge-line {
    transition: opacity 0.3s ease, stroke-width 0.3s ease;
    pointer-events: none;
}

/* ---- Running pulse animation ---- */
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
}

.node-circle[fill='#89b4fa'] {
    animation: pulse 1.5s ease-in-out infinite;
}

/* ---- Sidebar ---- */
.sidebar {
    width: 350px; background: var(--surface);
    border-left: 1px solid var(--surface2);
    overflow-y: auto; flex-shrink: 0;
}
.sidebar-empty {
    padding: 40px 20px; text-align: center;
    color: var(--gray); font-size: 13px;
}

/* (Sidebar sub-styles from existing shell.py — tabs, events, source, etc.) */
"""
```

### How CSS Transitions Work With Server-Rendered SVG

This is the critical mechanism that replaces d3-force animation:

1. **Server sends SVG with node at position (100, 200).** The `<g>` element has `transform="translate(100.0, 200.0)"`.
2. **Layout changes.** Node moves to (300, 250). Server sends new SVG via `w.patch()`.
3. **Datastar morphs the DOM.** The `<g>` element's `transform` attribute changes to `translate(300.0, 250.0)`.
4. **CSS transition kicks in.** `.node-group { transition: transform 0.5s ease-out; }` smoothly interpolates the position over 500ms.
5. **Result:** The node slides smoothly to its new position, identical to what d3-force would do.

Same for colors: when a node goes from `idle` (gray fill) to `running` (blue fill), the `fill` attribute changes, and `.node-circle { transition: fill 0.3s ease; }` smoothly blends the color.

The pulse animation for running nodes uses a CSS `@keyframes` rule that targets circles with the specific blue fill color. When the node stops running and the fill changes, the animation stops naturally because the selector no longer matches.

### What About Zoom/Pan?

The v2 viewer uses d3-zoom for zoom and pan. With server-rendered SVG, we have two options:

**Option A: CSS `overflow: auto` with native scroll.** The SVG has a fixed `viewBox` and the container allows scrolling. Simple but not as smooth as pinch-zoom.

**Option B: Minimal vanilla JS for zoom/pan.** ~20 lines of JS that applies a `transform` to the SVG root group on wheel/drag events. This doesn't conflict with Datastar — it modifies a wrapper `<g>` that Datastar doesn't touch.

**Decision: Option B** — a tiny JS snippet for zoom/pan, embedded in the shell. It's not a framework, just event handlers.

```javascript
// Embedded in shell.py as a <script> block
(function() {
    let scale = 1, tx = 0, ty = 0;
    const pane = document.getElementById('graph-pane');
    const svg = document.getElementById('graph-svg');

    // Wheel zoom
    pane.addEventListener('wheel', function(e) {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 0.9 : 1.1;
        scale = Math.max(0.2, Math.min(4, scale * factor));
        svg.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    }, { passive: false });

    // Drag pan
    let dragging = false, startX = 0, startY = 0;
    pane.addEventListener('mousedown', function(e) {
        if (e.target.closest('.node-group')) return; // Don't pan on node click
        dragging = true; startX = e.clientX - tx; startY = e.clientY - ty;
    });
    pane.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        tx = e.clientX - startX; ty = e.clientY - startY;
        svg.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    });
    window.addEventListener('mouseup', function() { dragging = false; });
})();
```

This modifies `svg.style.transform` which is a CSS property on the SVG element itself. Datastar morphs the SVG content (child elements) but doesn't touch inline styles, so there's no conflict.

### Node Visual States

| Status | Fill Color | Animation | Stroke |
|--------|-----------|-----------|--------|
| `idle` | `#6c7086` (gray) | None | None |
| `active` | `#a6e3a1` (green) | None | None |
| `running` | `#89b4fa` (blue) | Pulse 1.5s | None |
| `pending_approval` | `#f9e2af` (yellow) | None | None |
| `error` | `#f38ba8` (red) | None | None |
| Cursor focus | (any) | None | `#89b4fa` 3px + glow filter |
| Selected | (any) | None | `#b4befe` 3px |

---

## 8. Graph Viewer: Sidebar and Interaction

### Overview

The sidebar is the right panel (350px wide) that shows details about the selected node and provides interaction controls. It has four tabs: **Log**, **Source**, **Connections**, and **Actions**. The Actions tab is the most important for the demo — it contains the chat input and proposal approve/reject buttons.

The existing v2 sidebar (`remora_demo/graph/sidebar.py`) already implements this structure as raw HTML string concatenation. The new version rewrites it using Stario's `Tag` system for type-safe HTML generation, and replaces the JavaScript onclick handlers with Datastar actions (`@post`, `@get`).

### View: `render_sidebar_content()`

```python
"""remora_demo/graph/views/sidebar.py — Sidebar detail panel for selected node."""
from __future__ import annotations

import datetime
import html as html_mod

from stario.html.core import Tag

# HTML tag factories
Div = Tag("div")
Span = Tag("span")
Button = Tag("button")
Pre = Tag("pre")
Code = Tag("code")
TextArea = Tag("textarea")
Input = Tag("input")


STATUS_COLORS = {
    "active": "#a6e3a1",
    "idle": "#6c7086",
    "running": "#89b4fa",
    "pending_approval": "#f9e2af",
    "error": "#f38ba8",
    "orphaned": "#45475a",
}


def render_sidebar_content(
    node: dict | None,
    events: list[dict],
    proposals: list[dict],
    connections: dict,
) -> ...:
    """Render the sidebar content for a selected node.

    This replaces the entire #sidebar-content div via Datastar morph.
    Returns a Stario element tree.
    """
    if not node:
        return Div(id="sidebar-content")(
            Div(class_="sidebar-empty")("Node not found"),
        )

    nid = node.get("remora_id", "")
    name = node.get("name", "unknown")
    node_type = node.get("node_type", "unknown")
    status = node.get("status", "idle")
    file_path = node.get("file_path", "")
    start_line = node.get("start_line", "?")
    end_line = node.get("end_line", "?")
    source = node.get("source_code", "")
    color = STATUS_COLORS.get(status, "#6c7086")

    return Div(id="sidebar-content")(
        # Node info header
        _render_header(name, node_type, status, color),
        # Metadata
        _render_meta(nid, file_path, start_line, end_line),
        # Tab bar
        _render_tabs(),
        # Tab content panels
        _render_log_tab(events),
        _render_source_tab(source),
        _render_connections_tab(connections, nid),
        _render_actions_tab(nid, proposals),
    )


def _render_header(name: str, node_type: str, status: str, color: str) -> ...:
    return Div(class_="node-info-header")(
        Span(class_="node-info-name")(html_mod.escape(name)),
        Span(class_="node-info-type")(node_type),
        Span(
            class_="node-info-status",
            style=f"background:{color};color:#1e1e2e",
        )(status),
    )


def _render_meta(nid: str, file_path: str, start_line, end_line) -> ...:
    return Div(class_="sidebar-section")(
        Div(class_="meta-line")(
            Span(class_="meta-label")("ID:"),
            Code()(html_mod.escape(nid)),
        ),
        Div(class_="meta-line")(
            Span(class_="meta-label")("File:"),
            Span()(html_mod.escape(file_path)),
        ),
        Div(class_="meta-line")(
            Span(class_="meta-label")("Lines:"),
            Span()(f"{start_line}-{end_line}"),
        ),
    )


def _render_tabs() -> ...:
    """Tab bar. Uses Datastar signals to switch visible tab."""
    return Div(class_="sidebar-tabs")(
        Button(
            class_="sidebar-tab",
            data_on_click="$activeTab = 'log'",
        )("Log"),
        Button(
            class_="sidebar-tab",
            data_on_click="$activeTab = 'source'",
        )("Source"),
        Button(
            class_="sidebar-tab",
            data_on_click="$activeTab = 'connections'",
        )("Connections"),
        Button(
            class_="sidebar-tab",
            data_on_click="$activeTab = 'actions'",
        )("Actions"),
    )


def _render_log_tab(events: list[dict]) -> ...:
    """Agent event log — most recent first."""
    if not events:
        items = [Div(class_="sidebar-empty", style="padding:12px")("No events yet")]
    else:
        items = []
        for ev in events[:15]:
            et = html_mod.escape(str(ev.get("event_type", "")))
            ts = ev.get("timestamp", 0)
            # Extract a one-line summary from payload
            message = ev.get("message") or ev.get("content") or ""
            if message and len(message) > 80:
                message = message[:77] + "..."

            items.append(
                Div(class_="event-item")(
                    Span(class_="event-badge")(et),
                    Span(class_="event-time")(_format_time(ts)),
                    Span(class_="event-summary")(
                        html_mod.escape(message)
                    ) if message else "",
                )
            )

    return Div(
        class_="sidebar-section tab-content",
        data_show="$activeTab == 'log'",
    )(*items)


def _render_source_tab(source: str) -> ...:
    """Agent source code (read-only view)."""
    if source:
        content = Pre(class_="source-block")(Code()(html_mod.escape(source)))
    else:
        content = Div(class_="sidebar-empty", style="padding:12px")(
            "No source code",
        )

    return Div(
        class_="sidebar-section tab-content",
        data_show="$activeTab == 'source'",
    )(content)


def _render_connections_tab(connections: dict, current_nid: str) -> ...:
    """Graph connections — clickable links to related nodes."""
    sections = []
    for label, key in [
        ("Parents", "parents"),
        ("Children", "children"),
        ("Callers", "callers"),
        ("Callees", "callees"),
    ]:
        items = connections.get(key, [])
        if items:
            section_items = [
                Div(class_="connections-label")(label),
            ]
            for item_id in items:
                escaped = html_mod.escape(item_id)
                section_items.append(
                    Div(
                        class_="connection-item",
                        data_on_click=f"@get('/agent/{escaped}')",
                    )(escaped),
                )
            sections.extend(section_items)

    if not sections:
        sections = [
            Div(class_="sidebar-empty", style="padding:12px")("No connections"),
        ]

    return Div(
        class_="sidebar-section tab-content",
        data_show="$activeTab == 'connections'",
    )(*sections)


def _render_actions_tab(nid: str, proposals: list[dict]) -> ...:
    """Chat input + proposal approve/reject buttons."""
    escaped_nid = html_mod.escape(nid)

    parts = []

    # Chat input
    parts.append(
        Div(class_="actions-group")(
            Div(class_="actions-label")("Send Message"),
            TextArea(
                class_="chat-input",
                placeholder="Message to agent...",
                data_model="chatMessage",
                rows="3",
            ),
            Button(
                class_="action-btn primary",
                data_on_click=(
                    f"@post('/command', {{"
                    f"signals: {{command_type: 'chat', agent_id: '{escaped_nid}', "
                    f"payload: JSON.stringify({{message: $chatMessage}})}}"
                    f"}})"
                ),
            )("Send"),
        )
    )

    # Pending proposals
    if proposals:
        parts.append(Div(class_="actions-label")("Pending Proposals"))
        for p in proposals:
            pid = html_mod.escape(str(p.get("proposal_id", "")))
            diff = html_mod.escape(str(p.get("diff", "")))
            parts.append(
                Div(class_="proposal-card")(
                    Div(class_="proposal-id")(f"ID: {pid}"),
                    Pre(class_="proposal-diff")(diff),
                    Div(class_="proposal-actions")(
                        Button(
                            class_="action-btn approve",
                            data_on_click=(
                                f"@post('/command', {{"
                                f"signals: {{command_type: 'approve', "
                                f"agent_id: '{escaped_nid}', "
                                f"payload: JSON.stringify({{proposal_id: '{pid}'}})}}"
                                f"}})"
                            ),
                        )("Approve"),
                        Button(
                            class_="action-btn danger",
                            data_on_click=(
                                f"@post('/command', {{"
                                f"signals: {{command_type: 'reject', "
                                f"agent_id: '{escaped_nid}', "
                                f"payload: JSON.stringify({{proposal_id: '{pid}'}})}}"
                                f"}})"
                            ),
                        )("Reject"),
                    ),
                )
            )

    return Div(
        class_="sidebar-section tab-content",
        data_show="$activeTab == 'actions'",
    )(*parts)


def _format_time(ts: float) -> str:
    if not ts:
        return ""
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S")
```

### View: `render_event_list()`

The global event stream shows recent events across all agents, visible as a scrollable log at the bottom of the sidebar or as a separate panel. This is the "firehose" view — it shows every event in the system, not filtered to a single agent.

```python
"""remora_demo/graph/views/event_stream.py — Global event stream rendering."""
from __future__ import annotations

import datetime
import html as html_mod

from stario.html.core import Tag

Div = Tag("div")
Span = Tag("span")


EVENT_TYPE_COLORS = {
    "NodeDiscovered": "#a6e3a1",      # green — something appeared
    "NodeRemoved": "#6c7086",         # gray — something disappeared
    "AgentStart": "#89b4fa",          # blue — agent activated
    "AgentComplete": "#a6e3a1",       # green — agent finished
    "AgentError": "#f38ba8",          # red — error
    "ContentChanged": "#f9e2af",      # yellow — file changed
    "ModelRequest": "#cba6f7",        # mauve — LLM call
    "ModelResponse": "#cba6f7",       # mauve — LLM response
    "AgentMessage": "#89dceb",        # sky — inter-agent comm
    "HumanChat": "#fab387",           # peach — human interaction
    "RewriteProposal": "#f9e2af",     # yellow — proposal created
    "RewriteApplied": "#a6e3a1",      # green — proposal accepted
    "RewriteRejected": "#f38ba8",     # red — proposal rejected
}


def render_event_list(events: list[dict]) -> ...:
    """Render the global event stream as a scrollable list.

    Target element: #event-stream. Updated by w.patch() on graph.events.
    """
    if not events:
        return Div(id="event-stream", class_="event-stream")(
            Div(class_="sidebar-empty")("No events yet"),
        )

    items = []
    for ev in events:
        et = ev.get("event_type", "Unknown")
        agent_id = ev.get("agent_id", "")
        ts = ev.get("timestamp", 0)
        correlation_id = ev.get("correlation_id", "")

        # Extract human-readable summary
        message = ev.get("message") or ev.get("content") or ""
        if isinstance(message, str) and len(message) > 100:
            message = message[:97] + "..."

        color = EVENT_TYPE_COLORS.get(et, "#6c7086")

        items.append(
            Div(class_="event-stream-item")(
                Div(class_="event-stream-header")(
                    Span(
                        class_="event-badge",
                        style=f"background:{color};color:#1e1e2e",
                    )(et),
                    Span(class_="event-agent")(
                        html_mod.escape(agent_id),
                    ) if agent_id else "",
                    Span(class_="event-time")(
                        _format_time(ts),
                    ),
                ),
                Div(class_="event-stream-body")(
                    html_mod.escape(message),
                ) if message else "",
            )
        )

    return Div(id="event-stream", class_="event-stream")(*items)


def _format_time(ts: float) -> str:
    if not ts:
        return ""
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}"
```

### CSS Additions for Sidebar

These styles are appended to the `graph_css()` function in `css.py`:

```python
# Added to graph_css() return string:
"""
/* ---- Sidebar content ---- */
.node-info-header {
    padding: 12px 16px;
    display: flex; align-items: center; gap: 8px;
    border-bottom: 1px solid var(--surface2);
}
.node-info-name { font-size: 14px; font-weight: 600; }
.node-info-type {
    font-size: 10px; color: var(--subtext);
    padding: 1px 6px; border-radius: 3px; background: var(--surface2);
}
.node-info-status {
    font-size: 10px; padding: 1px 6px; border-radius: 3px;
    margin-left: auto;
}

.meta-line {
    font-size: 11px; color: var(--subtext);
    padding: 2px 16px;
}
.meta-label { font-weight: 600; margin-right: 4px; }

/* ---- Tabs ---- */
.sidebar-tabs {
    display: flex; border-bottom: 1px solid var(--surface2);
    padding: 0 8px;
}
.sidebar-tab {
    background: none; border: none; color: var(--subtext);
    font-family: inherit; font-size: 11px; padding: 8px 10px;
    cursor: pointer; border-bottom: 2px solid transparent;
    transition: color 0.2s, border-color 0.2s;
}
.sidebar-tab:hover { color: var(--text); }
.sidebar-tab[aria-selected="true"] {
    color: var(--blue); border-bottom-color: var(--blue);
}

.tab-content { padding: 8px 16px; }

/* ---- Event items (per-agent log) ---- */
.event-item {
    padding: 4px 0;
    border-bottom: 1px solid var(--surface2);
    display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
}
.event-badge {
    font-size: 9px; padding: 1px 5px; border-radius: 3px;
    background: var(--surface2); color: var(--text);
    font-weight: 600; white-space: nowrap;
}
.event-time {
    font-size: 10px; color: var(--overlay); margin-left: auto;
}
.event-summary {
    font-size: 10px; color: var(--subtext);
    width: 100%; padding-left: 2px;
}

/* ---- Connections ---- */
.connections-label {
    font-size: 11px; color: var(--subtext); font-weight: 600;
    margin: 8px 0 4px;
}
.connection-item {
    font-size: 12px; padding: 3px 8px; border-radius: 4px;
    cursor: pointer; transition: background 0.2s;
}
.connection-item:hover { background: var(--surface2); }

/* ---- Actions ---- */
.actions-group { margin-bottom: 16px; }
.actions-label {
    font-size: 11px; color: var(--subtext); font-weight: 600;
    margin-bottom: 6px;
}
.chat-input {
    width: 100%; background: var(--bg); border: 1px solid var(--surface2);
    border-radius: 4px; color: var(--text); font-family: inherit;
    font-size: 12px; padding: 8px; resize: vertical;
}
.chat-input:focus { border-color: var(--blue); outline: none; }

.action-btn {
    background: var(--surface2); border: none; color: var(--text);
    font-family: inherit; font-size: 11px; padding: 6px 12px;
    border-radius: 4px; cursor: pointer; transition: background 0.2s;
}
.action-btn:hover { background: var(--overlay); }
.action-btn.primary { background: var(--blue); color: #1e1e2e; }
.action-btn.primary:hover { opacity: 0.9; }
.action-btn.approve { background: var(--green); color: #1e1e2e; }
.action-btn.danger { background: var(--red); color: #1e1e2e; }

/* ---- Proposals ---- */
.proposal-card {
    background: var(--bg); border: 1px solid var(--surface2);
    border-radius: 6px; padding: 8px; margin-bottom: 8px;
}
.proposal-id { font-size: 10px; color: var(--subtext); margin-bottom: 4px; }
.proposal-diff {
    font-size: 10px; background: var(--surface2); padding: 6px;
    border-radius: 3px; overflow-x: auto; max-height: 200px;
    overflow-y: auto; margin: 4px 0;
}
.proposal-actions { display: flex; gap: 4px; margin-top: 6px; }
.proposal-actions .action-btn { flex: 1; text-align: center; }

/* ---- Source block ---- */
.source-block {
    font-size: 11px; background: var(--bg); padding: 8px;
    border-radius: 4px; overflow-x: auto; overflow-y: auto;
    max-height: 400px; border: 1px solid var(--surface2);
}

/* ---- Global event stream ---- */
.event-stream {
    max-height: 300px; overflow-y: auto;
    border-top: 1px solid var(--surface2);
}
.event-stream-item {
    padding: 6px 12px;
    border-bottom: 1px solid var(--surface2);
}
.event-stream-header {
    display: flex; align-items: center; gap: 6px;
}
.event-stream-body {
    font-size: 10px; color: var(--subtext); padding: 2px 0 0 2px;
    white-space: pre-wrap; word-break: break-word;
}
.event-agent {
    font-size: 10px; color: var(--lavender);
}
"""
```

### Interaction Patterns

The sidebar uses Datastar signals and actions exclusively — no custom JavaScript event handlers.

**Tab switching:**
The `$activeTab` signal is a Datastar signal initialized in the shell. Each tab content div has `data-show="$activeTab == 'log'"` which Datastar evaluates to show/hide panels. Tab buttons set the signal via `data-on-click="$activeTab = 'log'"`. The signal must be initialized in the shell's `<body>` tag:

```python
# In render_shell(), the body tag becomes:
Body(
    data_on_load="@get('/subscribe')",
    data_signals='{"activeTab": "log", "chatMessage": ""}',
)
```

**Chat submission:**
The chat textarea binds to `$chatMessage` via `data-model="chatMessage"`. The Send button posts to `/command` with signals containing `command_type`, `agent_id`, and payload. The handler writes to `command_queue`, which the LSP server polls.

**Proposal approve/reject:**
Each proposal card has Approve and Reject buttons that post to `/command` with the appropriate `command_type` and `proposal_id` in the payload. The LSP server's `poll_command_queue()` dispatches these the same way Neovim commands do.

**Node navigation:**
Connection items use `data-on-click="@get('/agent/{id}')"` to load a different agent's sidebar. This fires a Datastar GET request, and the response replaces `#sidebar-content`.

### Datastar Signal Flow

```
User clicks tab button
  → data-on-click="$activeTab = 'actions'"
  → Datastar updates signal
  → data-show="$activeTab == 'actions'" evaluates to true
  → Panel becomes visible (CSS display)

User types in chat textarea
  → data-model="chatMessage"
  → Datastar binds textarea value to $chatMessage signal

User clicks Send
  → data-on-click="@post('/command', {signals: {...}})"
  → Datastar sends POST with signals as body
  → Handler reads signals via c.signals(CommandSignals)
  → Writes to command_queue table
  → Response is empty (or confirmation)

LSP server picks up command (1s poll):
  → poll_command_queue() reads pending commands
  → Dispatches as HumanChatEvent → runner.trigger()
  → Events emitted to DB
  → Bridge detects change → Relay publish
  → SSE handler sends updated event stream via w.patch()
```

### Integration with Global Event Stream

The event stream panel is rendered by `render_event_list()` and lives in a `#event-stream` div. It can be placed either:

1. **At the bottom of the sidebar** — below the tab content, always visible. Shows the last 10-15 events.
2. **As a footer bar** — at the bottom of the full page, spanning the entire width.

For the demo, option 1 is simpler. The shell template includes the event stream below the sidebar tabs:

```python
# In render_shell() — sidebar section:
Div(class_="sidebar", id="sidebar")(
    Div(id="sidebar-content")(
        Div(class_="sidebar-empty")("Click a node to view details"),
    ),
    Div(class_="sidebar-divider"),
    Div(class_="sidebar-section-title")("Event Stream"),
    Div(id="event-stream", class_="event-stream")(
        Div(class_="sidebar-empty")("Waiting for events..."),
    ),
),
```

The SSE handler patches `#event-stream` independently from `#sidebar-content`. When `graph.events` fires, only the event stream updates. When a user clicks a node, only the sidebar content updates. The two are independent DOM regions.

---

## 9. Cursor Tracking Integration

### The Full Pipeline

Cursor tracking is the "magic" moment in the demo — the user moves their cursor in Neovim, and the corresponding graph node highlights in real-time in the browser. This is golden path beat 4. The latency budget is 300ms (cursor move to visual highlight).

```
Neovim (CursorHold event, 300ms idle)
  → Lua plugin sends $/remora/cursorMoved { uri, line }
  → LSP server: notifications.py on_cursor_moved()
  → EventStore.get_node_at_position(uri, line) → AgentNode or None
  → RemoraDB.update_cursor_focus(agent_id, uri, line) → writes cursor_focus table
  → (300ms later) Graph viewer bridge polls DB
  → bridge._read_fingerprints() detects cursor_focus timestamp changed
  → relay.publish("graph.cursor", "changed")
  → SSE handler: snapshot = state.read_snapshot() (includes cursor_focus)
  → w.patch(render_graph(snapshot, positions, cursor_focus=agent_id))
  → Datastar morphs DOM: node's stroke changes to #89b4fa 3px + glow filter
  → CSS transition: stroke 0.2s ease → smooth highlight appearance
```

Total worst-case latency: 300ms (CursorHold) + 300ms (bridge poll) = 600ms. Typical: ~450ms. This is perceptible but acceptable for a demo. If needed, the bridge poll interval can be reduced to 100ms for cursor tracking.

### Neovim Side: CursorHold Notification

The Neovim plugin already sends this notification. The relevant Lua code in the remora plugin:

```lua
-- In the remora.nvim plugin (already exists)
vim.api.nvim_create_autocmd("CursorHold", {
    callback = function()
        local buf = vim.api.nvim_get_current_buf()
        local uri = vim.uri_from_bufnr(buf)
        local line = vim.api.nvim_win_get_cursor(0)[1]  -- 1-indexed
        vim.lsp.buf_notify(buf, "$/remora/cursorMoved", {
            uri = uri,
            line = line,
        })
    end,
})
```

`CursorHold` fires after `updatetime` milliseconds of cursor inactivity (default 4000ms, but Remora recommends setting to 300ms in the plugin setup). This debounces cursor tracking naturally — we don't send notifications while the user is actively typing.

### LSP Server Side: `on_cursor_moved()`

The handler in `notifications.py` (already exists, shown in the context reading) does:

1. Extracts `uri` and `line` from params.
2. Calls `server.event_store.get_node_at_position(uri, line)` to find which agent covers that line.
3. Writes the result to `cursor_focus` table via `server.db.update_cursor_focus(agent_id, uri, line)`.

**Current implementation already works.** The only prerequisite is that `get_node_at_position()` exists on EventStore (Option A task 1, required for demo).

### `get_node_at_position()` Implementation

This is Option A task 1. The method queries the `nodes` table for a node whose `file_path` matches the URI and whose `start_line <= line <= end_line`:

```python
# In src/remora/core/event_store.py

async def get_node_at_position(self, file_path: str, line: int) -> AgentNode | None:
    """Find the most specific node containing the given line position.

    When multiple nodes contain the line (e.g., a function inside a file),
    returns the one with the smallest span (most specific).
    """
    def _query():
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT * FROM nodes
            WHERE file_path = ? AND start_line <= ? AND end_line >= ?
            AND status != 'orphaned'
            ORDER BY (end_line - start_line) ASC
            LIMIT 1
            """,
            (file_path, line, line),
        )
        row = cursor.fetchone()
        if row:
            return AgentNode.from_row(dict(row))
        return None

    return await asyncio.to_thread(_query)
```

The `ORDER BY (end_line - start_line) ASC` ensures that when a function is inside a file (both match the line), the function (smaller span) wins. This is the correct behavior — cursor on a function should highlight the function node, not the file node.

### `cursor_focus` Table Schema

Already exists in RemoraDB:

```sql
CREATE TABLE IF NOT EXISTS cursor_focus (
    id INTEGER PRIMARY KEY DEFAULT 1,
    agent_id TEXT,
    file_path TEXT,
    line INTEGER,
    timestamp REAL
);
```

Single row (id=1), updated on each cursor move. The graph viewer reads this as part of `read_snapshot()`:

```python
# Already in GraphState.read_snapshot():
cursor.execute("SELECT agent_id, file_path, line, timestamp FROM cursor_focus WHERE id = 1")
row = cursor.fetchone()
cursor_focus = dict(row) if row else None
```

### Bridge Detection

The bridge fingerprints the cursor_focus table by its timestamp:

```python
# In bridge._read_fingerprints():
cursor.execute("SELECT timestamp FROM cursor_focus WHERE id = 1")
row = cursor.fetchone()
fp["cursor"] = str(row[0]) if row else "0"
```

When the timestamp changes, the bridge publishes `graph.cursor`. The subscribe handler then re-renders the graph with the updated `cursor_focus` parameter.

### Graph Rendering with Cursor Focus

The `render_graph()` function already accepts `cursor_focus: str | None` (Section 7). When a node's ID matches `cursor_focus`, it gets:

1. **A bright blue stroke** (`#89b4fa`, 3px width) around the circle.
2. **A glow filter** (`url(#glow)`) — an SVG feGaussianBlur + feColorMatrix that creates a soft blue halo.
3. **Connected edges brighten** — edges touching the focused node increase opacity from 0.4 to 0.9 and gain +1px stroke width.

The CSS transitions handle the visual smoothness:
- `stroke` and `stroke-width` on `.node-circle` transition over 0.2s
- `opacity` and `stroke-width` on `.edge-line` transition over 0.3s

### Threading the Cursor Focus Through the Subscribe Handler

The subscribe handler needs to extract `cursor_focus` from the snapshot and pass it to `render_graph()`. Updated handler:

```python
# Updated subscribe handler (in handlers.py):
async for subject, change_type in w.alive(relay.subscribe("graph.*")):
    snapshot = state.read_snapshot()
    positions = layout.get_positions()

    # Extract cursor focus agent_id from snapshot
    cursor_agent = snapshot.cursor_focus.get("agent_id") if snapshot.cursor_focus else None

    if subject in ("graph.topology", "graph.status", "graph.cursor"):
        w.patch(render_graph(snapshot, positions, cursor_focus=cursor_agent))
    elif subject == "graph.events":
        events = state.read_recent_events(limit=30)
        w.patch(render_event_list(events))
```

### Viewport Panning (Optional Enhancement)

For the demo, it would be impressive if the graph viewport automatically panned to center the focused node. This requires a small JS addition:

```javascript
// Added to the zoom/pan script in shell.py
// Called after Datastar morphs the graph SVG
const observer = new MutationObserver(() => {
    const focused = document.querySelector('.node-circle[stroke="#89b4fa"]');
    if (focused) {
        const group = focused.parentElement;
        // Extract translate from transform attribute
        const match = group.getAttribute('transform')?.match(/translate\(([^,]+),([^)]+)\)/);
        if (match) {
            const nx = parseFloat(match[1]), ny = parseFloat(match[2]);
            const pane = document.getElementById('graph-pane');
            const rect = pane.getBoundingClientRect();
            // Smoothly pan to center the focused node
            const targetTx = rect.width / 2 - nx * scale;
            const targetTy = rect.height / 2 - ny * scale;
            // Animate with requestAnimationFrame
            const animate = () => {
                tx += (targetTx - tx) * 0.1;
                ty += (targetTy - ty) * 0.1;
                document.getElementById('graph-svg').style.transform =
                    `translate(${tx}px,${ty}px) scale(${scale})`;
                if (Math.abs(targetTx - tx) > 1 || Math.abs(targetTy - ty) > 1) {
                    requestAnimationFrame(animate);
                }
            };
            requestAnimationFrame(animate);
        }
    }
});
observer.observe(document.getElementById('graph-pane'), { childList: true, subtree: true });
```

This is ~25 lines of vanilla JS. It watches for DOM mutations (triggered by Datastar morph), finds the focused node by its stroke color, and smoothly pans the viewport to center it. The `0.1` lerp factor gives a smooth ease-out feel. This is completely optional — the demo works without it, but the smooth auto-pan makes beat 4 much more impressive.

### Latency Optimization

If 600ms worst-case feels too slow during the demo, we have two levers:

1. **Reduce bridge poll interval** to 100ms (from 300ms). This adds ~10% CPU usage but cuts response time to ~400ms. The bridge can use a faster interval specifically for cursor tracking by fingerprinting cursor_focus separately and at a higher frequency.

2. **Reduce Neovim `updatetime`** to 100ms. This makes CursorHold fire sooner. The trade-off is more LSP notifications, but `get_node_at_position()` is a fast indexed query.

For the demo script, we'll recommend `updatetime=300` which gives good responsiveness without excessive traffic.

---

## 10. LSP Server Modifications

### Scope

The LSP server needs modifications in two categories:

1. **Option A migration tasks (1-10)** — Moving from `ASTAgentNode + RemoraDB` to `AgentNode + EventStore` as the single source of truth for node state. These are detailed in `.scratch/option-a-plan.md` and tracked in `.scratch/CRITICAL_RULES.md`.

2. **Demo-specific additions** — MockLLM selection, command queue polling, event bridging. Small changes on top of the migration.

This section focuses on the demo-specific changes. The Option A migration tasks are defined elsewhere and executed independently.

### Change 1: MockLLM Selection in Server Startup

The server must instantiate `MockLLMClient` when `model_default` is `"mock"`. This happens during runner creation in `server.py` (or in the `__main__.py` entry point that creates the server).

**File: `src/remora/lsp/server.py`**

```python
# In RemoraLanguageServer.__init__() or a setup method:

async def setup_runner(self) -> None:
    """Create the AgentRunner with the appropriate LLM client."""
    from remora.core.config import load_config
    config = load_config()

    if config.model_default == "mock":
        from remora_demo.mock_llm import MockLLMClient
        llm = MockLLMClient()
        logger.info("Using MockLLMClient for demo mode")
    else:
        from remora.lsp.runner import LLMClient
        llm = LLMClient(
            base_url=config.model_base_url,
            model=config.model_default,
        )
        logger.info("Using LLMClient: %s @ %s", config.model_default, config.model_base_url)

    from remora.lsp.runner import AgentRunner
    self.runner = AgentRunner(self, llm=llm)
```

This replaces the current hardcoded runner creation. The `remora_demo` package is only imported when `model_default == "mock"`, so the demo dependency is lazy.

### Change 2: Event Bridging in `emit_event()`

The current `emit_event()` method on `RemoraLanguageServer` already bridges LSP events to the EventStore:

```python
# Current implementation (server.py:55-70):
async def emit_event(self, event) -> Any:
    if not getattr(event, "timestamp", None):
        event.timestamp = time.time()
    await self.db.store_event(event)          # RemoraDB events table

    if self.event_store:
        try:
            core_event = event.to_core_event()
        except NotImplementedError:
            core_event = None
        else:
            if core_event:
                await self.event_store.append("swarm", core_event)

    self.protocol.notify("$/remora/event", event.model_dump())
    return event
```

This is already correct for the demo. LSP model events (from `lsp/models.py`) that implement `to_core_event()` get bridged to the EventStore, which the graph viewer reads. Events that don't implement `to_core_event()` still get stored in RemoraDB's `events` table, which the graph viewer also reads.

**No changes needed here.** The existing dual-write approach works for the demo.

### Change 3: Ensure All Golden Path Events Are Bridged

The golden path requires these event types to appear in the graph viewer:

| LSP Event | Core Event | Bridged? |
|---|---|---|
| `HumanChatEvent` | `HumanChatEvent` (same) | Yes — already in `events.py` |
| `AgentStartEvent` | `AgentStartEvent` | Yes |
| `ModelRequestEvent` | `ModelRequestEvent` | Yes |
| `ModelResponseEvent` | `ModelResponseEvent` | Yes |
| `AgentMessageEvent` | `AgentMessageEvent` | Yes |
| `RewriteProposalEvent` | `RewriteProposalEvent` | Yes |
| `RewriteAppliedEvent` | `RewriteAppliedEvent` | Yes |
| `ContentChangedEvent` | `ContentChangedEvent` | Yes |
| `AgentCompleteEvent` | `AgentCompleteEvent` | Yes |

All of these have `to_core_event()` implementations. The graph viewer reads events from either the EventStore's events table or RemoraDB's events table (it queries both, or just RemoraDB since that's where `state.py` currently reads from).

**Decision:** For the demo, the graph viewer reads events from RemoraDB's `events` table (the existing `read_events_for_agent()` and `read_recent_events()` methods). This avoids needing to add event query methods to EventStore. Post-demo, we can migrate event reads to EventStore too.

### Change 4: `notifications.py` — Use EventStore for Cursor Tracking

Already discussed in Section 9. The current code already uses `server.event_store.get_node_at_position()`:

```python
# notifications.py:21 (already correct):
node = await server.event_store.get_node_at_position(uri, line)
```

The only prerequisite is implementing `get_node_at_position()` on EventStore (Option A task 1).

### Change 5: Command Queue Polling in the Runner

The runner already has `poll_command_queue()` which runs as a background task:

```python
# runner.py:160-180 (already exists):
async def poll_command_queue(self) -> None:
    """Poll the command_queue table and dispatch commands."""
    while True:
        await asyncio.sleep(1.0)
        try:
            commands = await self.server.db.poll_commands(limit=5)
            for cmd in commands:
                await self._dispatch_command(cmd)
        except Exception:
            logger.debug("Command poll error", exc_info=True)
```

The `_dispatch_command()` method handles `chat`, `approve`, `reject`, and `focus` command types. For the demo, we need to ensure these are wired correctly:

| Command Type | Source | Action |
|---|---|---|
| `chat` | Browser Send button | Emit `HumanChatEvent`, call `runner.trigger(agent_id, correlation_id)` |
| `approve` | Browser Approve button | Apply the proposal via `workspace/applyEdit`, emit `RewriteAppliedEvent` |
| `reject` | Browser Reject button | Emit `RewriteRejectedEvent`, optionally trigger agent with feedback |
| `focus` | Browser node click | Update cursor_focus table (for bidirectional highlight sync) |

**The existing `_dispatch_command()` implementation handles `chat` and `approve`/`reject`.** We may need to add `focus` handling if we want browser clicks to sync back to Neovim (optional for demo).

### Change 6: `documents.py` — Emit Events to EventStore

The `did_open` and `did_save` handlers in `documents.py` currently use the ASTWatcher to discover nodes and write them to RemoraDB. For the demo, they need to also emit `NodeDiscoveredEvent`s to the EventStore so the `nodes` table (managed by NodeProjection) is populated.

**File: `src/remora/lsp/handlers/documents.py`**

The key change is in the `_process_document()` helper (or equivalent) that runs after parsing:

```python
# After ASTWatcher returns discovered nodes:
async def _process_discovered_nodes(
    server: RemoraLanguageServer,
    file_path: str,
    discovered: list[dict],
) -> None:
    """Emit NodeDiscoveredEvents to EventStore for each discovered node."""
    if not server.event_store:
        return

    from remora.core.events import NodeDiscoveredEvent
    from remora.core.extensions import load_extensions

    extensions = load_extensions()

    for node_dict in discovered:
        # Build NodeDiscoveredEvent from watcher output
        event = NodeDiscoveredEvent(
            node_id=node_dict["remora_id"],
            name=node_dict["name"],
            node_type=node_dict["node_type"],
            file_path=file_path,
            start_line=node_dict["start_line"],
            end_line=node_dict["end_line"],
            source_code=node_dict.get("source_code", ""),
            # Extension matching
            extension_name=_match_extension(node_dict, extensions),
        )
        await server.event_store.append("swarm", event)
```

This is Option A task 4+5 in compressed form. The watcher returns dicts (task 4), and `documents.py` emits events to EventStore (task 5).

### Change 7: LSP Handlers Read from EventStore

Code lens, hover, and code action handlers currently read `ASTAgentNode` from RemoraDB. For the demo, they need to read `AgentNode` from EventStore.

**This is Option A tasks 6-7** and the most invasive change. The pattern is:

```python
# Before (current):
node = await server.db.get_node(node_id)  # Returns ASTAgentNode

# After (demo):
node = await server.event_store.get_node(node_id)  # Returns AgentNode
```

Since `AgentNode` has the same LSP convenience methods (`to_code_lens()`, `to_hover()`, `to_code_actions()`), the handler logic stays the same — only the data source changes.

### Summary of Required Changes

| File | Change | Option A Task | Effort |
|---|---|---|---|
| `server.py` | Add `setup_runner()` with MockLLM selection | Demo-specific | Small |
| `server.py` | Pass EventStore to `RemoraLanguageServer.__init__()` | Task 10 | Small |
| `notifications.py` | Already correct (uses `event_store.get_node_at_position()`) | Task 9 | Done |
| `documents.py` | Emit `NodeDiscoveredEvent` to EventStore on parse | Tasks 4, 5 | Medium |
| `handlers/lens.py` | Read AgentNode from EventStore | Task 6 | Medium |
| `handlers/hover.py` | Read AgentNode from EventStore | Task 6 | Small |
| `handlers/actions.py` | Read AgentNode from EventStore | Task 6 | Small |
| `handlers/commands.py` | Read AgentNode from EventStore for chat/approve | Task 7 | Medium |
| `runner.py` | Use AgentNode from EventStore in execution loop | Task 8 | Medium |
| `event_store.py` | Add `get_node_at_position()`, `set_node_status()`, `remove_nodes_for_file()` | Tasks 1-3 | Medium |

Total: ~10 files modified, but most changes are mechanical (swap data source). The Option A plan has detailed specs for each task.

---

## 11. Demo Entry Points and Launcher

### Two Processes, Two Entry Points

The demo runs as two separate processes:

1. **LSP Server** — Started by Neovim when it opens a file in the demo project. Runs as a stdio-based language server. Entry point: `remora_demo/__main__.py` (already exists).
2. **Graph Viewer** — Started manually in a terminal. Runs an HTTP server on `localhost:8420`. Entry point: `remora_demo/graph/__main__.py` (already exists, needs update for Stario).

Both processes share the same SQLite database at `.remora/indexer.db` within the demo project directory.

### Updated LSP Server Entry Point

The current `remora_demo/__main__.py` imports `MockLLMClient` from `tests/fixtures/mock_llm.py`. For the demo, it should use the enhanced `MockLLMClient` from `remora_demo/mock_llm.py` and wire up the EventStore.

```python
"""remora_demo/__main__.py — Start the Remora LSP demo server."""
from __future__ import annotations

import asyncio
import logging

from lsprotocol import types as lsp

from remora.core.event_store import EventStore
from remora.lsp.server import server
from remora.lsp.runner import AgentRunner

logger = logging.getLogger("remora.demo")


def main() -> None:
    """Start the Remora LSP demo server with EventStore and MockLLM."""

    # Initialize EventStore (uses the same DB the graph viewer reads)
    # The DB path is resolved relative to the workspace root, which
    # the LSP server learns from the initialize request. We set up
    # the EventStore in the initialized handler below.

    @server.feature(lsp.INITIALIZED)
    async def _on_initialized(params: lsp.InitializedParams) -> None:
        # Resolve workspace root
        root_uri = server.workspace.root_uri or ""
        if root_uri:
            from pygls.uris import to_fs_path
            root_path = to_fs_path(root_uri)
        else:
            root_path = "."

        # Create EventStore
        import os
        db_path = os.path.join(root_path, ".remora", "indexer.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        event_store = EventStore(db_path)
        server.event_store = event_store
        logger.info("EventStore initialized at %s", db_path)

        # Create runner with MockLLM
        from remora_demo.mock_llm import MockLLMClient
        llm = MockLLMClient()
        runner = AgentRunner(server=server, llm=llm)
        server.runner = runner
        logger.info("AgentRunner created with MockLLMClient")

        # Start the runner's background loops
        asyncio.ensure_future(runner.run_forever())

    server.start_io()


if __name__ == "__main__":
    main()
```

**Key differences from current version:**
- Uses `EventStore` instead of passing `event_store=None`.
- Imports `MockLLMClient` from `remora_demo.mock_llm` (enhanced version).
- Resolves DB path from workspace root (so it works when Neovim opens the demo project).
- Defers EventStore creation to `INITIALIZED` handler (when we know the workspace root).

### Updated Graph Viewer Entry Point

The current `remora_demo/graph/__main__.py` uses uvicorn + Starlette. The new version uses Stario's built-in server.

```python
"""remora_demo/graph/__main__.py — Start the graph viewer web server."""
from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remora Graph Viewer — real-time agent graph visualization",
    )
    parser.add_argument("--port", type=int, default=8420, help="HTTP port (default: 8420)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument(
        "--db",
        default=".remora/indexer.db",
        help="Path to the shared SQLite DB (default: .remora/indexer.db)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.3,
        help="DB poll interval in seconds (default: 0.3)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from pathlib import Path
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Warning: DB not found at {db_path}. Will wait for LSP server to create it.",
              file=sys.stderr)

    from remora_demo.graph.app import create_app
    app = create_app(db_path=str(db_path), poll_interval=args.poll_interval)

    print(f"Remora Graph Viewer: http://{args.host}:{args.port}")
    print(f"DB: {db_path.resolve()}")
    print(f"Poll interval: {args.poll_interval}s")

    app.serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

**Key differences from current version:**
- Uses `app.serve()` (Stario) instead of `uvicorn.run()` (ASGI).
- Adds `--poll-interval` flag for tuning bridge responsiveness.
- Adds `--verbose` flag for debug logging.
- Prints startup info banner.
- Warns but doesn't fail if DB doesn't exist yet (it will be created when the LSP server starts).

### Updated App Factory

The `create_app()` function needs to accept the `poll_interval` parameter:

```python
# In remora_demo/graph/app.py:
def create_app(db_path: str = ".remora/indexer.db", poll_interval: float = 0.3) -> Stario:
    # ...
    bridge = DBBridge(state=state, layout=layout, relay=relay, poll_interval=poll_interval)
    # ... rest unchanged
```

### Neovim Configuration

The demo project needs a `.nvim.lua` (or `.exrc`) file that tells Neovim to use the demo LSP server:

```lua
-- remora_demo/project/.nvim.lua
-- Auto-loaded by Neovim when opening files in this directory
-- (requires `set exrc` in init.lua)

vim.lsp.start({
    name = "remora-demo",
    cmd = { "python", "-m", "remora_demo" },
    root_dir = vim.fn.getcwd(),
    settings = {},
})

-- Set updatetime for responsive cursor tracking
vim.opt.updatetime = 300
```

Alternatively, if the user has the remora Neovim plugin installed, it handles LSP registration. In that case, the plugin just needs to know to use `python -m remora_demo` as the command instead of the production server. This is configured in the plugin's setup:

```lua
-- In user's init.lua:
require("remora").setup({
    cmd = { "python", "-m", "remora_demo" },
})
```

### Port Configuration

| Service | Default Port | Flag | Environment Variable |
|---|---|---|---|
| Graph Viewer | 8420 | `--port` | — |
| LSP Server | (stdio, no port) | — | — |

The graph viewer port is hardcoded in the browser URL. Since it's a single-user demo tool, port conflicts are unlikely. If needed, the port can be overridden with `--port`.

### DB Path Resolution

Both processes need to agree on the DB path. The convention:

1. **LSP Server:** Resolves `{workspace_root}/.remora/indexer.db` from the LSP initialization params.
2. **Graph Viewer:** Takes `--db` flag (default: `.remora/indexer.db` relative to CWD).

For the demo, both are run from the `remora_demo/project/` directory, so the default paths match.

### Optional: Unified Launcher Script

For convenience, a shell script that starts both processes:

```bash
#!/usr/bin/env bash
# remora_demo/launch.sh — Start both the graph viewer and open Neovim
set -e

DEMO_DIR="$(cd "$(dirname "$0")/project" && pwd)"
DB_PATH="$DEMO_DIR/.remora/indexer.db"

echo "Remora Demo"
echo "==========="
echo "Demo project: $DEMO_DIR"
echo ""

# Ensure .remora directory exists
mkdir -p "$DEMO_DIR/.remora"

# Start graph viewer in background
echo "Starting graph viewer on http://127.0.0.1:8420 ..."
python -m remora_demo.graph --db "$DB_PATH" &
GRAPH_PID=$!
echo "Graph viewer PID: $GRAPH_PID"

# Wait a moment for the server to start
sleep 1

# Open browser (best-effort)
if command -v xdg-open &>/dev/null; then
    xdg-open "http://127.0.0.1:8420" 2>/dev/null &
elif command -v open &>/dev/null; then
    open "http://127.0.0.1:8420" &
fi

# Start Neovim with the demo project
echo "Opening Neovim..."
cd "$DEMO_DIR"
nvim src/configlib/loader.py

# Cleanup: kill graph viewer when Neovim exits
echo "Shutting down graph viewer..."
kill $GRAPH_PID 2>/dev/null || true
wait $GRAPH_PID 2>/dev/null || true
echo "Done."
```

This script:
1. Starts the graph viewer in the background.
2. Opens the browser to `localhost:8420`.
3. Opens Neovim with `loader.py` (the main file for the golden path).
4. When Neovim exits, kills the graph viewer.

The script is a convenience — each process can also be started independently in separate terminals for debugging.

---

## 12. Demo Script: The Golden Path

### Prerequisites

Before running the demo, ensure:

1. `devenv shell` (or equivalent Python env) is active with all dependencies.
2. The demo project directory exists at `remora_demo/project/` with all source files from Section 2.
3. The remora Neovim plugin is installed and configured to use `python -m remora_demo` as the LSP command.

### Terminal Layout

```
┌─────────────────────────────┬─────────────────────────────┐
│                             │                             │
│        Neovim               │     Browser                 │
│        (Terminal 1)         │     localhost:8420           │
│                             │                             │
└─────────────────────────────┴─────────────────────────────┘
                     Terminal 2 (below, optional)
                     Graph viewer server logs
```

Use a tiling window manager or `tmux` split. Neovim on the left, browser on the right, optional terminal at the bottom for graph viewer logs.

### Setup Commands

**Terminal 2 (graph viewer):**

```bash
cd remora_demo/project
python -m remora_demo.graph --db .remora/indexer.db -v
# Output: Remora Graph Viewer: http://127.0.0.1:8420
#         DB: /home/.../remora_demo/project/.remora/indexer.db
```

**Browser:** Navigate to `http://127.0.0.1:8420`. You should see an empty graph with the header "Remora Graph" and sidebar saying "Click a node to view details".

**Terminal 1 (Neovim):**

```bash
cd remora_demo/project
nvim src/configlib/loader.py
```

### Beat 1: Launch

**What happens:**
- Neovim opens `loader.py`. The remora LSP plugin starts `python -m remora_demo` as a subprocess.
- The LSP server initializes, creates `.remora/indexer.db`, sets up EventStore.
- The graph viewer's bridge detects the DB was created and starts polling.

**What you see:**
- Neovim: `loader.py` opens with syntax highlighting. After ~1 second, code lenses appear above functions.
- Browser: Empty graph (no nodes yet — `did_open` hasn't fired for enough files).

**What to say:** "Neovim just started the Remora LSP server. The graph viewer is connected to the same database."

### Beat 2: Open Files — Code Lenses Appear

**What happens:**
- `did_open` fires for `loader.py`. ASTWatcher parses it. `NodeDiscoveredEvent`s are emitted for `load_config`, `detect_format`, `load_yaml`, and the file node.
- Code lenses appear: `▶ rm_load_config`, `▶ rm_detect_format`, `▶ rm_load_yaml`.

**What you see:**
- Neovim: Three code lenses above functions.
- Browser: Three function nodes + one file node appear. They drift into position (CSS transition from initial layout).

**What to say:** "Each function is now an agent. The code lenses show their status. The graph viewer sees the same nodes."

### Beat 3: More Files — Graph Grows

**Action:** Open more files in Neovim:

```vim
:e src/configlib/schema.py
:e src/configlib/merge.py
:e tests/test_loader.py
:e tests/test_merge.py
```

**What happens:**
- Each `did_open` triggers ASTWatcher → `NodeDiscoveredEvent`s.
- LazyGraph builds edges (parent_of, calls).
- The graph viewer's bridge detects topology changes.

**What you see:**
- Neovim: Each file gets code lenses above its functions.
- Browser: The graph fills in — 16 nodes, 17 edges. File nodes at top, function nodes below. Test nodes on the right side. Edges connect callers to callees. Layout settles via CSS transitions.

**What to say:** "Now we can see the full graph. File nodes contain their functions. Call edges show dependencies. Test functions point to the source functions they test."

### Beat 4: Navigate — Cursor Tracking

**Action:** Move cursor to `load_config()` function in `loader.py`:

```vim
:e src/configlib/loader.py
/def load_config
```

Then let the cursor sit for ~300ms.

**What happens:**
- `CursorHold` fires → `$/remora/cursorMoved` → `get_node_at_position()` finds `load_config` → `cursor_focus` table updated.
- Bridge detects cursor change → `graph.cursor` → SSE patch.

**What you see:**
- Neovim: Normal cursor position on `load_config`.
- Browser: The `load_config` node gets a bright blue highlight ring with a soft glow. Connected edges brighten. If viewport panning is enabled, the graph smoothly centers on that node.

**What to say:** "Watch the graph — as I move my cursor, the corresponding agent highlights. This is real-time cursor tracking through the LSP."

**Action:** Move cursor to different functions to show the highlight following:

```vim
/def detect_format
```

(Pause.) The highlight moves to `detect_format`.

```vim
:e tests/test_loader.py
/def test_load_yaml
```

(Pause.) The highlight moves to `test_load_yaml`.

### Beat 5: Chat — Talk to an Agent

**Action:** Navigate back to `load_config` and send a chat message:

```vim
:e src/configlib/loader.py
/def load_config
:RemoraChat what do you do?
```

**What happens:**
- `:RemoraChat` emits `HumanChatEvent` → EventStore → runner triggers `load_config` agent.
- MockLLM's `HumanChatScript` matches → returns descriptive text about `load_config`.
- `AgentMessageEvent` emitted with the response.

**What you see:**
- Neovim: The response appears in a floating panel or the message area (depending on plugin UI).
- Browser: Event stream shows `HumanChat` (peach) followed by `AgentComplete` (green). The `load_config` node briefly turns blue (running) then back to gray (idle).

**What to say:** "I just asked the agent what it does. It responded based on its context — it knows its source code, its dependencies, and its role in the project."

### Beat 6: Edit — Trigger the Cascade

**Action:** Edit `load_config` to add a timeout parameter:

```vim
:e src/configlib/loader.py
/def load_config
```

Change the function signature from:

```python
def load_config(path: str | Path) -> dict[str, Any]:
```

to:

```python
def load_config(path: str | Path, timeout: int = 30) -> dict[str, Any]:
```

Then save: `:w`

**What happens:**
- `did_save` fires → ASTWatcher re-parses → `ContentChangedEvent` emitted.
- Runner triggers `load_config` agent with the content change context.
- MockLLM's `ContentChangedAnalyzeScript` matches → returns text + `message_node("test_load_yaml", ...)`.

**What you see:**
- Neovim: Code lens changes to `▶ rm_load_config running`.
- Browser: `load_config` node turns blue (running) with pulse animation. Event stream shows `ContentChanged` → `AgentStart` → `ModelRequest` → `ModelResponse`.

**What to say:** "I added a timeout parameter. The agent detected the change and is analyzing it."

### Beat 7: Agent Thinks — Visible Processing

**What happens (continuing from beat 6):**
- Runner processes the tool call: `message_node("test_load_yaml", "...")`.
- `AgentMessageEvent` emitted targeting `test_load_yaml`.
- `load_config` agent completes.

**What you see:**
- Browser: `ModelRequest` and `ModelResponse` events appear in the stream. The agent's text explanation scrolls in: "I see that load_config has been updated with a new timeout parameter..."

**What to say:** "The agent is thinking. You can see the model requests and responses in real-time. It decided to notify the test agent."

### Beat 8: Cascade — Agent Messages Agent

**What happens:**
- The `message_node` tool call delivers a message to `test_load_yaml`.
- Runner triggers `test_load_yaml` agent.
- MockLLM's `TestAgentUpdateScript` matches:
  - Round 0: returns `read_node("load_config")` tool call.
  - Runner executes `read_node`, returns current source.
  - Round 1: returns `rewrite_self(new_source)` tool call.

**What you see:**
- Neovim: Code lens for `test_load_yaml` changes to `▶ rm_test_load_yaml running`.
- Browser: The edge between `load_config` and `test_load_yaml` brightens. `test_load_yaml` node turns blue (running). Event stream shows: `AgentMessage` → `AgentStart` (test_load_yaml) → `ModelRequest` → `read_node` → `ModelResponse` → `ModelRequest` → `rewrite_self` → `ModelResponse`.

**What to say:** "The source agent messaged the test agent. The test agent is now reading the current source code and preparing an update. This is autonomous inter-agent coordination."

### Beat 9: Proposal — Agent Proposes a Rewrite

**What happens:**
- The `rewrite_self` tool call creates a `RewriteProposalEvent`.
- A diagnostic squiggle appears on `test_load_yaml` in the test file.
- The node status changes to `pending_approval` (yellow).

**What you see:**
- Neovim: Open `tests/test_loader.py` — there's a diagnostic squiggle (warning) on the test function. The code lens shows `▶ rm_test_load_yaml pending_approval`.
- Browser: `test_load_yaml` node turns yellow. Click on it — the sidebar's Actions tab shows the proposal with a diff. The diff shows the new `test_load_yaml_with_timeout` test being added.

**What to say:** "The test agent proposes an update. The yellow node means it's waiting for approval. Let's look at the diff."

**Action:** Click the `test_load_yaml` node in the browser. The sidebar loads with the proposal.

### Beat 10: Approve — Apply the Change

**Action:** Approve the proposal from Neovim:

```vim
:e tests/test_loader.py
:RemoraAccept
```

**What happens:**
- `:RemoraAccept` dispatches `workspace/applyEdit` → buffer updates with new test code.
- `RewriteAppliedEvent` emitted.
- Node status returns to `idle`.
- Diagnostic clears.

**What you see:**
- Neovim: The test file updates with the new test function. Diagnostic squiggle disappears. Code lens returns to `▶ rm_test_load_yaml`.
- Browser: Node turns back to gray (idle). Event stream shows `RewriteApplied`. The whole chain is visible in the log.

**What to say:** "Approved. The test file is updated. The whole chain — from edit to analysis to cascade to proposal to approval — happened through events."

### Beat 11: Reflect — Browse the Event Log

**Action:** Click on `load_config` in the browser graph. Switch to the Log tab in the sidebar.

**What you see:**
- Sidebar shows the full event history for `load_config`:
  - `HumanChat` (from beat 5)
  - `AgentStart`/`AgentComplete` (from beat 5)
  - `ContentChanged` (from beat 6)
  - `AgentStart` (from beat 6-7)
  - `ModelRequest`/`ModelResponse` (from beat 7)
  - `AgentMessage` (to test_load_yaml, from beat 8)
  - `AgentComplete` (from beat 8)

**What to say:** "Every event is logged and auditable. You can trace the complete chain: what triggered the agent, what it decided, who it talked to, and what happened. This is the EventBased architecture — single source of truth, observable by any tool."

### Timing

| Beat | Duration | Cumulative |
|------|----------|------------|
| 1. Launch | 5s | 0:05 |
| 2. Open files | 10s | 0:15 |
| 3. More files | 15s | 0:30 |
| 4. Navigate | 15s | 0:45 |
| 5. Chat | 15s | 1:00 |
| 6. Edit | 10s | 1:10 |
| 7. Agent thinks | 5s (automatic) | 1:15 |
| 8. Cascade | 5s (automatic) | 1:20 |
| 9. Proposal | 15s | 1:35 |
| 10. Approve | 10s | 1:45 |
| 11. Reflect | 15s | 2:00 |

**Total demo time: ~2 minutes.** This is tight enough to hold attention and long enough to show the architecture working end-to-end.

---

## 13. File Manifest

### New Files to Create

| File | Description | Section |
|---|---|---|
| **Demo Project** | | |
| `remora_demo/project/remora.yaml` | Remora config for demo project | 2 |
| `remora_demo/project/.remora/models/test_function.py` | TestFunction extension config | 2 |
| `remora_demo/project/.remora/models/package_init.py` | PackageInit extension config | 2 |
| `remora_demo/project/src/configlib/__init__.py` | Package exports | 2 |
| `remora_demo/project/src/configlib/loader.py` | Core loading functions | 2 |
| `remora_demo/project/src/configlib/schema.py` | Validation | 2 |
| `remora_demo/project/src/configlib/merge.py` | Dict merge utilities | 2 |
| `remora_demo/project/tests/test_loader.py` | Loader tests | 2 |
| `remora_demo/project/tests/test_merge.py` | Merge tests | 2 |
| **MockLLM** | | |
| `remora_demo/mock_llm.py` | Enhanced MockLLMClient with scripted responses | 4 |
| `tests/test_mock_llm.py` | Tests for the mock | 4 |
| **Graph Viewer (new/rewrite)** | | |
| `remora_demo/graph/views/__init__.py` | Package init | 5 |
| `remora_demo/graph/views/graph.py` | SVG graph rendering | 7 |
| `remora_demo/graph/views/shell.py` | Full HTML page | 7 |
| `remora_demo/graph/views/sidebar.py` | Sidebar detail panel | 8 |
| `remora_demo/graph/views/event_stream.py` | Global event stream | 8 |
| `remora_demo/graph/svg.py` | SVG element builders | 7 |
| `remora_demo/graph/bridge.py` | DB→Relay polling bridge | 6 |
| `remora_demo/graph/layout.py` | Force-directed layout | 5 |
| `remora_demo/graph/css.py` | All CSS (Catppuccin dark theme) | 7, 8 |
| **Launcher** | | |
| `remora_demo/launch.sh` | Convenience script to start both processes | 11 |

### Existing Files to Modify

| File | Change | Section |
|---|---|---|
| **Core EventStore** | | |
| `src/remora/core/event_store.py` | Add `get_node_at_position()`, `set_node_status()`, `remove_nodes_for_file()` | 9, 10 |
| **LSP Server** | | |
| `src/remora/lsp/server.py` | Add `setup_runner()` with MockLLM selection; wire EventStore | 10 |
| `src/remora/lsp/handlers/documents.py` | Emit `NodeDiscoveredEvent` to EventStore after parse | 10 |
| `src/remora/lsp/handlers/lens.py` | Read `AgentNode` from EventStore instead of RemoraDB | 10 |
| `src/remora/lsp/handlers/hover.py` | Read `AgentNode` from EventStore | 10 |
| `src/remora/lsp/handlers/actions.py` | Read `AgentNode` from EventStore | 10 |
| `src/remora/lsp/handlers/commands.py` | Read `AgentNode` from EventStore for chat/approve | 10 |
| `src/remora/lsp/runner.py` | Use `AgentNode` from EventStore in execution loop | 10 |
| `src/remora/lsp/notifications.py` | Already correct (uses EventStore) — verify | 9, 10 |
| **Graph Viewer (rewrite existing)** | | |
| `remora_demo/graph/__init__.py` | No changes needed | — |
| `remora_demo/graph/__main__.py` | Replace uvicorn with Stario `app.serve()` | 11 |
| `remora_demo/graph/app.py` | Rewrite: Stario app factory with Relay, bridge | 6 |
| `remora_demo/graph/state.py` | Add `read_recent_events()`; keep existing methods | 6 |
| **Graph Viewer (delete)** | | |
| `remora_demo/graph/sidebar.py` | Replaced by `views/sidebar.py` | 8 |
| `remora_demo/graph/shell.py` | Replaced by `views/shell.py` | 7 |
| **Demo Entry Point** | | |
| `remora_demo/__main__.py` | Use enhanced MockLLM, wire EventStore | 11 |

### Files NOT Modified (Reference Only)

| File | Why |
|---|---|
| `src/remora/core/agent_node.py` | Already complete (Phase 1) |
| `src/remora/core/events.py` | Already complete (Phase 1) |
| `src/remora/core/projections.py` | Already complete (Phase 1) |
| `src/remora/core/extensions.py` | Already complete (Phase 1) |
| `src/remora/lsp/db.py` | Keeps existing tables; no schema changes |
| `src/remora/lsp/graph.py` | LazyGraph — partial update in Option A task 14, not critical path |
| `src/remora/lsp/models.py` | ASTAgentNode stays for now (cleanup deferred) |
| `src/remora/lsp/extensions.py` | Stays for now (cleanup deferred) |
| `src/remora/lsp/watcher.py` | Task 4 changes watcher output format, but watcher.py itself is minimal |

### File Count Summary

| Category | New | Modified | Deleted |
|---|---|---|---|
| Demo project files | 9 | 0 | 0 |
| MockLLM | 2 | 0 | 0 |
| Graph viewer | 8 | 4 | 2 |
| Core / LSP | 0 | 9 | 0 |
| Launcher | 1 | 0 | 0 |
| **Total** | **20** | **13** | **2** |

---

## 14. Implementation Order

This section organizes the work from sections 2-13 into discrete implementation tasks, maps their dependencies, estimates effort, and identifies the critical path.

### Implementation Tasks

The work decomposes into **22 tasks** across 5 workstreams. Each task is designed for a single atomic commit.

| ID | Task | Section | Workstream | Effort |
|----|------|---------|------------|--------|
| **T1** | Create `configlib` demo project files | 2 | Demo Project | S |
| **T2** | Create `.remora/models/` extension configs + `remora.yaml` | 2 | Demo Project | S |
| **T3** | Add `get_node_at_position()` to EventStore | 3, 9 | Core Migration | S |
| **T4** | Add `set_node_status()` to EventStore | 3 | Core Migration | S |
| **T5** | Add `remove_nodes_for_file()` to EventStore | 3 | Core Migration | S |
| **T6** | Update watcher to return dicts (not ASTAgentNode) | 3 | Core Migration | M |
| **T7** | Update `documents.py` to emit `NodeDiscoveredEvent` to EventStore | 3, 10 | Core Migration | M |
| **T8** | Update LSP handlers (lens, hover, actions) to read `AgentNode` from EventStore | 3, 10 | Core Migration | M |
| **T9** | Update `commands.py` to use EventStore + `AgentNode` | 3, 10 | Core Migration | M |
| **T10** | Update `runner.py` to use EventStore + `AgentNode` | 3, 10 | Core Migration | L |
| **T11** | Update `notifications.py` to use EventStore | 3, 9 | Core Migration | S |
| **T12** | Update `server.py` wiring (EventStore + MockLLM selection) | 3, 10, 11 | Core Migration | M |
| **T13** | Update LazyGraph to read nodes from EventStore | 3, 10 | Core Migration | M |
| **T14** | Implement enhanced `MockLLMClient` with scripted responses | 4 | MockLLM | L |
| **T15** | Implement server-side `ForceLayout` + `layout.py` | 5 | Graph Viewer | M |
| **T16** | Implement `svg.py` element builders | 7 | Graph Viewer | S |
| **T17** | Implement `css.py` (Catppuccin theme, transitions, animations) | 7 | Graph Viewer | M |
| **T18** | Implement `bridge.py` (DB→Relay polling bridge) | 6 | Graph Viewer | M |
| **T19** | Implement graph viewer Stario app + handlers (`app.py`, `handlers.py`) | 6 | Graph Viewer | L |
| **T20** | Implement view functions (`shell.py`, `graph.py`, `sidebar.py`, `event_stream.py`) | 7, 8 | Graph Viewer | L |
| **T21** | Implement demo entry points + launcher | 11 | Launcher | M |
| **T22** | End-to-end integration test (golden path smoke test) | 12, 15 | Integration | L |

**Effort key:** S = small (~1-2 hours), M = medium (~2-4 hours), L = large (~4-8 hours).

### Dependency Graph

```
                    ┌─────────────────────────────────────────────────────────────────────┐
                    │                     DEMO PROJECT (independent)                       │
                    │                                                                      │
                    │  T1 ──> T2                                                          │
                    └─────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────────────────────────────────┐
                    │                     CORE MIGRATION (sequential spine)                │
                    │                                                                      │
                    │  T3 ─┐                                                              │
                    │  T4 ─┼──> T7 ──> T8 ──┐                                            │
                    │  T5 ─┘    │            ├──> T10 ──> T12                             │
                    │           │      T9 ──┘      │                                      │
                    │           │                   ├──> T13                               │
                    │  T6 ──────┘            T11 ──┘                                      │
                    └─────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────────────────────────────────┐
                    │                     MOCK LLM (independent until T10)                 │
                    │                                                                      │
                    │  T14 ─────────────────────────────────────────> (feeds into T12)    │
                    └─────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────────────────────────────────┐
                    │                     GRAPH VIEWER (mostly independent)                │
                    │                                                                      │
                    │  T15 ─┐                                                              │
                    │  T16 ─┼──> T20 ──> T19                                              │
                    │  T17 ─┘              │                                               │
                    │  T18 ───────────────>┘                                               │
                    └─────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────────────────────────────────┐
                    │                     INTEGRATION                                      │
                    │                                                                      │
                    │  T12 ─┐                                                              │
                    │  T19 ─┼──> T21 ──> T22                                              │
                    │  T2  ─┘                                                              │
                    └─────────────────────────────────────────────────────────────────────┘
```

### Dependency Details

| Task | Depends On | Rationale |
|------|-----------|-----------|
| T1 | — | Standalone: write demo project source files |
| T2 | T1 | Extension configs reference the project structure |
| T3 | — | New EventStore method, only depends on Phase 1 code |
| T4 | — | New EventStore method, only depends on Phase 1 code |
| T5 | — | New EventStore method, only depends on Phase 1 code |
| T6 | — | Watcher refactor is independent of EventStore additions |
| T7 | T3, T4, T5, T6 | documents.py needs all three new EventStore methods + dict-returning watcher |
| T8 | T7 | Handlers need documents.py to populate EventStore first |
| T9 | T7 | commands.py needs nodes in EventStore (populated by documents.py) |
| T10 | T8, T9 | Runner uses handlers' patterns + commands' patterns; largest change |
| T11 | T3 | notifications.py only needs `get_node_at_position()` |
| T12 | T10, T11, T14 | server.py wires everything together including MockLLM |
| T13 | T10 | LazyGraph needs EventStore to have nodes; runner must work first |
| T14 | — | MockLLM is self-contained; can be built in isolation |
| T15 | — | Force layout algorithm is pure computation, no dependencies |
| T16 | — | SVG builders are pure functions |
| T17 | — | CSS is standalone |
| T18 | — | Bridge reads from DB + publishes to Relay; can stub data for testing |
| T19 | T18, T20 | App wires together bridge, handlers, and views |
| T20 | T15, T16, T17 | Views compose layout, SVG builders, and CSS |
| T21 | T2, T12, T19 | Entry points need demo project, wired server, and graph viewer app |
| T22 | T21 | End-to-end test requires everything assembled |

### Critical Path

The **critical path** is the longest chain of dependent tasks that determines minimum calendar time:

```
T3/T4/T5 (S) ──> T7 (M) ──> T8 (M) ──> T10 (L) ──> T12 (M) ──> T21 (M) ──> T22 (L)
   ~2h              3h          3h          6h           3h           3h          6h
                                                                          Total: ~26h
```

The graph viewer workstream runs in parallel but has its own chain:

```
T15/T16/T17 (S+S+M) ──> T20 (L) ──> T19 (L)
        ~6h                  6h          6h
                                   Total: ~18h
```

Since the graph viewer chain (~18h) is shorter than the core migration chain (~26h), **the core migration is the bottleneck**. The graph viewer can be built entirely in parallel and will finish first.

### Parallelization Opportunities

At any given point, multiple tasks can be in flight simultaneously (assuming a human is context-switching or multiple sessions are used):

| Phase | Tasks That Can Run In Parallel | Combined Effort |
|-------|-------------------------------|-----------------|
| **Phase A: Foundations** | T1, T3, T4, T5, T6, T14, T15, T16, T17, T18 | 10 tasks, ~18h total |
| **Phase B: Wiring** | T2, T7, T8, T9, T11, T20 | 6 tasks, ~16h total |
| **Phase C: Assembly** | T10, T13, T19 | 3 tasks, ~14h total |
| **Phase D: Integration** | T12 | 1 task, ~3h |
| **Phase E: Launch** | T21, T22 | 2 tasks, ~9h total |

With full parallelization across workstreams, wall-clock time could be as low as **~26 hours** (limited by the critical path). With a single implementer working sequentially, total effort is approximately **~60 hours** (~7-8 working days).

### Recommended Implementation Sequence

For a single implementer (one task at a time), this ordering minimizes context-switching and gives the fastest feedback loops:

#### Week 1: Core Migration + MockLLM

| Order | Task | Why This Order |
|-------|------|---------------|
| 1 | **T3** — `get_node_at_position()` | Smallest core addition; warm up with TDD |
| 2 | **T4** — `set_node_status()` | Same pattern, builds confidence |
| 3 | **T5** — `remove_nodes_for_file()` | Completes the EventStore API surface |
| 4 | **T6** — Watcher returns dicts | Prepares the pipeline input |
| 5 | **T7** — `documents.py` uses EventStore | First real integration point; can test with existing LSP test harness |
| 6 | **T11** — `notifications.py` uses EventStore | Quick win; only needs T3 |
| 7 | **T8** — LSP handlers use AgentNode | Natural follow-on from T7; handlers read what documents.py wrote |
| 8 | **T9** — `commands.py` uses AgentNode | Same migration pattern as T8 |
| 9 | **T10** — `runner.py` uses AgentNode | Largest single task; do it while migration patterns are fresh |
| 10 | **T14** — Enhanced MockLLMClient | Context switch to new code; palate cleanser after heavy refactoring |

#### Week 2: Graph Viewer + Integration

| Order | Task | Why This Order |
|-------|------|---------------|
| 11 | **T1** — Create `configlib` project | Quick; sets up the demo test bed |
| 12 | **T2** — Extension configs + `remora.yaml` | Completes the demo project |
| 13 | **T12** — Wire `server.py` | All dependencies ready; connects everything on the LSP side |
| 14 | **T13** — Update LazyGraph | Ensures graph edges work with new node source |
| 15 | **T15** — Server-side ForceLayout | Start graph viewer workstream |
| 16 | **T16** — SVG element builders | Pure functions, fast to implement |
| 17 | **T17** — CSS theme + transitions | Visual foundation |
| 18 | **T18** — DB→Relay bridge | Connects data to SSE pipeline |
| 19 | **T20** — View functions | Compose layout + SVG + CSS into renderable views |
| 20 | **T19** — Stario app + handlers | Wire views into HTTP/SSE endpoints |
| 21 | **T21** — Demo entry points + launcher | Assemble everything |
| 22 | **T22** — End-to-end integration test | Verify the golden path works |

### Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| `runner.py` migration (T10) is more complex than estimated | High | Blocks all downstream tasks | Do T10 early in the sequence while context is fresh. Have the Option A plan + runner source code open side-by-side. |
| Server-side force layout (T15) produces poor graph aesthetics | Medium | Demo looks bad | Start with a simple spring-electric model. Tune constants empirically. Fall back to hierarchical layout if force-directed doesn't converge. |
| MockLLM scripts (T14) don't produce convincing demo flow | Medium | Demo feels scripted/fake | Design scripts to have natural variance. Include thinking tokens. Test against golden path beat table. |
| Stario SSE streaming (T19) has performance issues with rapid updates | Low | Graph viewer feels laggy | Bridge already uses fingerprint-based change detection to minimize publishes. Debounce in bridge if needed. |
| LazyGraph (T13) breaks when reading nodes from different DB | Medium | Graph has nodes but no edges | Keep edges in RemoraDB. Give LazyGraph both DB handles. Test with the demo project specifically. |
| devenv hash mismatch blocks local testing | Known | Can't run pytest | Use `uv pip install -e ".[dev]"` as fallback. Or fix the iocraft hash in flake.nix. |

### Summary

- **22 tasks**, **~60 hours** total effort, **~26 hours** critical path.
- **5 workstreams**: Demo Project (2), Core Migration (11), MockLLM (1), Graph Viewer (6), Integration (2).
- **Biggest risk**: `runner.py` migration (T10) — mitigate by tackling it early.
- **Biggest payoff**: Core Migration Phase A (T3-T6) unlocks everything downstream.
- The graph viewer workstream is completely independent and can be built in any order relative to core migration, as long as both converge before T21.
- After T22 passes, the demo is ready to run.
