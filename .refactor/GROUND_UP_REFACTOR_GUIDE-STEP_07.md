# Implementation Guide for Step 7: Graph Executor

## Context

This guide is for implementing Step 7 of the Remora v0.4.0 ground-up refactor. This step creates the `GraphExecutor` that runs agents in dependency order using `structured-agents`' `Agent.from_bundle()`.

**Design document:** `.context/GROUND_UP_REFACTOR_IDEAS.md` (Ideas 2, 4)

## What You're Building

A new `executor.py` module that:
1. Defines `ExecutorState` dataclass for tracking execution progress
2. Provides `execute_agent()` function for running individual agents via `Agent.from_bundle()`
3. Implements `GraphExecutor` class for dependency-ordered batch execution with configurable concurrency

## Contract Touchpoints
- Set `STRUCTURED_AGENTS_BASE_URL` and `STRUCTURED_AGENTS_API_KEY` from `RemoraConfig.model` before bundle load.
- Provide the shared `EventBus` as the structured-agents Observer.
- Pass `CairnDataProvider` and `CairnResultHandler` to ensure Grail VFS + result persistence.

## Done Criteria
- [ ] `GraphExecutor` respects dependency ordering and concurrency limits.
- [ ] Errors obey `stop_graph`/`skip_downstream`/`continue` policy and emit `AgentErrorEvent`.
- [ ] Unit test runs an agent with a mocked bundle and verifies EventBus events.

## What You're Replacing

- **`src/remora/agent_graph.py`** — Contains the current `GraphExecutor` class with `_run_kernel()`, `_simulate_execution()`, and all the manual kernel wiring

## Target Location

- **CREATE:** `src/remora/executor.py` (~200 lines)
- **MODIFY:** `src/remora/__init__.py` (update exports)

---

## Implementation Steps

### Step 7.1: Create ExecutorState Dataclass

**File:** `src/remora/executor.py`

Add the following imports at the top:

```python
"""Graph Executor - Runs agents in dependency order using structured-agents v0.3."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.graph import AgentNode
    from remora.workspace import CairnWorkspace
```

Add the `ErrorPolicy` enum and `ExecutorState` dataclass:

```python
class ErrorPolicy(StrEnum):
    """Graph-level error handling policies."""
    STOP_GRAPH = "stop_graph"
    SKIP_DOWNSTREAM = "skip_downstream"
    CONTINUE = "continue"


@dataclass
class ExecutorState:
    """Tracks execution state across a graph run."""
    
    graph_id: str
    nodes: dict[str, "AgentNode"]
    completed: dict[str, "RunResult"] = field(default_factory=dict)
    pending: set[str] = field(default_factory=set)
    workspaces: dict[str, "CairnWorkspace"] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    
    def get_agent_state(self, agent_id: str) -> str:
        """Get current state of an agent.
        
        Returns:
            'completed' - Agent finished successfully
            'running'  - Agent is currently executing
            'pending'  - Agent has not started yet
            'failed'   - Agent failed (tracked in completed with error)
        """
        if agent_id in self.completed:
            result = self.completed[agent_id]
            if result is None or hasattr(result, 'error') and result.error:
                return "failed"
            return "completed"
        if agent_id in self.pending:
            return "running"
        return "pending"
    
    def mark_completed(self, agent_id: str, result: "RunResult | None") -> None:
        """Mark an agent as completed."""
        self.completed[agent_id] = result
        self.pending.discard(agent_id)
    
    def mark_started(self, agent_id: str) -> None:
        """Mark an agent as started."""
        self.pending.add(agent_id)
```

### Step 7.2: Create execute_agent() Function

**File:** `src/remora/executor.py`

Before calling `Agent.from_bundle()`, set `STRUCTURED_AGENTS_BASE_URL` and `STRUCTURED_AGENTS_API_KEY` from `RemoraConfig.model` so the bundle loader uses the correct model endpoint.

Add the `RunResult` type alias and `execute_agent()` function:

```python
from typing import Any, Protocol


class RunResult(Protocol):
    """Protocol for agent execution results."""
    
    @property
    def final_message(self) -> Any:
        ...
    
    @property
    def turn_count(self) -> int:
        ...
    
    @property
    def termination_reason(self) -> str:
        ...


async def execute_agent(
    node: "AgentNode",
    workspace: "CairnWorkspace",
    observer: Any,
) -> RunResult:
    """Execute a single agent using structured-agents v0.3.
    
    Args:
        node: The AgentNode to execute
        workspace: The Cairn workspace for this agent
        observer: EventBus/Observer for emitting events
        
    Returns:
        RunResult from the structured-agents kernel
    """
    from structured_agents import Agent
    
    # 1. Create CairnDataProvider for virtual filesystem population
    from remora.workspace import CairnDataProvider
    data_provider = CairnDataProvider(workspace)
    
    # 2. Create the agent via Agent.from_bundle()
    agent = await Agent.from_bundle(
        str(node.bundle_path),
        data_provider=data_provider,
        observer=observer,
    )
    
    # 3. Build the prompt from the target node
    prompt = _build_agent_prompt(node)
    
    # 4. Run the agent
    return await agent.run(prompt)


def _build_agent_prompt(node: "AgentNode") -> str:
    """Build the prompt for an agent from its target node."""
    prompt_parts = []
    
    # Add target information
    prompt_parts.append(f"# Target: {node.name}")
    prompt_parts.append(f"# Type: {node.node_type}")
    if node.target.file_path:
        prompt_parts.append(f"# File: {node.target.file_path}")
    prompt_parts.append("")
    prompt_parts.append(node.target.text)
    
    return "\n".join(prompt_parts)
```

### Step 7.3: Create ExecutionConfig Dataclass

**File:** `src/remora/executor.py`

Add the configuration dataclass:

```python
@dataclass
class ExecutionConfig:
    """Configuration for graph execution."""
    
    max_concurrency: int = 4
    timeout: float = 300.0
    error_policy: ErrorPolicy = ErrorPolicy.STOP_GRAPH
    
    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
```

### Step 7.4: Create GraphExecutor Class

**File:** `src/remora/executor.py`

Add the main executor class:

```python
class GraphExecutor:
    """Runs agents in dependency order with bounded concurrency.
    
    Usage:
        executor = GraphExecutor(config, event_bus)
        results = await executor.run(graph, workspace_config)
    """
    
    def __init__(self, config: ExecutionConfig, event_bus: Any):
        """Initialize the executor.
        
        Args:
            config: Execution configuration
            event_bus: EventBus for emitting lifecycle events
        """
        self.config = config
        self.event_bus = event_bus
    
    async def run(
        self,
        graph: list["AgentNode"],
        workspace_config: Any,
    ) -> dict[str, RunResult]:
        """Execute all agents in topological order.
        
        Args:
            graph: List of AgentNodes with dependency edges
            workspace_config: Configuration for creating workspaces
            
        Returns:
            Dict mapping agent_id to RunResult
        """
        from remora.graph import get_execution_batches
        from remora.workspace import create_workspace
        
        graph_id = uuid.uuid4().hex
        results: dict[str, RunResult] = {}
        state = ExecutorState(
            graph_id=graph_id,
            nodes={node.id: node for node in graph},
        )
        
        # Emit graph start event
        await self.event_bus.emit(GraphStartEvent(
            graph_id=graph_id,
            node_count=len(graph),
            timestamp=time.time(),
        ))
        
        # Get execution batches (nodes that can run in parallel)
        batches = get_execution_batches(graph)
        
        for batch in batches:
            # Create workspaces for this batch
            for node in batch:
                ws = await create_workspace(node.id, workspace_config)
                state.workspaces[node.id] = ws
            
            # Run batch (parallel or sequential based on config)
            if self.config.max_concurrency > 1:
                batch_results = await self._run_batch_parallel(batch, state)
            else:
                batch_results = await self._run_batch_sequential(batch, state)
            
            # Collect results and apply error policy
            for node, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    await self.event_bus.emit(AgentErrorEvent(
                        graph_id=graph_id,
                        agent_id=node.id,
                        error=str(result),
                        timestamp=time.time(),
                    ))
                    
                    if self.config.error_policy == ErrorPolicy.STOP_GRAPH:
                        # Stop execution on first error
                        await self._handle_stop_graph(graph_id, state)
                        break
                else:
                    results[node.id] = result
                    state.mark_completed(node.id, result)
        
        # Emit graph complete event
        await self.event_bus.emit(GraphCompleteEvent(
            graph_id=graph_id,
            node_count=len(graph),
            completed_count=len(results),
            timestamp=time.time(),
        ))
        
        return results
    
    async def _run_batch_parallel(
        self,
        batch: list["AgentNode"],
        state: ExecutorState,
    ) -> list[RunResult | Exception]:
        """Run a batch of nodes in parallel."""
        semaphore = asyncio.Semaphore(self.config.max_concurrency)
        
        async def run_with_semaphore(node: "AgentNode") -> RunResult | Exception:
            async with semaphore:
                return await self._run_node(node, state)
        
        tasks = [asyncio.create_task(run_with_semaphore(node)) for node in batch]
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _run_batch_sequential(
        self,
        batch: list["AgentNode"],
        state: ExecutorState,
    ) -> list[RunResult | Exception]:
        """Run a batch of nodes sequentially."""
        results = []
        for node in batch:
            try:
                result = await self._run_node(node, state)
                results.append(result)
            except Exception as e:
                results.append(e)
        return results
    
    async def _run_node(
        self,
        node: "AgentNode",
        state: ExecutorState,
    ) -> RunResult:
        """Run a single node."""
        workspace = state.workspaces[node.id]
        graph_id = state.graph_id
        
        # Emit start event
        await self.event_bus.emit(AgentStartEvent(
            graph_id=graph_id,
            agent_id=node.id,
            node_type=node.node_type,
            timestamp=time.time(),
        ))
        
        try:
            # Execute the agent
            result = await execute_agent(node, workspace, self.event_bus)
            
            # Emit complete event
            await self.event_bus.emit(AgentCompleteEvent(
                graph_id=graph_id,
                agent_id=node.id,
                turn_count=result.turn_count,
                termination=result.termination_reason,
                timestamp=time.time(),
            ))
            
            return result
            
        except Exception as e:
            await self.event_bus.emit(AgentErrorEvent(
                graph_id=graph_id,
                agent_id=node.id,
                error=str(e),
                timestamp=time.time(),
            ))
            
            if self.config.error_policy == ErrorPolicy.STOP_GRAPH:
                raise
            
            return None
    
    async def _handle_stop_graph(self, graph_id: str, state: ExecutorState) -> None:
        """Handle stop_graph error policy."""
        await self.event_bus.emit(GraphErrorEvent(
            graph_id=graph_id,
            error="Stopping due to error policy",
            timestamp=time.time(),
        ))
```

### Step 7.5: Add Event Type Definitions

**File:** `src/remora/executor.py`

Add the event dataclasses used by the executor:

```python
@dataclass(frozen=True)
class GraphStartEvent:
    """Emitted when a graph execution starts."""
    graph_id: str
    node_count: int
    timestamp: float


@dataclass(frozen=True)
class GraphCompleteEvent:
    """Emitted when a graph execution completes."""
    graph_id: str
    node_count: int
    completed_count: int
    timestamp: float


@dataclass(frozen=True)
class GraphErrorEvent:
    """Emitted when graph execution fails."""
    graph_id: str
    error: str
    timestamp: float


@dataclass(frozen=True)
class AgentStartEvent:
    """Emitted when an agent starts executing."""
    graph_id: str
    agent_id: str
    node_type: str
    timestamp: float


@dataclass(frozen=True)
class AgentCompleteEvent:
    """Emitted when an agent completes execution."""
    graph_id: str
    agent_id: str
    turn_count: int
    termination: str
    timestamp: float


@dataclass(frozen=True)
class AgentErrorEvent:
    """Emitted when an agent fails."""
    graph_id: str
    agent_id: str
    error: str
    timestamp: float
```

---

## Dependencies Required

Ensure these modules exist before implementing Step 7:

| Module | Purpose | Status |
|--------|---------|--------|
| `remora.graph` | `AgentNode` dataclass, `get_execution_batches()` | **MUST EXIST** (Step 5) |
| `remora.workspace` | `CairnDataProvider`, `create_workspace()` | **MUST EXIST** (Step 4) |
| `remora.events` | Event dataclass definitions | **MUST EXIST** (Step 1) |
| `structured-agents` | `Agent.from_bundle()`, `RunResult` | External dependency |

---

## Update Exports

**File:** `src/remora/__init__.py`

Add the new exports:

```python
from remora.executor import (
    GraphExecutor,
    ExecutorState,
    ExecutionConfig,
    ErrorPolicy,
    execute_agent,
)
```

Update `__all__`:

```python
__all__ = [
    # Core
    "GraphExecutor",
    "ExecutorState", 
    "ExecutionConfig",
    "ErrorPolicy",
    "execute_agent",
    # ... existing exports
]
```

---

## Testing Strategy

### Test 1: Unit Test for ExecutorState

**File:** `tests/unit/test_executor.py`

```python
import pytest
from remora.executor import ExecutorState, ErrorPolicy


class TestExecutorState:
    def test_initial_state(self):
        state = ExecutorState(graph_id="test-123", nodes={})
        
        assert state.graph_id == "test-123"
        assert state.get_agent_state("nonexistent") == "pending"
    
    def test_mark_started(self):
        nodes = {"agent-1": None}  # Mock nodes dict
        state = ExecutorState(graph_id="test", nodes=nodes)
        
        state.mark_started("agent-1")
        
        assert state.get_agent_state("agent-1") == "running"
    
    def test_mark_completed(self):
        nodes = {"agent-1": None}
        state = ExecutorState(graph_id="test", nodes=nodes)
        
        # Completed with successful result
        mock_result = type("MockResult", (), {"error": None})()
        state.mark_completed("agent-1", mock_result)
        
        assert state.get_agent_state("agent-1") == "completed"
```

### Test 2: Unit Test for ExecutionConfig

```python
import pytest
from remora.executor import ExecutionConfig, ErrorPolicy


class TestExecutionConfig:
    def test_default_values(self):
        config = ExecutionConfig()
        
        assert config.max_concurrency == 4
        assert config.timeout == 300.0
        assert config.error_policy == ErrorPolicy.STOP_GRAPH
    
    def test_custom_values(self):
        config = ExecutionConfig(
            max_concurrency=2,
            timeout=600.0,
            error_policy=ErrorPolicy.CONTINUE,
        )
        
        assert config.max_concurrency == 2
        assert config.timeout == 600.0
        assert config.error_policy == ErrorPolicy.CONTINUE
    
    def test_invalid_concurrency(self):
        with pytest.raises(ValueError):
            ExecutionConfig(max_concurrency=0)
    
    def test_invalid_timeout(self):
        with pytest.raises(ValueError):
            ExecutionConfig(timeout=-1)
```

### Test 3: Integration Test for GraphExecutor (with mocks)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remora.executor import GraphExecutor, ExecutionConfig, ErrorPolicy


class TestGraphExecutor:
    @pytest.fixture
    def mock_event_bus(self):
        bus = AsyncMock()
        bus.emit = AsyncMock()
        return bus
    
    @pytest.fixture
    def config(self):
        return ExecutionConfig(
            max_concurrency=2,
            error_policy=ErrorPolicy.STOP_GRAPH,
        )
    
    @pytest.mark.asyncio
    async def test_run_single_agent(self, config, mock_event_bus):
        # Create mock agent node
        mock_node = MagicMock()
        mock_node.id = "agent-1"
        mock_node.bundle_path = "/path/to/bundle"
        mock_node.node_type = "function"
        mock_node.name = "test_agent"
        
        # Mock execute_agent
        mock_result = MagicMock()
        mock_result.turn_count = 3
        mock_result.termination_reason = "submit_result"
        
        with patch("remora.executor.execute_agent", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_result
            
            executor = GraphExecutor(config, mock_event_bus)
            
            # Need to mock workspace creation too
            with patch("remora.executor.create_workspace", new_callable=AsyncMock) as mock_ws:
                mock_ws.return_value = MagicMock()
                
                # Create mock graph with get_execution_batches
                with patch("remora.executor.get_execution_batches") as mock_batches:
                    mock_batches.return_value = [[mock_node]]
                    
                    results = await executor.run([mock_node], MagicMock())
        
        # Verify execute_agent was called
        mock_exec.assert_called_once()
        
        # Verify events were emitted
        assert mock_event_bus.emit.call_count >= 2  # Start + Complete
    
    @pytest.mark.asyncio
    async def test_error_policy_continue(self, config, mock_event_bus):
        config.error_policy = ErrorPolicy.CONTINUE
        
        mock_node = MagicMock()
        mock_node.id = "agent-1"
        mock_node.bundle_path = "/path/to/bundle"
        
        with patch("remora.executor.execute_agent", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = Exception("Agent failed")
            
            with patch("remora.executor.create_workspace", new_callable=AsyncMock):
                with patch("remora.executor.get_execution_batches") as mock_batches:
                    mock_batches.return_value = [[mock_node]]
                    
                    executor = GraphExecutor(config, mock_event_bus)
                    results = await executor.run([mock_node], MagicMock())
        
        # Should complete without raising despite error
        assert "agent-1" not in results
    
    @pytest.mark.asyncio
    async def test_error_policy_stop_graph(self, config, mock_event_bus):
        config.error_policy = ErrorPolicy.STOP_GRAPH
        
        mock_node1 = MagicMock()
        mock_node1.id = "agent-1"
        mock_node1.bundle_path = "/path/to/bundle"
        
        mock_node2 = MagicMock()
        mock_node2.id = "agent-2"
        mock_node2.bundle_path = "/path/to/bundle"
        
        call_count = 0
        
        async def mock_execute(node, *args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Agent 1 failed")
            return MagicMock(turn_count=1, termination_reason="submit_result")
        
        with patch("remora.executor.execute_agent", side_effect=mock_execute):
            with patch("remora.executor.create_workspace", new_callable=AsyncMock):
                with patch("remora.executor.get_execution_batches") as mock_batches:
                    # Both agents in same batch
                    mock_batches.return_value = [[mock_node1, mock_node2]]
                    
                    executor = GraphExecutor(config, mock_event_bus)
                    results = await executor.run([mock_node1, mock_node2], MagicMock())
        
        # Should only call execute once due to stop_graph policy
        assert call_count == 1
```

---

## Common Pitfalls

### Pitfall 1: Forgetting Agent.from_bundle is async

**Problem:** `Agent.from_bundle()` returns an awaitable in structured-agents v0.3.

**Solution:** Always await it:
```python
agent = await Agent.from_bundle(bundle_path, ...)
```

### Pitfall 2: Error handling not respecting error_policy

**Problem:** Exceptions propagate even when `error_policy == CONTINUE`.

**Solution:** Catch exceptions in `_run_node()` and handle based on policy:
```python
except Exception as e:
    if self.config.error_policy == ErrorPolicy.STOP_GRAPH:
        raise
    return None  # Continue to next agent
```

### Pitfall 3: Missing workspace cleanup

**Problem:** Workspaces aren't cleaned up after execution.

**Solution:** Add cleanup in `run()` after all batches complete:
```python
finally:
    for ws in state.workspaces.values():
        await ws.cleanup()
```

### Pitfall 4: EventBus doesn't implement Observer protocol

**Problem:** structured-agents expects an `Observer` with `emit()` method.

**Solution:** Ensure EventBus has the right interface or create an adapter:
```python
class ObserverAdapter:
    def __init__(self, event_bus):
        self.event_bus = event_bus
    
    async def emit(self, event):
        await self.event_bus.emit(event)
```

---

## Verification

Run the following to verify the implementation:

```bash
# Verify imports work
python -c "from remora import GraphExecutor, ExecutorState, ExecutionConfig; print('OK')"

# Run unit tests
python -m pytest tests/unit/test_executor.py -v

# Run integration tests (if available)
python -m pytest tests/integration/test_agent_node_workflow.py -v
```

---

## Files Summary

| File | Action | Description |
|------|--------|-------------|
| `src/remora/executor.py` | CREATE | Main executor module (~200 lines) |
| `src/remora/__init__.py` | MODIFY | Add exports for new classes |
| `tests/unit/test_executor.py` | CREATE | Unit tests for executor |

---

## Next Step

After completing this step, proceed to **Step 8: Checkpoint Manager** for Cairn-native checkpointing.
