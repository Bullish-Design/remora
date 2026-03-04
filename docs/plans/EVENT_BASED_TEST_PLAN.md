# EventBased Architecture: Comprehensive Test Plan

> **Scope:** Phase 1 remediation + full EventBased architecture (all phases)
>
> **Reference:** `docs/EventBased_Concept.md`, `EVENT_BASED_PHASE_1_CODE_REVIEW.md`
>
> **Date:** 2026-03-02

---

## Table of Contents

1. [Testing Philosophy](#1-testing-philosophy)
2. [Phase 1 Test Gaps and Remediation](#2-phase-1-test-gaps-and-remediation)
3. [Test Infrastructure](#3-test-infrastructure)
4. [Unit Test Plan by Component](#4-unit-test-plan-by-component)
5. [Integration Test Plan](#5-integration-test-plan)
6. [Neovim Integration Testing with asciinema](#6-neovim-integration-testing-with-asciinema)
7. [Performance and Load Testing](#7-performance-and-load-testing)
8. [Regression Testing Strategy](#8-regression-testing-strategy)

---

## 1. Testing Philosophy

### Principles

1. **Real over mocked.** Prefer real SQLite databases, real tree-sitter parsing, and real Neovim instances over mocks. Only mock the LLM kernel.

2. **Event-centric assertions.** Since the EventLog is the source of truth, most tests should assert on event sequences and their projected outcomes, not on intermediate object state.

3. **Pyramid structure.** Many fast unit tests, fewer integration tests, even fewer (but critical) end-to-end Neovim tests.

4. **Every bug gets a regression test.** When an issue from the code review is fixed, the fix includes a test that would have caught it.

5. **Deterministic by default.** All time-dependent behavior uses injectable clocks. All async tests use controlled event loops.

### Test Categories

| Category | Location | Runs in CI | Typical Duration |
|----------|----------|------------|-----------------|
| Unit | `tests/unit/` | Always | <5s total |
| Integration | `tests/integration/` | Always | <30s total |
| Neovim E2E | `tests/e2e/` | On PR merge | <120s total |
| Performance | `tests/benchmarks/` | Nightly | <60s total |
| Roundtrip | `tests/roundtrip/` | Manual | Variable |

### Markers

```python
# conftest.py additions
pytest.mark.unit       # Fast, no I/O beyond tmp_path
pytest.mark.integration # Real DB, real file system, no Neovim
pytest.mark.e2e        # Requires Neovim + asciinema
pytest.mark.benchmark  # Performance measurement
pytest.mark.slow       # >5s, skip in quick mode
```

---

## 2. Phase 1 Test Gaps and Remediation

These are the specific test gaps identified in the Phase 1 code review. Each should be addressed before starting Phase 2.

### 2.1 Missing Tests to Add

#### T1: `ToolSchema.to_llm_tool()` (P1)

**File:** `tests/unit/test_agent_node.py`

```python
class TestToolSchema:
    def test_to_llm_tool_basic(self):
        tool = ToolSchema(
            name="run_test",
            description="Run the test suite",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        result = tool.to_llm_tool()
        assert result["type"] == "function"
        assert result["function"]["name"] == "run_test"
        assert result["function"]["description"] == "Run the test suite"
        assert "path" in result["function"]["parameters"]["properties"]

    def test_to_llm_tool_empty_params(self):
        tool = ToolSchema(name="noop", description="Do nothing", parameters={})
        result = tool.to_llm_tool()
        assert result["function"]["parameters"] == {}

    def test_to_code_action(self):
        tool = ToolSchema(name="run_test", description="Run test", parameters={})
        action = tool.to_code_action("node_abc")
        assert action.command.command == "remora.tool.run_test"
        assert action.command.arguments == ["node_abc"]
```

#### T2: Extension with Complex Fields Through Projection (P1)

**File:** `tests/unit/test_projections.py`

```python
class TestProjectExtensionComplexFields:
    @pytest.mark.asyncio
    async def test_extension_with_extra_tools(self, store: EventStore):
        class ToolExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str) -> bool:
                return name == "instrumented"

            @staticmethod
            def get_extension_data() -> dict:
                return {
                    "extension_name": "ToolAgent",
                    "extra_tools": [
                        {"name": "run", "description": "Run it", "parameters": {"type": "object"}},
                    ],
                    "mounted_workspaces": ["/data/workspace"],
                }

        proj = NodeProjection(extension_configs=[ToolExt])
        event = _discovered_event(name="instrumented", full_name="function:instrumented")
        proj.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        node = AgentNode.from_row(row)
        assert node.extension_name == "ToolAgent"
        assert len(node.extra_tools) == 1
        assert node.extra_tools[0].name == "run"
        assert node.mounted_workspaces == ["/data/workspace"]

    @pytest.mark.asyncio
    async def test_extension_with_extra_subscriptions(self, store: EventStore):
        class SubExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str) -> bool:
                return True

            @staticmethod
            def get_extension_data() -> dict:
                return {
                    "extension_name": "ReactiveAgent",
                    "extra_subscriptions": [
                        {"event_types": ["ContentChangedEvent"], "file_patterns": ["*.py"]},
                    ],
                }

        proj = NodeProjection(extension_configs=[SubExt])
        event = _discovered_event()
        proj.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        node = AgentNode.from_row(row)
        assert len(node.extra_subscriptions) == 1
        assert node.extra_subscriptions[0].event_types == ["ContentChangedEvent"]
```

#### T3: Error Path Tests for `from_row()` (P2)

**File:** `tests/unit/test_agent_node.py`

```python
class TestAgentNodeErrorPaths:
    def test_from_row_malformed_extra_tools_json(self):
        row = {**_make_node().to_row(), "extra_tools": "not-json"}
        with pytest.raises((json.JSONDecodeError, Exception)):
            AgentNode.from_row(row)

    def test_from_row_extra_tools_wrong_schema(self):
        row = {**_make_node().to_row(), "extra_tools": '[{"unexpected": true}]'}
        with pytest.raises((TypeError, Exception)):
            AgentNode.from_row(row)

    def test_from_row_null_json_fields(self):
        row = {**_make_node().to_row()}
        row["caller_ids"] = None
        row["callee_ids"] = None
        row["extra_tools"] = None
        row["extra_subscriptions"] = None
        row["mounted_workspaces"] = None
        node = AgentNode.from_row(row)
        assert node.caller_ids == []
        assert node.extra_tools == []

    def test_from_row_empty_string_json_fields(self):
        row = {**_make_node().to_row()}
        row["caller_ids"] = ""
        node = AgentNode.from_row(row)
        assert node.caller_ids == []
```

#### T4: Concurrency Test for `append()` (P2)

**File:** `tests/integration/test_event_store_concurrency.py`

```python
import asyncio
from pathlib import Path
import pytest
from remora.core.event_store import EventStore
from remora.core.events import AgentStartEvent, AgentCompleteEvent, NodeDiscoveredEvent
from remora.core.projections import NodeProjection


@pytest.fixture
async def store(tmp_path: Path):
    s = EventStore(tmp_path / "test.db", projection=NodeProjection())
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_concurrent_status_updates(store: EventStore):
    """Multiple concurrent status updates on same node should not corrupt state."""
    # Create node first
    await store.append("s", NodeDiscoveredEvent(
        node_id="node1", node_type="function", name="f",
        full_name="function:f", file_path="/f.py",
        start_line=1, end_line=5, source_code="def f(): pass",
        source_hash="h",
    ))

    # Fire 10 start/complete cycles concurrently
    async def cycle(i: int):
        await store.append("s", AgentStartEvent(
            graph_id=f"g{i}", agent_id="node1", node_name="f",
        ))
        await store.append("s", AgentCompleteEvent(
            graph_id=f"g{i}", agent_id="node1", result_summary=f"done-{i}",
        ))

    await asyncio.gather(*[cycle(i) for i in range(10)])

    # Final state should be idle (all cycles completed)
    node = await store.get_node("node1")
    assert node is not None
    assert node.status == "idle"


@pytest.mark.asyncio
async def test_concurrent_discovery_different_nodes(store: EventStore):
    """Discovering many different nodes concurrently should not lose any."""
    async def discover(i: int):
        await store.append("s", NodeDiscoveredEvent(
            node_id=f"node_{i}", node_type="function", name=f"f{i}",
            full_name=f"function:f{i}", file_path="/f.py",
            start_line=i, end_line=i+5, source_code=f"def f{i}(): pass",
            source_hash=f"h{i}",
        ))

    await asyncio.gather(*[discover(i) for i in range(50)])

    nodes = await store.list_nodes()
    assert len(nodes) == 50
```

#### T5: Extension Error Handling (P2)

**File:** `tests/unit/test_extensions.py`

```python
class TestExtensionErrorHandling:
    def test_load_malformed_python_file(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "broken.py").write_text("def foo(:\n  pass\n")  # syntax error
        (models_dir / "good.py").write_text(textwrap.dedent("""\
            from remora.extensions import AgentExtension
            class GoodExt(AgentExtension):
                @staticmethod
                def matches(node_type: str, name: str) -> bool:
                    return True
                @staticmethod
                def get_extension_data() -> dict:
                    return {"extension_name": "Good"}
        """))
        exts = load_extensions(models_dir)
        # Broken file should be skipped, good file should load
        assert len(exts) == 1
        assert exts[0].get_extension_data()["extension_name"] == "Good"

    def test_extension_matches_raises(self, tmp_path: Path):
        """An extension whose matches() raises should not crash the projection."""
        from remora.core.projections import NodeProjection

        class BadExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str) -> bool:
                raise ValueError("boom")

            @staticmethod
            def get_extension_data() -> dict:
                return {"extension_name": "Bad"}

        class GoodExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str) -> bool:
                return True

            @staticmethod
            def get_extension_data() -> dict:
                return {"extension_name": "Good"}

        # NOTE: This test documents CURRENT behavior.
        # Currently, BadExt.matches() raising would crash the projection.
        # The fix would be to add try/except in _project_node_discovered().
        proj = NodeProjection(extension_configs=[BadExt, GoodExt])
        # This SHOULD skip BadExt and fall through to GoodExt.
        # If it crashes, that's a bug to fix.
```

### 2.2 Remediation Checklist

| # | Gap | Test File | Blocking Phase 2? |
|---|-----|-----------|-------------------|
| T1 | `ToolSchema.to_llm_tool()` | `test_agent_node.py` | Yes |
| T2 | Extension with complex fields through projection | `test_projections.py` | Yes |
| T3 | `from_row()` error paths | `test_agent_node.py` | No |
| T4 | Concurrent `append()` | `test_event_store_concurrency.py` | No |
| T5 | Extension error handling | `test_extensions.py` | No |
| T6 | CSTNode -> NodeDiscoveredEvent conversion | Blocked until reconciler rewrite | No |
| T7 | New `conftest.py` fixtures | `conftest.py` | No (but do early) |

---

## 3. Test Infrastructure

### 3.1 New Fixtures for `conftest.py`

Add these to `tests/conftest.py` alongside the existing old-world fixtures:

```python
# ============================================================================
# EventBased fixtures (Phase 1+)
# ============================================================================

from remora.core.agent_node import AgentNode, ToolSchema
from remora.core.projections import NodeProjection
from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent
from remora.extensions import AgentExtension


def make_agent_node(**overrides) -> AgentNode:
    """Factory for test AgentNodes with sensible defaults."""
    defaults = {
        "node_id": "test_node_abc123",
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


def make_discovered_event(**overrides) -> NodeDiscoveredEvent:
    """Factory for test NodeDiscoveredEvents."""
    defaults = {
        "node_id": "test_node_abc123",
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
    return NodeDiscoveredEvent(**defaults)


@pytest.fixture
async def event_store_with_projection(tmp_path: Path) -> AsyncIterator[EventStore]:
    """EventStore with NodeProjection wired up."""
    projection = NodeProjection(extension_configs=[])
    store = EventStore(tmp_path / "events.db", projection=projection)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def seeded_store(tmp_path: Path) -> AsyncIterator[EventStore]:
    """EventStore pre-seeded with a few nodes for query/LSP tests."""
    projection = NodeProjection(extension_configs=[])
    store = EventStore(tmp_path / "events.db", projection=projection)
    await store.initialize()

    for i, (name, ntype) in enumerate([
        ("calculate_total", "function"),
        ("UserModel", "class"),
        ("test_billing", "function"),
    ]):
        await store.append("swarm", NodeDiscoveredEvent(
            node_id=f"node_{name}",
            node_type=ntype,
            name=name,
            full_name=f"{ntype}:{name}",
            file_path="/src/billing.py",
            start_line=i * 20 + 1,
            end_line=i * 20 + 15,
            source_code=f"def {name}(): pass",
            source_hash=f"hash_{name}",
        ))

    yield store
    await store.close()
```

### 3.2 Test Helpers Module

**File:** `tests/helpers.py` (extend existing)

```python
class FakeExtension(AgentExtension):
    """Configurable fake extension for tests."""

    def __init__(self, match_fn, data):
        self._match_fn = match_fn
        self._data = data

    def matches(self, node_type: str, name: str) -> bool:
        return self._match_fn(node_type, name)

    def get_extension_data(self) -> dict:
        return self._data
```

Note: This won't work because `matches()` and `get_extension_data()` are `@staticmethod` in the base class. The projection calls them as class methods (`ext.matches(...)`) not instance methods. A better pattern for tests is inline class definitions (as already done in the test files).

### 3.3 Extension Cache Cleanup

The module-level `_cache` in `extensions.py` persists across tests. Add a cleanup mechanism:

```python
# tests/conftest.py
from remora.extensions import _cache as _extension_cache

@pytest.fixture(autouse=True)
def clear_extension_cache():
    """Ensure extension cache doesn't leak between tests."""
    _extension_cache.clear()
    yield
    _extension_cache.clear()
```

---

## 4. Unit Test Plan by Component

### 4.1 AgentNode (`src/remora/core/agent_node.py`)

| Test Class | Test | Status | Notes |
|-----------|------|--------|-------|
| `TestAgentNodeCreation` | `test_create_minimal` | Exists | |
| | `test_create_with_extension_fields` | Exists | |
| | `test_create_with_all_fields` | **NEW** | Exercise every field including optionals |
| | `test_node_id_is_required` | **NEW** | Pydantic validation |
| `TestAgentNodeSerialization` | `test_to_row_basic` | Exists | |
| | `test_to_row_with_json_fields` | Exists | |
| | `test_from_row_round_trip` | Exists | |
| | `test_from_row_null_json_fields` | **NEW** | Handles None gracefully |
| | `test_from_row_malformed_json` | **NEW** | Raises on bad JSON |
| | `test_from_row_wrong_schema` | **NEW** | Raises on unexpected keys |
| | `test_to_row_from_row_with_all_statuses` | **NEW** | Each status round-trips |
| `TestToolSchema` | `test_to_llm_tool_basic` | **NEW** | |
| | `test_to_llm_tool_empty_params` | **NEW** | |
| | `test_to_code_action` | **NEW** | |
| `TestAgentNodeToSystemPrompt` | `test_basic_prompt` | Exists | |
| | `test_prompt_with_extension` | Exists | |
| | `test_prompt_with_graph_context` | Exists | |
| | `test_prompt_escape_source_code` | **NEW** | Source with triple backticks |
| | `test_prompt_empty_callers_callees` | **NEW** | Shows "None" |
| `TestAgentNodeLSP` | All 8 tests | Exist | |
| | `test_to_code_lens_pending_approval` | **NEW** | Uses pause icon |
| | `test_to_code_lens_unknown_status` | **NEW** | Falls back to "?" |
| | `test_to_document_symbol_unknown_type` | **NEW** | Falls back to Variable |
| | `test_to_hover_no_events` | **NEW** | Omits event section |

### 4.2 Events (`src/remora/core/events.py`)

| Test | Status | Notes |
|------|--------|-------|
| `test_node_discovered_create` | Exists | |
| `test_node_discovered_frozen` | Exists | |
| `test_node_removed_create` | Exists | |
| `test_node_discovered_with_parent_id` | **NEW** | |
| `test_node_discovered_default_timestamp` | **NEW** | Verify > 0 and monotonic |
| `test_all_events_have_timestamp` | **NEW** | Parametrized over all event types |
| `test_agent_message_tags_mutability` | **NEW** | Demonstrate the list mutability bug |
| `test_event_dataclass_asdict` | **NEW** | Verify `dataclasses.asdict()` works on all events |

### 4.3 Projections (`src/remora/core/projections.py`)

| Test | Status | Notes |
|------|--------|-------|
| `test_insert_new_node` | Exists | |
| `test_upsert_existing_node` | Exists | |
| `test_extension_matching` | Exists | |
| `test_no_extension_match` | Exists | |
| `test_hydrate_from_projection` | Exists | |
| `test_agent_start_sets_running` | Exists | |
| `test_agent_complete_sets_idle` | Exists | |
| `test_agent_error_sets_error` | Exists | |
| `test_remove_deletes_row` | Exists | |
| `test_extension_with_extra_tools` | **NEW** (T2) | Complex field round-trip |
| `test_extension_with_extra_subscriptions` | **NEW** (T2) | Complex field round-trip |
| `test_upsert_preserves_status` | **NEW** | Should be unit test too |
| `test_start_nonexistent_node` | **NEW** | UPDATE on missing row is a no-op |
| `test_complete_nonexistent_node` | **NEW** | UPDATE on missing row is a no-op |
| `test_apply_irrelevant_event` | **NEW** | e.g., FileSavedEvent does nothing |
| `test_extension_raises_in_matches` | **NEW** | Error isolation |

### 4.4 EventStore (`src/remora/core/event_store.py`)

| Test | Status | Notes |
|------|--------|-------|
| All existing `test_event_store.py` | Exists | |
| `test_nodes_table_exists` | Exists | |
| `test_nodes_table_schema` | Exists | |
| `test_nodes_table_indexes` | Exists | |
| `test_append_projects_to_table` | Exists | |
| `test_get_node` | Exists | |
| `test_list_nodes` | Exists | |
| `test_list_nodes_by_file` | Exists | |
| `test_list_nodes_by_type` | Exists | |
| `test_get_node_no_projection` | **NEW** | Store without projection returns None |
| `test_list_nodes_empty` | **NEW** | No nodes returns [] |
| `test_list_nodes_ordering` | **NEW** | Ordered by file_path, start_line |
| `test_append_and_project_transaction` | **NEW** | After B2 fix: verify atomicity |
| `test_concurrent_appends` | **NEW** (T4) | |

### 4.5 Extensions (`src/remora/extensions.py`)

| Test | Status | Notes |
|------|--------|-------|
| `test_base_matches_returns_false` | Exists | |
| `test_base_get_extension_data_returns_empty` | Exists | |
| `test_load_from_empty_dir` | Exists | |
| `test_load_from_nonexistent_dir` | Exists | |
| `test_load_valid_extension` | Exists | |
| `test_mtime_caching` | Exists | |
| `test_load_order_alphabetical` | Exists | |
| `test_load_malformed_file` | **NEW** (T5) | Skips broken file |
| `test_cache_identity` | **NEW** | Assert `exts1 is exts2` |
| `test_cache_invalidation_on_mtime_change` | **NEW** | Touch file, reload |
| `test_multiple_classes_in_one_file` | **NEW** | Both collected |
| `test_ignores_imported_base_classes` | **NEW** | Only direct subclasses |

---

## 5. Integration Test Plan

### 5.1 Pipeline Integration (EventStore + Projection + AgentNode)

**File:** `tests/integration/test_agent_node_pipeline.py` (extend existing)

| Test | Status | Notes |
|------|--------|-------|
| `test_full_lifecycle` | Exists | discover -> start -> complete -> LSP -> remove |
| `test_re_discovery_preserves_status` | Exists | |
| `test_bulk_discovery_50_nodes` | **NEW** | Discover 50 nodes, verify all queryable |
| `test_file_rename_simulation` | **NEW** | Remove old nodes, discover new ones at new path |
| `test_error_recovery` | **NEW** | Agent errors, then re-run succeeds |
| `test_multiple_extensions_first_match_wins` | **NEW** | Two extensions match, first one's data is used |

### 5.2 Discovery -> Event Pipeline (Phase 2)

**File:** `tests/integration/test_discovery_to_events.py` (new, after reconciler rewrite)

| Test | Description |
|------|-------------|
| `test_discover_file_emits_events` | Run `discover()` on a Python file, convert CSTNodes to NodeDiscoveredEvents, verify events match |
| `test_discover_to_projection_round_trip` | Discover -> emit events -> project -> query -> verify AgentNode matches source |
| `test_diff_discovery_emits_remove_events` | Discover file v1, modify file, discover v2, verify removed nodes get NodeRemovedEvent |
| `test_discover_multilanguage` | Discover JS/TS/Rust files, verify events are emitted for each language |

### 5.3 Reactive Loop Integration (Phase 2+)

**File:** `tests/integration/test_reactive_loop.py` (new)

| Test | Description |
|------|-------------|
| `test_file_save_triggers_subscribed_agent` | Save file -> FileSavedEvent -> subscription match -> agent trigger |
| `test_agent_message_triggers_target` | Agent A sends message -> AgentMessageEvent -> Agent B triggered |
| `test_cascade_depth_limit` | Agent A triggers B triggers C triggers ... verify depth limit enforced |
| `test_cascade_cooldown` | Same event fires twice within cooldown period -> second trigger suppressed |
| `test_concurrent_agent_execution` | Multiple agents triggered simultaneously -> concurrency semaphore respected |
| `test_manual_trigger` | User triggers agent via ManualTriggerEvent -> agent executes |

### 5.4 LSP Server Integration (Phase 2)

**File:** `tests/integration/test_lsp_agentnode.py` (new)

| Test | Description |
|------|-------------|
| `test_code_lens_from_nodes_table` | Discover nodes -> query EventStore -> verify code lenses match |
| `test_hover_shows_node_info` | Hover over a discovered node -> verify markdown content |
| `test_code_actions_include_tools` | Node with extension tools -> code actions include tool commands |
| `test_document_symbols` | Verify document symbol tree matches discovered nodes |
| `test_status_update_refreshes_lens` | Agent runs -> code lens icon changes |

---

## 6. Neovim Integration Testing with asciinema

### 6.1 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Test Runner (pytest)                         │
├─────────────────────────────────────────────────────────────────────┤
│  1. Start asciinema recording                                       │
│  2. Launch Neovim in headless mode with --listen                    │
│  3. Send commands via nvim --remote-send or pynvim RPC              │
│  4. Wait for LSP server to respond                                  │
│  5. Assert on buffer state / LSP responses / event store contents   │
│  6. Stop recording                                                  │
│  7. Generate GIF from .cast file                                    │
│  8. Write pass/fail verdict                                         │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 Infrastructure

#### Test Harness

**File:** `tests/e2e/conftest.py`

```python
"""E2E test infrastructure for Neovim + Remora integration testing.

Uses asciinema for recording and pynvim for RPC control.
"""
import asyncio
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import pynvim
import pytest


@dataclass
class NvimSession:
    """A running Neovim instance with Remora LSP attached."""
    process: subprocess.Popen
    nvim: pynvim.Nvim
    socket_path: str
    recording_path: Path | None
    project_dir: Path

    def send_keys(self, keys: str, delay: float = 0.1) -> None:
        """Send keystrokes to Neovim."""
        self.nvim.input(keys)
        time.sleep(delay)

    def command(self, cmd: str) -> None:
        """Execute an ex command."""
        self.nvim.command(cmd)

    def get_buffer_lines(self) -> list[str]:
        """Get all lines from current buffer."""
        return list(self.nvim.current.buffer)

    def wait_for_lsp(self, timeout: float = 10.0) -> bool:
        """Wait for Remora LSP to attach."""
        start = time.time()
        while time.time() - start < timeout:
            clients = self.nvim.exec_lua("return vim.lsp.get_clients()", [])
            for c in clients:
                if "remora" in str(c.get("name", "")).lower():
                    return True
            time.sleep(0.5)
        return False

    def get_code_lenses(self) -> list[dict]:
        """Get code lenses from Remora LSP."""
        return self.nvim.exec_lua("""
            local lenses = vim.lsp.codelens.get(vim.api.nvim_get_current_buf())
            return lenses or {}
        """, [])

    def get_diagnostics(self) -> list[dict]:
        """Get diagnostics for current buffer."""
        return self.nvim.exec_lua("""
            return vim.diagnostic.get(vim.api.nvim_get_current_buf())
        """, [])


@pytest.fixture
async def nvim_session(tmp_path: Path) -> AsyncIterator[NvimSession]:
    """Launch a Neovim instance with Remora LSP and optional asciinema recording."""
    socket_path = str(tmp_path / "nvim.sock")
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Create a sample Python file
    (project_dir / "src").mkdir()
    (project_dir / "src" / "main.py").write_text(
        "def calculate_total(items):\n"
        "    return sum(items)\n\n"
        "def test_calculate():\n"
        "    assert calculate_total([1, 2, 3]) == 6\n"
    )

    # Create .remora config
    remora_dir = project_dir / ".remora"
    remora_dir.mkdir()
    (remora_dir / "config.toml").write_text(
        '[remora]\n'
        'discovery_paths = ["src/"]\n'
    )

    recording_path = None
    asciinema_proc = None

    if os.environ.get("REMORA_RECORD_E2E"):
        recording_path = tmp_path / "recording.cast"
        asciinema_proc = subprocess.Popen(
            ["asciinema", "rec", "--overwrite", str(recording_path),
             "--command", f"nvim --listen {socket_path} --headless"],
            cwd=str(project_dir),
        )
        time.sleep(2)  # Wait for nvim to start inside asciinema
    else:
        # Start Neovim directly in headless mode
        proc = subprocess.Popen(
            ["nvim", "--listen", socket_path, "--headless", "--clean"],
            cwd=str(project_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

    # Connect via RPC
    nvim = pynvim.attach("socket", path=socket_path)

    session = NvimSession(
        process=asciinema_proc or proc,
        nvim=nvim,
        socket_path=socket_path,
        recording_path=recording_path,
        project_dir=project_dir,
    )

    yield session

    # Cleanup
    nvim.command("qa!")
    session.process.wait(timeout=5)

    # Convert recording to GIF if it exists
    if recording_path and recording_path.exists():
        gif_path = recording_path.with_suffix(".gif")
        subprocess.run(
            ["agg", str(recording_path), str(gif_path)],
            check=False,  # Don't fail test if agg not installed
        )


@pytest.fixture
def record_e2e(request):
    """Marker fixture: set REMORA_RECORD_E2E=1 to enable recording."""
    return os.environ.get("REMORA_RECORD_E2E", "0") == "1"
```

#### GIF Generation Pipeline

```
asciinema rec  →  .cast file  →  agg (asciinema gif generator)  →  .gif file
                                  or
                                  svg-term  →  .svg file (better for PRs)
```

Tools required:
- `asciinema` -- terminal recording (available in nixpkgs)
- `agg` -- asciinema-to-gif converter (https://github.com/asciinema/agg, available in nixpkgs)
- `pynvim` -- Python Neovim RPC client (pip dependency)

### 6.3 E2E Test Scenarios

**File:** `tests/e2e/test_neovim_lsp.py`

#### Scenario 1: Code Lens Appears on Discovery

```python
@pytest.mark.e2e
async def test_code_lens_on_file_open(nvim_session: NvimSession):
    """Opening a Python file should show code lenses for discovered nodes."""
    # Open the file
    nvim_session.command(f"edit {nvim_session.project_dir}/src/main.py")
    time.sleep(1)

    # Wait for LSP to attach
    assert nvim_session.wait_for_lsp(timeout=15), "Remora LSP did not attach"

    # Wait for code lenses to appear
    time.sleep(3)  # Allow discovery + projection
    lenses = nvim_session.get_code_lenses()

    # Should have lenses for calculate_total and test_calculate
    lens_titles = [l.get("command", {}).get("title", "") for l in lenses]
    assert any("calculate_total" in t for t in lens_titles), \
        f"Expected calculate_total lens, got: {lens_titles}"

    # Pass/fail verdict
    PASS = len(lenses) >= 2
    print(f"[{'PASS' if PASS else 'FAIL'}] Code lens on file open: {len(lenses)} lenses")
    assert PASS
```

#### Scenario 2: Agent Status Updates in Real Time

```python
@pytest.mark.e2e
async def test_agent_status_updates(nvim_session: NvimSession):
    """Triggering an agent should update the code lens icon from idle to running to idle."""
    nvim_session.command(f"edit {nvim_session.project_dir}/src/main.py")
    assert nvim_session.wait_for_lsp(timeout=15)
    time.sleep(3)

    # Capture initial lenses (should show idle icon ●)
    initial_lenses = nvim_session.get_code_lenses()
    initial_titles = [l.get("command", {}).get("title", "") for l in initial_lenses]
    assert any("●" in t for t in initial_titles), "Expected idle icon"

    # Trigger agent via code action
    nvim_session.command("lua vim.lsp.buf.code_action()")
    time.sleep(1)

    # Select "Chat with this agent" (first action)
    nvim_session.send_keys("<CR>", delay=0.5)

    # Check that status changed to running (▶)
    time.sleep(1)
    running_lenses = nvim_session.get_code_lenses()
    running_titles = [l.get("command", {}).get("title", "") for l in running_lenses]

    # After agent completes, should return to idle (●)
    time.sleep(10)  # Wait for LLM response (mocked)
    final_lenses = nvim_session.get_code_lenses()
    final_titles = [l.get("command", {}).get("title", "") for l in final_lenses]
    assert any("●" in t for t in final_titles), "Expected idle icon after completion"
```

#### Scenario 3: Hover Shows Agent Info

```python
@pytest.mark.e2e
async def test_hover_shows_agent_info(nvim_session: NvimSession):
    """Hovering over a function should show agent node information."""
    nvim_session.command(f"edit {nvim_session.project_dir}/src/main.py")
    assert nvim_session.wait_for_lsp(timeout=15)
    time.sleep(3)

    # Move cursor to line 1 (calculate_total)
    nvim_session.command("normal! 1G")
    time.sleep(0.5)

    # Trigger hover
    nvim_session.command("lua vim.lsp.buf.hover()")
    time.sleep(2)

    # Check hover window content
    # (Implementation depends on how hover is rendered -- may need to check
    # floating window buffers or use nvim_buf_get_lines on the hover float)
    windows = nvim_session.nvim.windows
    hover_content = ""
    for win in windows:
        buf = win.buffer
        if buf != nvim_session.nvim.current.buffer:
            hover_content = "\n".join(buf[:])
            break

    assert "calculate_total" in hover_content, \
        f"Expected calculate_total in hover, got: {hover_content}"
    assert "Status" in hover_content
```

#### Scenario 4: File Edit Triggers Reactive Agent (Phase 2+)

```python
@pytest.mark.e2e
async def test_file_edit_triggers_agent(nvim_session: NvimSession):
    """Editing and saving a file should trigger subscribed agents."""
    nvim_session.command(f"edit {nvim_session.project_dir}/src/main.py")
    assert nvim_session.wait_for_lsp(timeout=15)
    time.sleep(3)

    # Edit the file
    nvim_session.command("normal! Godef new_function():\n    pass")
    nvim_session.command("write")
    time.sleep(2)

    # Check that new function was discovered
    lenses = nvim_session.get_code_lenses()
    lens_titles = [l.get("command", {}).get("title", "") for l in lenses]
    assert any("new_function" in t for t in lens_titles), \
        f"Expected new_function lens after edit, got: {lens_titles}"

    # If reactive subscriptions are configured, check that subscribed agents
    # were triggered (check event store for AgentStartEvent)
```

### 6.4 Pass/Fail Determination and GIF Playback

#### Verdict Format

Each E2E test produces a structured verdict:

```python
@dataclass
class E2EVerdict:
    test_name: str
    passed: bool
    duration_ms: float
    recording_path: Path | None
    gif_path: Path | None
    screenshot: bytes | None
    failure_reason: str | None
```

#### Verdict Report

**File:** `tests/e2e/conftest.py` (pytest plugin)

```python
@pytest.hookimpl(tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Capture E2E test results with recording paths."""
    if "e2e" not in item.keywords:
        return

    if call.when == "call":
        session = item.funcargs.get("nvim_session")
        if session and session.recording_path:
            gif_path = session.recording_path.with_suffix(".gif")
            verdict = E2EVerdict(
                test_name=item.name,
                passed=call.excinfo is None,
                duration_ms=call.duration * 1000,
                recording_path=session.recording_path,
                gif_path=gif_path if gif_path.exists() else None,
                screenshot=None,
                failure_reason=str(call.excinfo.value) if call.excinfo else None,
            )
            # Write verdict to JSON for CI consumption
            verdict_path = session.recording_path.with_suffix(".verdict.json")
            verdict_path.write_text(json.dumps(asdict(verdict), default=str))
```

#### Rapid Approval Workflow

For human review of E2E test recordings:

```bash
# Run E2E tests with recording enabled
REMORA_RECORD_E2E=1 pytest tests/e2e/ -v --tb=short

# View results
ls tests/e2e/recordings/
#   test_code_lens_on_file_open.gif      (visual)
#   test_code_lens_on_file_open.cast     (replayable)
#   test_code_lens_on_file_open.verdict.json (machine-readable)

# Quick review: open all GIFs
for gif in tests/e2e/recordings/*.gif; do
    xdg-open "$gif"  # or wezterm imgcat, kitty icat, etc.
done

# Replay interactively
asciinema play tests/e2e/recordings/test_code_lens_on_file_open.cast
```

#### CI Integration

```yaml
# .github/workflows/e2e.yml
name: E2E Tests
on:
  push:
    branches: [main]
  pull_request:

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: DeterminateSystems/nix-installer-action@main
      - uses: DeterminateSystems/magic-nix-cache-action@main
      - name: Run E2E tests
        run: |
          REMORA_RECORD_E2E=1 nix develop --command \
            pytest tests/e2e/ -v --tb=short
      - name: Upload recordings
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: e2e-recordings
          path: tests/e2e/recordings/
```

### 6.5 E2E Test Matrix

| Scenario | Phase | Neovim | LSP | LLM | Description |
|----------|-------|--------|-----|-----|-------------|
| Code lens on open | Phase 2 | Real | Real | None | Open file -> lenses appear |
| Hover info | Phase 2 | Real | Real | None | Hover -> node info shown |
| Code actions | Phase 2 | Real | Real | None | Code action menu has Remora items |
| Agent chat | Phase 2+ | Real | Real | Mock | Chat command -> LLM response |
| Agent rewrite | Phase 2+ | Real | Real | Mock | Rewrite -> proposal shown |
| File save trigger | Phase 2+ | Real | Real | Mock | Save -> agent triggered |
| Multi-agent cascade | Phase 3 | Real | Real | Mock | Agent A -> B -> C chain |
| Human approval flow | Phase 3 | Real | Real | Mock | Agent proposes -> user approves |
| Error recovery | Phase 2+ | Real | Real | Mock | Agent fails -> error status |
| Extension hot-reload | Phase 3 | Real | Real | None | Edit extension -> behavior changes |

---

## 7. Performance and Load Testing

### 7.1 Discovery Performance

**File:** `tests/benchmarks/test_discovery_performance.py` (extend existing)

| Benchmark | Description | Target |
|-----------|-------------|--------|
| `bench_discover_100_functions` | Parse a file with 100 functions | <100ms |
| `bench_discover_1000_node_project` | Full project with ~1000 nodes | <2s |
| `bench_cstnode_to_event_conversion` | Convert 1000 CSTNodes to events | <10ms |

### 7.2 EventStore Performance

**File:** `tests/benchmarks/test_event_store_performance.py` (new)

| Benchmark | Description | Target |
|-----------|-------------|--------|
| `bench_append_1000_events` | Append 1000 events with projection | <5s |
| `bench_append_1000_events_no_projection` | Append without projection | <2s |
| `bench_list_nodes_1000` | Query 1000 nodes | <100ms |
| `bench_get_node_single` | Single node lookup | <5ms |
| `bench_concurrent_append_100` | 100 concurrent appends | <10s |

### 7.3 Reactive Loop Performance

**File:** `tests/benchmarks/test_reactive_loop_performance.py` (new, Phase 2+)

| Benchmark | Description | Target |
|-----------|-------------|--------|
| `bench_subscription_matching_100_subs` | Match event against 100 subscriptions | <10ms |
| `bench_subscription_matching_1000_subs` | Match against 1000 subscriptions | <50ms |
| `bench_cascade_chain_depth_10` | 10-deep cascade chain | <30s |
| `bench_event_throughput` | Events/second with full pipeline | >100 events/s |

### 7.4 LSP Response Time

**File:** `tests/benchmarks/test_lsp_response_time.py` (new, Phase 2+)

| Benchmark | Description | Target |
|-----------|-------------|--------|
| `bench_code_lens_100_nodes` | Generate lenses for 100 nodes | <50ms |
| `bench_hover_response` | Generate hover for one node | <10ms |
| `bench_code_action_generation` | Generate actions for one node | <5ms |

---

## 8. Regression Testing Strategy

### 8.1 Phase 2 Migration Regression Plan

As Phase 2 replaces old components with new ones, each migration step needs regression tests:

| Migration Step | Regression Tests |
|---------------|-----------------|
| Reconciler emits NodeDiscoveredEvent | Existing reconciler tests still pass + new event tests |
| AgentRunner loads from nodes table | Agent runner tests work with EventStore instead of JSONL |
| SwarmExecutor uses AgentNode | Swarm tests pass with AgentNode instead of AgentMetadata |
| LSP handlers use EventStore queries | LSP integration tests produce same responses |
| Remove deprecated files | All imports resolve, no test failures |

### 8.2 Existing Test Compatibility

The existing test suite uses old fixtures (`agent_state`, `swarm_state`, `agent_metadata`). During migration:

1. **Keep both fixture sets** in `conftest.py` until migration is complete.
2. **Mark old fixtures** with a `# DEPRECATED: Phase 2 will remove` comment.
3. **Run the full test suite** (`pytest tests/`) at each migration step.
4. **When a test is migrated** from old to new fixtures, update the test and remove old fixture usage.

### 8.3 Continuous Verification

```bash
# Quick check (unit tests only, <5s)
pytest tests/unit/ -x -q

# Standard check (unit + integration, <30s)
pytest tests/unit/ tests/integration/ -x -q

# Full check (everything except E2E, <60s)
pytest tests/ --ignore=tests/e2e/ -x -q

# E2E check (requires Neovim, <120s)
REMORA_RECORD_E2E=1 pytest tests/e2e/ -v

# Performance check (benchmarks, <60s)
pytest tests/benchmarks/ -v --benchmark-only
```

---

## Appendix A: Test File Map

```
tests/
├── conftest.py                          # Shared fixtures (old + new)
├── helpers.py                           # Test utilities
├── unit/
│   ├── test_agent_node.py               # AgentNode model (exists, extend)
│   ├── test_extensions.py               # Extension loader (exists, extend)
│   ├── test_node_events.py              # Node lifecycle events (exists, extend)
│   ├── test_nodes_table.py              # Schema verification (exists)
│   ├── test_projections.py              # NodeProjection (exists, extend)
│   ├── test_event_store.py              # EventStore base (exists)
│   ├── test_event_store_projection.py   # Append -> projection (exists)
│   ├── test_event_store_nodes_query.py  # get_node/list_nodes (exists)
│   ├── test_subscriptions.py            # SubscriptionPattern/Registry (exists)
│   ├── test_event_bus.py                # EventBus (exists)
│   └── ... (existing tests)
├── integration/
│   ├── test_agent_node_pipeline.py      # Full lifecycle (exists, extend)
│   ├── test_event_store_concurrency.py  # Concurrent operations (NEW)
│   ├── test_discovery_to_events.py      # CSTNode -> Event pipeline (NEW, Phase 2)
│   ├── test_reactive_loop.py            # Event -> subscription -> trigger (NEW, Phase 2+)
│   ├── test_lsp_agentnode.py            # LSP with AgentNode (NEW, Phase 2)
│   └── ... (existing tests)
├── e2e/
│   ├── conftest.py                      # NvimSession, asciinema infra (NEW)
│   ├── test_neovim_lsp.py              # Neovim E2E scenarios (NEW)
│   └── recordings/                      # .cast + .gif output (gitignored)
├── benchmarks/
│   ├── test_discovery_performance.py    # Discovery benchmarks (exists)
│   ├── test_event_store_performance.py  # EventStore benchmarks (NEW)
│   ├── test_reactive_loop_performance.py # Reactive loop benchmarks (NEW, Phase 2+)
│   └── test_lsp_response_time.py        # LSP response benchmarks (NEW, Phase 2+)
└── roundtrip/
    └── run_harness.py                   # Discovery roundtrip (exists)
```

## Appendix B: Dependencies to Add

```toml
# pyproject.toml [project.optional-dependencies]
test = [
    "pytest",
    "pytest-asyncio",
    "pytest-benchmark",     # For performance tests
    "pynvim",               # For E2E Neovim tests
]

# System dependencies (nixpkgs)
# asciinema    - Terminal recording
# agg          - asciinema GIF generator
# neovim       - E2E testing target
```

---

*End of Test Plan*
