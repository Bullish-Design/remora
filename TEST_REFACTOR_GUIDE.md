# Remora Test Suite Refactoring Guide

This guide provides a comprehensive analysis of the test suite and step-by-step instructions for bringing it up to the standards required by the new reactive swarm architecture.

---

## Part 1: Current State Analysis

### 1.1 Test Suite Statistics

| Metric | Value |
|--------|-------|
| Total Test Files | 26 |
| Total Tests | 98 |
| Line Coverage | 32% (2084/3082 lines) |
| Unit Tests | 18 |
| Integration Tests | 52 |
| Benchmarks | 3 |
| Skipped Tests | ~10 |

### 1.2 Coverage by Module

| Module | Coverage | Assessment |
|--------|----------|------------|
| `core/subscriptions.py` | 85% | Good |
| `core/events.py` | 90% | Good |
| `core/event_store.py` | 75% | Good |
| `core/event_bus.py` | 70% | Adequate |
| `core/swarm_state.py` | 80% | Good |
| `core/agent_state.py` | 90% | Good |
| `core/agent_runner.py` | 25% | **Critical Gap** |
| `core/swarm_executor.py` | 15% | **Critical Gap** |
| `core/reconciler.py` | 60% | Adequate |
| `core/discovery.py` | 30% | **Needs Work** |
| `core/workspace.py` | 40% | Adequate |
| `core/config.py` | 80% | Good |
| `nvim/server.py` | 0% | **Critical Gap** |
| `service/chat_service.py` | 0% | **Critical Gap** |
| `cli/main.py` | 22% | **Needs Work** |

### 1.3 Critical Issues

1. **Skipped AgentRunner Tests**: `test_agent_runner.py` has module-level `pytest.skip()` preventing all tests from running

2. **No NvimServer Tests**: Zero coverage on the Neovim integration

3. **No Chat Service Tests**: Zero coverage on chat functionality

4. **External Service Dependencies**: Many integration tests require vLLM server or Cairn/AgentFS

5. **Inconsistent Test Organization**: Mix of patterns and naming conventions

---

## Part 2: Test Suite Refactoring Plan

### Phase 1: Fix Critical Test Issues

#### Step 1.1: Fix AgentRunner Tests

**File**: `tests/integration/test_agent_runner.py`

**Problem**: Module-level `pytest.skip()` prevents tests from running.

**Solution**: Replace module-level skip with conditional skip markers:

```python
# REMOVE THIS (lines 9-14):
# pytest.skip(
#     "AgentRunner integration tests rely on structured_agents imports that hang in this environment",
#     allow_module_level=True,
# )

# ADD THIS at module level:
import pytest
from unittest.mock import patch, AsyncMock

# Check if structured_agents is importable
try:
    from structured_agents.kernel import AgentKernel
    HAS_STRUCTURED_AGENTS = True
except ImportError:
    HAS_STRUCTURED_AGENTS = False

pytestmark = pytest.mark.skipif(
    not HAS_STRUCTURED_AGENTS,
    reason="structured_agents not available"
)
```

**Alternative**: Create mock for `SwarmExecutor` so tests don't need real `structured_agents`:

```python
@pytest.fixture
def mock_executor():
    """Mock SwarmExecutor for AgentRunner tests."""
    executor = AsyncMock()
    executor.run_agent = AsyncMock(return_value="Mock response")
    return executor

@pytest.mark.asyncio
async def test_depth_limit_enforced(runner_config, runner_components, tmp_path, mock_executor):
    event_store, subscriptions, swarm_state = runner_components
    runner = AgentRunner(...)
    runner._executor = mock_executor  # Inject mock
    # ... rest of test
```

---

#### Step 1.2: Add NvimServer Tests

**Create**: `tests/unit/test_nvim_server.py`

```python
"""Tests for NvimServer JSON-RPC functionality."""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from remora.nvim.server import NvimServer
from remora.core.event_store import EventStore
from remora.core.subscriptions import SubscriptionRegistry, SubscriptionPattern
from remora.core.events import ContentChangedEvent, AgentMessageEvent


@pytest.fixture
async def nvim_server(tmp_path: Path):
    """Create a NvimServer for testing."""
    subscriptions = SubscriptionRegistry(tmp_path / "subs.db")
    await subscriptions.initialize()

    event_store = EventStore(tmp_path / "events.db", subscriptions=subscriptions)
    await event_store.initialize()

    socket_path = tmp_path / "test.sock"
    server = NvimServer(
        socket_path=socket_path,
        event_store=event_store,
        subscriptions=subscriptions,
        project_root=tmp_path,
    )
    await server.start()
    yield server
    await server.stop()
    await event_store.close()
    await subscriptions.close()


@pytest.mark.asyncio
async def test_swarm_emit_content_changed(nvim_server, tmp_path):
    """Test swarm.emit method with ContentChangedEvent."""
    params = {
        "event_type": "ContentChangedEvent",
        "data": {"path": "src/main.py", "diff": "test diff"},
    }
    result = await nvim_server._handle_swarm_emit(params)
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_agent_select(nvim_server):
    """Test agent.select returns subscriptions."""
    # Register a subscription first
    await nvim_server._subscriptions.register(
        "test-agent",
        SubscriptionPattern(to_agent="test-agent"),
    )

    params = {"agent_id": "test-agent"}
    result = await nvim_server._handle_agent_select(params)

    assert result["agent_id"] == "test-agent"
    assert len(result["subscriptions"]) >= 1


@pytest.mark.asyncio
async def test_agent_chat(nvim_server):
    """Test agent.chat sends message event."""
    params = {"agent_id": "test-agent", "message": "Hello agent!"}
    result = await nvim_server._handle_agent_chat(params)
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_agent_subscribe(nvim_server):
    """Test agent.subscribe registers subscription."""
    params = {
        "agent_id": "test-agent",
        "pattern": {"event_types": ["ContentChangedEvent"]},
    }
    result = await nvim_server._handle_agent_subscribe(params)
    assert "subscription_id" in result


@pytest.mark.asyncio
async def test_invalid_event_type(nvim_server):
    """Test handling of unknown event type."""
    params = {
        "event_type": "NonExistentEvent",
        "data": {},
    }
    with pytest.raises(ValueError, match="Unknown event type"):
        await nvim_server._handle_swarm_emit(params)


@pytest.mark.asyncio
async def test_error_response_format(nvim_server):
    """Test error response follows JSON-RPC format."""
    response = nvim_server._error_response(1, -32601, "Method not found")
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert response["error"]["code"] == -32601
```

---

#### Step 1.3: Add Chat Service Tests

**Create**: `tests/unit/test_chat_service.py`

```python
"""Tests for ChatService functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

# Import once chat_service is confirmed to exist and is testable
# from remora.service.chat_service import ChatService


@pytest.mark.skip(reason="ChatService needs review for testability")
class TestChatService:
    """Tests for ChatService."""

    @pytest.mark.asyncio
    async def test_send_message(self):
        """Test sending a message to an agent."""
        pass

    @pytest.mark.asyncio
    async def test_get_history(self):
        """Test retrieving chat history."""
        pass
```

---

### Phase 2: Add Missing Unit Tests

#### Step 2.1: Add Discovery Edge Case Tests

**File**: `tests/unit/test_discovery.py` (expand existing)

```python
"""Additional discovery tests for edge cases."""

import pytest
from pathlib import Path

from remora.core.discovery import (
    discover,
    compute_node_id,
    _detect_language,
    _parse_file,
)


class TestDiscoveryEdgeCases:
    """Test discovery edge cases."""

    def test_discover_empty_directory(self, tmp_path: Path):
        """Test discovery on empty directory returns empty list."""
        (tmp_path / "empty").mkdir()
        nodes = discover([tmp_path / "empty"])
        assert nodes == []

    def test_discover_binary_file_skipped(self, tmp_path: Path):
        """Test that binary files are skipped gracefully."""
        binary_file = tmp_path / "data.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03")
        # Should not raise, should return empty
        nodes = discover([tmp_path])
        assert not any(n.file_path.endswith(".bin") for n in nodes)

    def test_discover_unicode_filename(self, tmp_path: Path):
        """Test discovery handles unicode filenames."""
        unicode_file = tmp_path / "module_\u4e2d\u6587.py"
        unicode_file.write_text("def func():\n    pass\n")
        nodes = discover([tmp_path])
        assert len(nodes) >= 1

    def test_detect_language_unknown_extension(self):
        """Test unknown extension returns None."""
        assert _detect_language(Path("file.xyz")) is None

    def test_compute_node_id_deterministic(self):
        """Test node ID is deterministic for same inputs."""
        id1 = compute_node_id("src/main.py", "func", 10, 20)
        id2 = compute_node_id("src/main.py", "func", 10, 20)
        assert id1 == id2

    def test_compute_node_id_different_for_different_inputs(self):
        """Test node ID differs for different inputs."""
        id1 = compute_node_id("src/main.py", "func", 10, 20)
        id2 = compute_node_id("src/main.py", "func", 10, 21)
        assert id1 != id2


class TestTreeSitterParsing:
    """Test tree-sitter parsing specifics."""

    def test_parse_python_function(self, tmp_path: Path):
        """Test parsing Python function."""
        py_file = tmp_path / "example.py"
        py_file.write_text("""
def hello_world():
    '''A simple function.'''
    print("Hello, World!")
""")
        nodes = _parse_file(py_file, "python")
        func_nodes = [n for n in nodes if n.node_type == "function"]
        assert len(func_nodes) == 1
        assert func_nodes[0].name == "hello_world"

    def test_parse_python_class(self, tmp_path: Path):
        """Test parsing Python class."""
        py_file = tmp_path / "example.py"
        py_file.write_text("""
class MyClass:
    def method(self):
        pass
""")
        nodes = _parse_file(py_file, "python")
        class_nodes = [n for n in nodes if n.node_type == "class"]
        assert len(class_nodes) == 1
        assert class_nodes[0].name == "MyClass"
```

---

#### Step 2.2: Add SwarmExecutor Tests

**Create**: `tests/unit/test_swarm_executor.py`

```python
"""Tests for SwarmExecutor."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from remora.core.swarm_executor import SwarmExecutor, _state_to_cst_node
from remora.core.agent_state import AgentState
from remora.core.config import Config


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create test configuration."""
    return Config(
        project_path=str(tmp_path),
        bundle_root=str(tmp_path / "agents"),
        model_base_url="http://localhost:8000/v1",
        model_default="test/model",
    )


@pytest.fixture
def test_state() -> AgentState:
    """Create test agent state."""
    return AgentState(
        agent_id="test_agent",
        node_type="function",
        name="test_func",
        full_name="src.main.test_func",
        file_path="src/main.py",
        range=(1, 10),
    )


class TestStateToNode:
    """Test _state_to_cst_node conversion."""

    def test_converts_state_to_node(self, test_state):
        """Test conversion from AgentState to CSTNode."""
        node = _state_to_cst_node(test_state)

        assert node.node_id == test_state.agent_id
        assert node.node_type == test_state.node_type
        assert node.name == test_state.name
        assert node.file_path == test_state.file_path
        assert node.start_line == 1
        assert node.end_line == 10

    def test_handles_missing_range(self):
        """Test conversion when range is None."""
        state = AgentState(
            agent_id="test",
            node_type="function",
            name="test",
            full_name="test",
            file_path="test.py",
            range=None,
        )
        node = _state_to_cst_node(state)
        assert node.start_line == 1
        assert node.end_line == 1


class TestSwarmExecutorInit:
    """Test SwarmExecutor initialization."""

    @pytest.mark.asyncio
    async def test_creates_workspace_service(self, test_config, tmp_path):
        """Test executor creates workspace service."""
        with patch("remora.core.swarm_executor.EventStore"):
            with patch("remora.core.swarm_executor.SubscriptionRegistry"):
                executor = SwarmExecutor(
                    config=test_config,
                    event_bus=None,
                    event_store=AsyncMock(),
                    subscriptions=AsyncMock(),
                    swarm_id="test",
                    project_root=tmp_path,
                )
                assert executor._workspace_service is not None


class TestBundleResolution:
    """Test bundle path resolution."""

    def test_resolves_known_node_type(self, test_config, tmp_path):
        """Test bundle resolution for configured node type."""
        test_config.bundle_mapping = {"function": "function_agent"}

        with patch("remora.core.swarm_executor.EventStore"):
            executor = SwarmExecutor(
                config=test_config,
                event_bus=None,
                event_store=AsyncMock(),
                subscriptions=AsyncMock(),
                swarm_id="test",
                project_root=tmp_path,
            )

            state = AgentState(
                agent_id="test",
                node_type="function",
                name="test",
                full_name="test",
                file_path="test.py",
            )

            bundle_path = executor._resolve_bundle_path(state)
            assert "function_agent" in str(bundle_path)

    def test_falls_back_for_unknown_node_type(self, test_config, tmp_path):
        """Test bundle resolution falls back for unknown type."""
        with patch("remora.core.swarm_executor.EventStore"):
            executor = SwarmExecutor(
                config=test_config,
                event_bus=None,
                event_store=AsyncMock(),
                subscriptions=AsyncMock(),
                swarm_id="test",
                project_root=tmp_path,
            )

            state = AgentState(
                agent_id="test",
                node_type="unknown_type",
                name="test",
                full_name="test",
                file_path="test.py",
            )

            bundle_path = executor._resolve_bundle_path(state)
            assert str(bundle_path) == test_config.bundle_root
```

---

### Phase 3: Integration Test Improvements

#### Step 3.1: Add Mock Alternatives for vLLM Tests

**File**: `tests/integration/helpers.py`

```python
# Add mock LLM client factory

def create_mock_llm_client(responses: list[str] | None = None):
    """Create a mock LLM client for testing without vLLM.

    Args:
        responses: List of responses to return in order

    Returns:
        Mock client with deterministic responses
    """
    from unittest.mock import AsyncMock, MagicMock

    responses = responses or ["Mock LLM response"]
    response_iter = iter(responses * 100)  # Repeat to avoid exhaustion

    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        side_effect=lambda *args, **kwargs: MagicMock(
            choices=[MagicMock(message=MagicMock(content=next(response_iter)))]
        )
    )
    return client
```

---

#### Step 3.2: Make Cairn Tests Conditional

**File**: `tests/integration/cairn/conftest.py`

```python
# Add at top of file
import pytest

def cairn_available() -> bool:
    """Check if Cairn/AgentFS is available."""
    try:
        from cairn.runtime import workspace_manager
        return True
    except ImportError:
        return False

# Apply skip marker to all tests in this directory
pytestmark = pytest.mark.skipif(
    not cairn_available(),
    reason="Cairn/AgentFS not available"
)
```

---

### Phase 4: Test Organization and Naming

#### Step 4.1: Standardize Test Naming

All test files should follow the pattern:
- `test_<module_name>.py` for unit tests
- `test_<feature>_integration.py` for integration tests
- `test_<feature>_real.py` for tests requiring external services

**Renames needed**:
- `test_reconcile_real.py` -> `test_reconciler_integration.py`
- `test_real_code_discovery_real.py` -> `test_discovery_real.py`
- `test_multilanguage_discovery_real.py` -> `test_discovery_multilang_real.py`

---

#### Step 4.2: Add Test Docstrings

All test functions should have docstrings explaining:
1. What is being tested
2. Expected behavior
3. Why this matters

**Example**:
```python
def test_cascade_depth_limit_prevents_infinite_loops():
    """Test that cascade depth limit prevents infinite agent loops.

    When an agent triggers another agent which triggers the first,
    the depth limit should halt the cascade after N iterations.
    This is critical for preventing runaway agent execution.
    """
```

---

### Phase 5: Test Infrastructure Improvements

#### Step 5.1: Add Shared Mock Factory

**Create**: `tests/mocks/__init__.py`

```python
"""Shared mock factories for Remora tests."""

from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from remora.core.agent_state import AgentState
from remora.core.swarm_state import AgentMetadata


def create_agent_state(
    agent_id: str = "test_agent",
    node_type: str = "function",
    name: str = "test_func",
    file_path: str = "src/main.py",
    **kwargs,
) -> AgentState:
    """Factory for creating test AgentState objects."""
    return AgentState(
        agent_id=agent_id,
        node_type=node_type,
        name=name,
        full_name=f"{file_path.replace('/', '.')}.{name}",
        file_path=file_path,
        **kwargs,
    )


def create_agent_metadata(
    agent_id: str = "test_agent",
    node_type: str = "function",
    **kwargs,
) -> AgentMetadata:
    """Factory for creating test AgentMetadata objects."""
    return AgentMetadata(
        agent_id=agent_id,
        node_type=node_type,
        name=kwargs.get("name", "test_func"),
        full_name=kwargs.get("full_name", "src.main.test_func"),
        file_path=kwargs.get("file_path", "src/main.py"),
        start_line=kwargs.get("start_line", 1),
        end_line=kwargs.get("end_line", 10),
    )


def create_mock_kernel(responses: list[str] | None = None):
    """Factory for creating mock LLM kernels."""
    responses = responses or ["Mock response"]
    response_iter = iter(responses * 100)

    kernel = AsyncMock()
    kernel.run = AsyncMock(
        side_effect=lambda *args, **kwargs: MagicMock(
            content=next(response_iter),
            tool_calls=[],
            __str__=lambda self: self.content,
        )
    )
    kernel.close = AsyncMock()
    return kernel


def create_mock_workspace():
    """Factory for creating mock AgentWorkspace."""
    workspace = AsyncMock()
    workspace.read = AsyncMock(return_value="# Mock file content\n")
    workspace.write = AsyncMock()
    workspace.exists = AsyncMock(return_value=True)
    workspace.list_dir = AsyncMock(return_value=["file1.py", "file2.py"])
    return workspace
```

---

#### Step 5.2: Add Performance Regression Tests

**Create**: `tests/benchmarks/test_event_processing_perf.py`

```python
"""Performance regression tests for event processing."""

import pytest
import time
import asyncio

from remora.core.event_store import EventStore
from remora.core.subscriptions import SubscriptionPattern, SubscriptionRegistry
from remora.core.events import ContentChangedEvent


@pytest.mark.benchmark
class TestEventProcessingPerformance:
    """Benchmark event processing throughput."""

    @pytest.mark.asyncio
    async def test_event_append_throughput(self, tmp_path):
        """Benchmark: append 1000 events should complete in < 2 seconds."""
        subscriptions = SubscriptionRegistry(tmp_path / "subs.db")
        await subscriptions.initialize()

        event_store = EventStore(tmp_path / "events.db", subscriptions=subscriptions)
        await event_store.initialize()

        start = time.perf_counter()
        for i in range(1000):
            await event_store.append(
                "test-swarm",
                ContentChangedEvent(path=f"file_{i}.py"),
            )
        elapsed = time.perf_counter() - start

        await event_store.close()
        await subscriptions.close()

        assert elapsed < 2.0, f"Event append too slow: {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_subscription_matching_throughput(self, tmp_path):
        """Benchmark: match against 100 subscriptions should be < 10ms."""
        subscriptions = SubscriptionRegistry(tmp_path / "subs.db")
        await subscriptions.initialize()

        # Register 100 subscriptions
        for i in range(100):
            await subscriptions.register(
                f"agent_{i}",
                SubscriptionPattern(path_glob=f"src/module_{i % 10}/*.py"),
            )

        event = ContentChangedEvent(path="src/module_5/utils.py")

        start = time.perf_counter()
        matching = await subscriptions.get_matching_agents(event)
        elapsed = time.perf_counter() - start

        await subscriptions.close()

        assert elapsed < 0.01, f"Subscription matching too slow: {elapsed*1000:.2f}ms"
```

---

## Part 3: Updated Test Structure

After implementing all changes, the test structure should be:

```
tests/
├── conftest.py                          # Root fixtures
├── mocks/                               # NEW: Shared mock factories
│   ├── __init__.py
│   └── factories.py
├── unit/
│   ├── test_event_bus.py               # EventBus tests
│   ├── test_event_store.py             # EventStore tests
│   ├── test_subscriptions.py           # Subscription tests
│   ├── test_swarm_state.py             # SwarmState tests
│   ├── test_agent_state.py             # NEW: AgentState tests
│   ├── test_discovery.py               # Discovery tests (expanded)
│   ├── test_swarm_executor.py          # NEW: SwarmExecutor tests
│   ├── test_nvim_server.py             # NEW: NvimServer tests
│   ├── test_chat_service.py            # NEW: ChatService tests
│   └── test_fs.py                      # FS utility tests
├── integration/
│   ├── conftest.py                     # Integration fixtures
│   ├── helpers.py                      # Test helpers (expanded)
│   ├── test_agent_runner.py            # FIXED: AgentRunner tests
│   ├── test_event_store_integration.py # EventStore integration
│   ├── test_reconciler_integration.py  # RENAMED
│   ├── test_discovery_real.py          # RENAMED
│   ├── test_discovery_multilang_real.py # RENAMED
│   ├── test_cli_real.py                # CLI tests
│   ├── test_vllm_real.py               # vLLM integration
│   └── cairn/                          # Cairn workspace tests
│       ├── conftest.py                 # UPDATED: conditional skip
│       └── ...
└── benchmarks/
    ├── test_discovery_performance.py   # Discovery benchmarks
    └── test_event_processing_perf.py   # NEW: Event benchmarks
```

---

## Part 4: Verification Checklist

After implementing test refactoring:

- [ ] All tests pass: `pytest tests/`
- [ ] No skipped tests that should be running
- [ ] Coverage increased to >50% overall
- [ ] No external service required for `pytest tests/unit/`
- [ ] All test files have consistent naming
- [ ] All test functions have docstrings
- [ ] Mock factories are reusable across test modules
- [ ] Performance baselines established

---

## Part 5: Coverage Goals

Target coverage after refactoring:

| Module | Current | Target |
|--------|---------|--------|
| `core/agent_runner.py` | 25% | 70% |
| `core/swarm_executor.py` | 15% | 60% |
| `core/discovery.py` | 30% | 70% |
| `nvim/server.py` | 0% | 60% |
| `service/chat_service.py` | 0% | 50% |
| `cli/main.py` | 22% | 50% |
| **Overall** | 32% | 55% |

---

## Implementation Priority

1. **P0 (Critical)**: Fix `test_agent_runner.py` skip issue
2. **P0 (Critical)**: Add NvimServer basic tests
3. **P1 (High)**: Add SwarmExecutor tests
4. **P1 (High)**: Expand discovery tests
5. **P2 (Medium)**: Add mock factories
6. **P2 (Medium)**: Add performance benchmarks
7. **P3 (Low)**: Rename test files for consistency
8. **P3 (Low)**: Add docstrings to all tests
