# Developer Guide: Refactoring Remora to Use `structured-agents`

## Overview

This guide walks through refactoring Remora to use the `structured-agents` library. The refactor will:

1. **Remove** ~1,400 lines of code that moved to structured-agents
2. **Add** a thin wrapper (`KernelRunner`) that bridges Remora's orchestration to the new library
3. **Migrate** existing subagent YAML files to the new bundle.yaml format

**Remember:** We do NOT care about backwards compatibility. We want the cleanest, most elegant architecture.

---

## Prerequisites

- Completed `structured-agents` library (in `.context/structured-agents/`)
- `structured-agents` published or available as a path dependency
- Familiarity with current Remora codebase

---

## Part 1: Understanding What Changes

### Files to DELETE

| File | Lines | Reason |
|------|-------|--------|
| `src/remora/runner.py` | ~950 | Agent loop moved to structured-agents |
| `src/remora/grammar.py` | ~42 | Grammar building moved to structured-agents |
| `src/remora/tool_parser.py` | ~45 | Tool parsing moved to structured-agents |
| `src/remora/execution.py` | ~424 | Process execution moved to structured-agents |

### Files to MODIFY

| File | Changes |
|------|---------|
| `src/remora/orchestrator.py` | Use new `KernelRunner` |
| `src/remora/config.py` | Remove runner-specific config, add bundle paths |
| `src/remora/events.py` | Simplify - now bridges to structured-agents observer |
| `src/remora/externals.py` | Update to work with path-based context |
| `pyproject.toml` | Add structured-agents dependency |

### Files to CREATE

| File | Purpose |
|------|---------|
| `src/remora/kernel_runner.py` | Wrapper around structured-agents AgentKernel |
| `src/remora/event_bridge.py` | Translates structured-agents events to Remora events |

### Files to KEEP (unchanged or minimal changes)

| File | Purpose |
|------|---------|
| `src/remora/discovery/*` | CST parsing with tree-sitter |
| `src/remora/context/*` | ContextManager, Hub integration |
| `src/remora/cli.py` | CLI entry points |
| `src/remora/results.py` | AgentResult, NodeResult |
| `src/remora/errors.py` | Error codes |

---

## Part 2: Add structured-agents Dependency

### Step 2.1: Update pyproject.toml

Add structured-agents as a dependency. If it's a local path during development:

```toml
[project]
dependencies = [
    # ... existing deps ...
    "structured-agents>=0.1.0",
]

[tool.uv.sources]
# During development, use path dependency
structured-agents = { path = "../structured-agents" }
```

Or if published to a registry:

```toml
[project]
dependencies = [
    "structured-agents>=0.1.0",
]
```

### Step 2.2: Install and Verify

```bash
cd /path/to/remora
uv sync
uv run python -c "import structured_agents; print(structured_agents.__version__)"
```

**Expected:** Version number prints without error.

---

## Part 3: Create the Event Bridge

The event bridge translates structured-agents observer events into Remora's EventEmitter format.

### Step 3.1: Create event_bridge.py

**File: `src/remora/event_bridge.py`**

```python
"""Bridge between structured-agents observer and Remora's EventEmitter."""

from __future__ import annotations

import time
from typing import Any

from structured_agents import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)

from remora.context import ContextManager
from remora.events import EventEmitter, EventName, EventStatus


class RemoraEventBridge:
    """Translates structured-agents events to Remora's EventEmitter format.

    This bridge:
    1. Receives typed events from structured-agents kernel
    2. Converts them to Remora's event dict format
    3. Emits them via Remora's EventEmitter
    4. Updates Remora's ContextManager with tool results
    """

    def __init__(
        self,
        emitter: EventEmitter,
        context_manager: ContextManager,
        agent_id: str,
        node_id: str,
        operation: str,
    ):
        self._emitter = emitter
        self._context_manager = context_manager
        self._agent_id = agent_id
        self._node_id = node_id
        self._operation = operation
        self._start_time = time.monotonic()

    def _base_payload(self, event_name: str) -> dict[str, Any]:
        """Build base event payload with common fields."""
        return {
            "event": event_name,
            "agent_id": self._agent_id,
            "node_id": self._node_id,
            "operation": self._operation,
            "phase": "execution",
            "timestamp_ms": int(time.time() * 1000),
        }

    async def on_kernel_start(self, event: KernelStartEvent) -> None:
        """Handle kernel start event."""
        payload = self._base_payload(EventName.AGENT_START)
        payload["max_turns"] = event.max_turns
        payload["tools_count"] = event.tools_count
        payload["initial_messages_count"] = event.initial_messages_count
        self._emitter.emit(payload)
        self._start_time = time.monotonic()

    async def on_model_request(self, event: ModelRequestEvent) -> None:
        """Handle model request event."""
        payload = self._base_payload(EventName.MODEL_REQUEST)
        payload["turn"] = event.turn
        payload["messages_count"] = event.messages_count
        payload["tools_count"] = event.tools_count
        payload["model"] = event.model
        self._emitter.emit(payload)

    async def on_model_response(self, event: ModelResponseEvent) -> None:
        """Handle model response event."""
        payload = self._base_payload(EventName.MODEL_RESPONSE)
        payload["turn"] = event.turn
        payload["duration_ms"] = event.duration_ms
        payload["tool_calls_count"] = event.tool_calls_count
        payload["status"] = EventStatus.OK

        if event.content:
            payload["response_preview"] = event.content[:500]

        if event.usage:
            payload["usage"] = {
                "prompt_tokens": event.usage.prompt_tokens,
                "completion_tokens": event.usage.completion_tokens,
                "total_tokens": event.usage.total_tokens,
            }

        self._emitter.emit(payload)

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        """Handle tool call event (before execution)."""
        payload = self._base_payload(EventName.TOOL_CALL)
        payload["turn"] = event.turn
        payload["tool_name"] = event.tool_name
        payload["call_id"] = event.call_id
        payload["arguments"] = event.arguments
        self._emitter.emit(payload)

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        """Handle tool result event."""
        payload = self._base_payload(EventName.TOOL_RESULT)
        payload["turn"] = event.turn
        payload["tool_name"] = event.tool_name
        payload["call_id"] = event.call_id
        payload["duration_ms"] = event.duration_ms
        payload["status"] = EventStatus.ERROR if event.is_error else EventStatus.OK
        payload["output_preview"] = event.output_preview
        self._emitter.emit(payload)

        # Update ContextManager with tool result
        self._context_manager.apply_event({
            "type": "tool_result",
            "tool_name": event.tool_name,
            "data": {
                "output_preview": event.output_preview,
                "is_error": event.is_error,
            },
        })

    async def on_turn_complete(self, event: TurnCompleteEvent) -> None:
        """Handle turn complete event."""
        # Increment turn in context manager
        self._context_manager.apply_event({"type": "turn_start"})

        payload = self._base_payload(EventName.TURN_COMPLETE)
        payload["turn"] = event.turn
        payload["tool_calls_count"] = event.tool_calls_count
        payload["tool_results_count"] = event.tool_results_count
        payload["errors_count"] = event.errors_count
        self._emitter.emit(payload)

    async def on_kernel_end(self, event: KernelEndEvent) -> None:
        """Handle kernel end event."""
        payload = self._base_payload(EventName.AGENT_COMPLETE)
        payload["turn_count"] = event.turn_count
        payload["termination_reason"] = event.termination_reason
        payload["total_duration_ms"] = event.total_duration_ms
        self._emitter.emit(payload)

    async def on_error(self, error: Exception, context: str | None = None) -> None:
        """Handle error event."""
        payload = self._base_payload(EventName.AGENT_ERROR)
        payload["error_type"] = type(error).__name__
        payload["error_message"] = str(error)
        payload["context"] = context
        payload["status"] = EventStatus.ERROR
        self._emitter.emit(payload)
```

### Testing Step 3

Create **`tests/test_event_bridge.py`**:

```python
"""Tests for the event bridge."""

import pytest
from unittest.mock import MagicMock

from structured_agents import (
    ModelRequestEvent,
    ToolResultEvent,
)

from remora.event_bridge import RemoraEventBridge
from remora.events import EventName


class TestRemoraEventBridge:
    @pytest.fixture
    def emitter(self):
        return MagicMock()

    @pytest.fixture
    def context_manager(self):
        cm = MagicMock()
        cm.apply_event = MagicMock()
        return cm

    @pytest.fixture
    def bridge(self, emitter, context_manager):
        return RemoraEventBridge(
            emitter=emitter,
            context_manager=context_manager,
            agent_id="test-agent",
            node_id="test-node",
            operation="docstring",
        )

    @pytest.mark.asyncio
    async def test_model_request_event(self, bridge, emitter):
        event = ModelRequestEvent(
            turn=1,
            messages_count=3,
            tools_count=5,
            model="test-model",
        )

        await bridge.on_model_request(event)

        emitter.emit.assert_called_once()
        payload = emitter.emit.call_args[0][0]
        assert payload["event"] == EventName.MODEL_REQUEST
        assert payload["turn"] == 1
        assert payload["agent_id"] == "test-agent"

    @pytest.mark.asyncio
    async def test_tool_result_updates_context_manager(self, bridge, context_manager):
        event = ToolResultEvent(
            turn=2,
            tool_name="write_docstring",
            call_id="call_123",
            is_error=False,
            duration_ms=150,
            output_preview="Success",
        )

        await bridge.on_tool_result(event)

        # Verify context manager was updated
        context_manager.apply_event.assert_called_once()
        call_args = context_manager.apply_event.call_args[0][0]
        assert call_args["type"] == "tool_result"
        assert call_args["tool_name"] == "write_docstring"
```

Run test:

```bash
uv run pytest tests/test_event_bridge.py -v
```

---

## Part 4: Create the Kernel Runner

The KernelRunner wraps structured-agents and handles Remora-specific concerns.

### Step 4.1: Create kernel_runner.py

**File: `src/remora/kernel_runner.py`**

```python
"""KernelRunner - Remora's wrapper around structured-agents AgentKernel."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from structured_agents import (
    AgentKernel,
    GrailBackend,
    GrailBackendConfig,
    KernelConfig,
    ToolResult,
    load_bundle,
)

from remora.config import RemoraConfig
from remora.context import ContextManager
from remora.context.summarizers import get_default_summarizers
from remora.discovery import CSTNode
from remora.event_bridge import RemoraEventBridge
from remora.events import EventEmitter
from remora.externals import create_remora_externals
from remora.results import AgentResult, AgentStatus

if TYPE_CHECKING:
    from remora.orchestrator import RemoraAgentContext

logger = logging.getLogger(__name__)


class KernelRunner:
    """Remora's wrapper around structured-agents AgentKernel.

    This class:
    1. Loads bundles and configures the kernel
    2. Creates Remora-specific Grail externals
    3. Bridges events to Remora's EventEmitter
    4. Manages ContextManager state
    5. Formats results into Remora's AgentResult
    """

    def __init__(
        self,
        node: CSTNode,
        ctx: RemoraAgentContext,
        config: RemoraConfig,
        bundle_path: Path,
        event_emitter: EventEmitter,
        workspace_path: Path | None = None,
        stable_path: Path | None = None,
    ):
        self.node = node
        self.ctx = ctx
        self.config = config
        self.bundle_path = bundle_path
        self.event_emitter = event_emitter
        self.workspace_path = workspace_path
        self.stable_path = stable_path

        # Load bundle
        self.bundle = load_bundle(bundle_path)

        # Initialize context manager
        self.context_manager = ContextManager(
            initial_context={
                "agent_id": ctx.agent_id,
                "goal": f"{self.bundle.name} on {node.name}",
                "operation": self.bundle.name,
                "node_id": node.node_id,
                "node_summary": self._summarize_node(),
            },
            summarizers=get_default_summarizers(),
        )

        # Create event bridge
        self._observer = RemoraEventBridge(
            emitter=event_emitter,
            context_manager=self.context_manager,
            agent_id=ctx.agent_id,
            node_id=node.node_id,
            operation=self.bundle.name,
        )

        # Store backend for cleanup
        self._backend: GrailBackend | None = None

        # Build kernel
        self._kernel = self._build_kernel()

    def _summarize_node(self) -> str:
        """Create a short summary of the target node."""
        lines = self.node.text.split("\n")
        if len(lines) > 5:
            return "\n".join(lines[:3]) + f"\n... ({len(lines)} lines total)"
        return self.node.text

    def _build_kernel(self) -> AgentKernel:
        """Build the structured-agents kernel with Remora configuration."""
        # Kernel config from Remora server config
        kernel_config = KernelConfig(
            base_url=self.config.server.base_url,
            model=self.bundle.manifest.model.adapter or self.config.server.default_adapter,
            api_key=self.config.server.api_key,
            timeout=float(self.config.server.timeout),
            max_tokens=self.config.runner.max_tokens,
            temperature=self.config.runner.temperature,
            tool_choice=self.config.runner.tool_choice,
        )

        # Grail backend config from Remora cairn config
        backend_config = GrailBackendConfig(
            grail_dir=self.config.cairn.home or Path.cwd(),
            max_workers=self.config.cairn.pool_workers,
            timeout=float(self.config.cairn.timeout),
            limits={
                **(self._get_limits_for_preset(self.config.cairn.limits_preset)),
                **self.config.cairn.limits_override,
            },
        )

        # Create backend with externals factory
        self._backend = GrailBackend(
            config=backend_config,
            externals_factory=self._create_externals,
        )

        # Build ToolSource from bundle + backend
        tool_source = self.bundle.build_tool_source(self._backend)

        # Get grammar config from bundle
        grammar_config = self.bundle.get_grammar_config()

        # Get plugin from bundle
        plugin = self.bundle.get_plugin()

        return AgentKernel(
            config=kernel_config,
            plugin=plugin,
            tool_source=tool_source,
            observer=self._observer,
            grammar_config=grammar_config,
            max_history_messages=self.config.runner.max_history_messages,
        )

    def _get_limits_for_preset(self, preset: str) -> dict[str, Any]:
        """Get Grail limits for a preset name."""
        presets = {
            "strict": {
                "max_memory_mb": 256,
                "max_duration_s": 30,
                "max_recursion": 50,
            },
            "default": {
                "max_memory_mb": 512,
                "max_duration_s": 60,
                "max_recursion": 100,
            },
            "permissive": {
                "max_memory_mb": 1024,
                "max_duration_s": 120,
                "max_recursion": 200,
            },
        }
        return presets.get(preset, presets["default"])

    def _create_externals(
        self,
        agent_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Create Remora-specific Grail external functions.

        The context dict from GrailBackend contains:
        - workspace_path: str | None
        - stable_path: str | None
        - node_source: str | None
        - node_metadata: dict | None
        """
        return create_remora_externals(
            agent_id=agent_id,
            node_source=context.get("node_source") or self.node.text,
            node_metadata=context.get("node_metadata") or {
                "name": self.node.name,
                "type": str(self.node.node_type),
                "file_path": str(self.node.file_path),
                "node_id": self.node.node_id,
                "start_line": self.node.start_line,
                "end_line": self.node.end_line,
            },
            workspace_path=context.get("workspace_path") or (
                str(self.workspace_path) if self.workspace_path else None
            ),
            stable_path=context.get("stable_path") or (
                str(self.stable_path) if self.stable_path else None
            ),
        )

    async def _provide_context(self) -> dict[str, Any]:
        """Provide per-turn context to the kernel.

        This is called at the start of each turn to inject
        fresh context into tool execution.
        """
        # Pull any updates from Hub
        await self.context_manager.pull_hub_context()

        return {
            # Standard context for all tools
            "node_text": self.node.text,
            "target_file": str(self.node.file_path),
            "workspace_id": self.ctx.agent_id,
            "agent_id": self.ctx.agent_id,

            # Workspace paths for Grail
            "workspace_path": str(self.workspace_path) if self.workspace_path else None,
            "stable_path": str(self.stable_path) if self.stable_path else None,

            # Node metadata
            "node_source": self.node.text,
            "node_metadata": {
                "name": self.node.name,
                "type": str(self.node.node_type),
                "file_path": str(self.node.file_path),
                "node_id": self.node.node_id,
            },

            # Prompt context from ContextManager
            **self.context_manager.get_prompt_context(),
        }

    async def run(self) -> AgentResult:
        """Execute the agent loop via structured-agents.

        Returns:
            AgentResult with status, summary, and any changed files.
        """
        # Build initial messages from bundle template
        initial_messages = self.bundle.build_initial_messages({
            "node_text": self.node.text,
            "node_name": self.node.name,
            "node_type": str(self.node.node_type),
            "file_path": str(self.node.file_path),
        })

        # Define termination condition
        def is_termination_tool(result: ToolResult) -> bool:
            return result.name == self.bundle.termination_tool

        try:
            # Run the kernel
            result = await self._kernel.run(
                initial_messages=initial_messages,
                tools=self.bundle.tool_schemas,
                max_turns=self.bundle.max_turns,
                termination=is_termination_tool,
                context_provider=self._provide_context,
            )

            return self._format_result(result)

        except Exception as e:
            logger.exception(f"KernelRunner failed for {self.node.node_id}")
            return AgentResult(
                status=AgentStatus.ERRORED,
                workspace_id=self.ctx.agent_id,
                changed_files=[],
                summary="",
                details={},
                error=str(e),
            )

        finally:
            await self._kernel.close()
            if self._backend:
                self._backend.shutdown()

    def _format_result(self, result) -> AgentResult:
        """Convert structured-agents RunResult to Remora's AgentResult."""
        # Extract data from termination tool result
        if result.termination_reason == "termination_tool" and result.final_tool_result:
            output = result.final_tool_result.output

            # Parse output if it's JSON string
            if isinstance(output, str):
                try:
                    output = json.loads(output)
                except json.JSONDecodeError:
                    output = {"summary": output}

            if isinstance(output, dict):
                status_str = output.get("status", "success")
                status = self._parse_status(status_str)

                return AgentResult(
                    status=status,
                    workspace_id=self.ctx.agent_id,
                    changed_files=output.get("changed_files", []),
                    summary=output.get("summary", ""),
                    details=output.get("details", {}),
                    error=output.get("error"),
                )

        # Handle other termination reasons
        if result.termination_reason == "no_tool_calls":
            # Model decided it's done without calling submit
            return AgentResult(
                status=AgentStatus.SUCCESS,
                workspace_id=self.ctx.agent_id,
                changed_files=[],
                summary=result.final_message.content or "Completed without tool calls",
                details={"termination_reason": "no_tool_calls"},
                error=None,
            )

        if result.termination_reason == "max_turns":
            return AgentResult(
                status=AgentStatus.ERRORED,
                workspace_id=self.ctx.agent_id,
                changed_files=[],
                summary="",
                details={"termination_reason": "max_turns", "turns": result.turn_count},
                error=f"Reached maximum turns ({result.turn_count})",
            )

        # Fallback
        return AgentResult(
            status=AgentStatus.SUCCESS,
            workspace_id=self.ctx.agent_id,
            changed_files=[],
            summary=result.final_message.content or "",
            details={"termination_reason": result.termination_reason},
            error=None,
        )

    def _parse_status(self, status_str: str) -> AgentStatus:
        """Parse status string to AgentStatus enum."""
        status_map = {
            "success": AgentStatus.SUCCESS,
            "skipped": AgentStatus.SKIPPED,
            "failed": AgentStatus.ERRORED,
            "error": AgentStatus.ERRORED,
            "errored": AgentStatus.ERRORED,
        }
        return status_map.get(status_str.lower(), AgentStatus.SUCCESS)
```

### Step 4.2: Update externals.py

The externals.py needs to be updated to work with path strings instead of Workspace objects:

**File: `src/remora/externals.py`** (updated)

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from cairn.runtime.external_functions import create_external_functions
from fsdantic import Workspace


def create_remora_externals(
    agent_id: str,
    node_source: str,
    node_metadata: dict[str, Any],
    workspace_path: str | None = None,
    stable_path: str | None = None,
) -> dict[str, Callable]:
    """Create external functions available to Remora's .pym tools.

    Extends Cairn's base externals with Remora-specific functions
    like node context access.

    Args:
        agent_id: Unique agent identifier.
        node_source: Source code of the node being analyzed.
        node_metadata: Metadata dict for the node (name, type, etc).
        workspace_path: Path to the agent's private workspace.
        stable_path: Path to the read-only backing filesystem.

    Returns:
        Dictionary of functions to inject into the Grail script.
    """
    # Create workspace objects from paths if provided
    agent_fs = Workspace(Path(workspace_path)) if workspace_path else None
    stable_fs = Workspace(Path(stable_path)) if stable_path else None

    base_externals = create_external_functions(agent_id, agent_fs, stable_fs)

    async def get_node_source() -> str:
        """Return the source code of the current node being analyzed."""
        return node_source

    async def get_node_metadata() -> dict[str, str]:
        """Return metadata about the current node."""
        return node_metadata

    # Remora-specific overrides or additions
    base_externals["get_node_source"] = get_node_source
    base_externals["get_node_metadata"] = get_node_metadata

    return base_externals
```

### Testing Step 4

Create **`tests/test_kernel_runner.py`**:

```python
"""Tests for KernelRunner."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from remora.kernel_runner import KernelRunner
from remora.results import AgentStatus


class TestKernelRunner:
    @pytest.fixture
    def mock_node(self):
        node = MagicMock()
        node.node_id = "test-node-id"
        node.name = "test_function"
        node.node_type = "function"
        node.file_path = Path("/test/file.py")
        node.text = "def test_function():\n    pass"
        node.start_line = 1
        node.end_line = 2
        return node

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock()
        ctx.agent_id = "test-agent-id"
        return ctx

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.server.base_url = "http://localhost:8000/v1"
        config.server.api_key = "EMPTY"
        config.server.timeout = 120
        config.server.default_adapter = "test-model"
        config.runner.max_tokens = 4096
        config.runner.temperature = 0.1
        config.runner.tool_choice = "auto"
        config.runner.max_history_messages = 50
        config.cairn.home = None
        config.cairn.pool_workers = 4
        config.cairn.timeout = 300
        config.cairn.limits_preset = "default"
        config.cairn.limits_override = {}
        return config

    @pytest.fixture
    def mock_emitter(self):
        return MagicMock()

    def test_summarize_node_short(self, mock_node, mock_ctx, mock_config, mock_emitter, tmp_path):
        bundle_dir = tmp_path / "test_bundle"
        bundle_dir.mkdir()
        (bundle_dir / "tools").mkdir()
        (bundle_dir / "bundle.yaml").write_text("""
name: test_agent
version: "1.0"

model:
  plugin: function_gemma

initial_context:
  system_prompt: Test
  user_template: "{{ node_text }}"

max_turns: 5
termination_tool: submit_result

tools:
  - name: submit_result
    registry: grail
    description: Submit result

registries:
  - type: grail
    config:
      agents_dir: tools
""")

        with patch("remora.kernel_runner.load_bundle") as mock_load:
            mock_bundle = MagicMock()
            mock_bundle.name = "test_agent"
            mock_bundle.manifest.model.adapter = None
            mock_bundle.max_turns = 5
            mock_bundle.termination_tool = "submit_result"
            mock_bundle.tool_schemas = []
            mock_bundle.get_plugin.return_value = MagicMock()
            mock_bundle.get_grammar_config.return_value = MagicMock()
            mock_bundle.build_tool_source.return_value = MagicMock()
            mock_load.return_value = mock_bundle

            with patch("remora.kernel_runner.GrailBackend"):
                with patch("remora.kernel_runner.AgentKernel"):
                    runner = KernelRunner(
                        node=mock_node,
                        ctx=mock_ctx,
                        config=mock_config,
                        bundle_path=bundle_dir,
                        event_emitter=mock_emitter,
                    )

                    summary = runner._summarize_node()
                    assert "def test_function" in summary

    def test_parse_status(self, mock_node, mock_ctx, mock_config, mock_emitter, tmp_path):
        bundle_dir = tmp_path / "test_bundle"
        bundle_dir.mkdir()
        (bundle_dir / "tools").mkdir()
        (bundle_dir / "bundle.yaml").write_text("""
name: test_agent
version: "1.0"
model:
  plugin: function_gemma
initial_context:
  system_prompt: Test
  user_template: "{{ node_text }}"
max_turns: 5
termination_tool: submit_result
tools:
  - name: submit_result
    registry: grail
    description: Submit result
registries:
  - type: grail
    config:
      agents_dir: tools
""")

        with patch("remora.kernel_runner.load_bundle") as mock_load:
            mock_bundle = MagicMock()
            mock_bundle.name = "test_agent"
            mock_bundle.manifest.model.adapter = None
            mock_bundle.max_turns = 5
            mock_bundle.termination_tool = "submit_result"
            mock_bundle.tool_schemas = []
            mock_bundle.get_plugin.return_value = MagicMock()
            mock_bundle.get_grammar_config.return_value = MagicMock()
            mock_bundle.build_tool_source.return_value = MagicMock()
            mock_load.return_value = mock_bundle

            with patch("remora.kernel_runner.GrailBackend"):
                with patch("remora.kernel_runner.AgentKernel"):
                    runner = KernelRunner(
                        node=mock_node,
                        ctx=mock_ctx,
                        config=mock_config,
                        bundle_path=bundle_dir,
                        event_emitter=mock_emitter,
                    )

                    assert runner._parse_status("success") == AgentStatus.SUCCESS
                    assert runner._parse_status("skipped") == AgentStatus.SKIPPED
                    assert runner._parse_status("failed") == AgentStatus.ERRORED
                    assert runner._parse_status("ERROR") == AgentStatus.ERRORED
```

Run test:

```bash
uv run pytest tests/test_kernel_runner.py -v
```

---

## Part 5: Update the Orchestrator

### Step 5.1: Modify orchestrator.py

The orchestrator needs to use `KernelRunner` instead of `FunctionGemmaRunner`.

**Changes to `src/remora/orchestrator.py`:**

```python
# REMOVE these imports:
# from remora.runner import FunctionGemmaRunner, AgentError
# from remora.execution import ProcessIsolatedExecutor, SnapshotManager

# ADD this import:
from remora.kernel_runner import KernelRunner

# In the Coordinator class:

class Coordinator:
    """Orchestrates agent execution across nodes."""

    def __init__(
        self,
        config: RemoraConfig,
        event_emitter: EventEmitter | None = None,
        llm_logger: LlmConversationLogger | None = None,
    ):
        self.config = config
        self._event_emitter = event_emitter or NullEventEmitter()
        self._llm_logger = llm_logger
        self._semaphore = asyncio.Semaphore(config.cairn.max_concurrent_agents)

        # REMOVE: self._executor = ProcessIsolatedExecutor(...)
        # REMOVE: self._snapshot_manager = SnapshotManager(...)

        # Workspace management stays
        self._workspace_cache = WorkspaceCache(config.cairn.home or Path.cwd())

    async def process_node(
        self,
        node: CSTNode,
        operations: list[str],
    ) -> NodeResult:
        """Process a single node with the specified operations."""
        runners: dict[str, tuple[RemoraAgentContext, KernelRunner]] = {}

        for operation in operations:
            op_config = self.config.operations.get(operation)
            if not op_config or not op_config.enabled:
                continue

            # Create agent context
            agent_id = f"{operation}-{node.node_id[:8]}-{uuid.uuid4().hex[:4]}"
            ctx = RemoraAgentContext(
                agent_id=agent_id,
                task=f"{operation} on {node.name}",
                operation=operation,
                node_id=node.node_id,
                state=RemoraAgentState.QUEUED,
            )

            # Get bundle path - now points to directory containing bundle.yaml
            bundle_path = self.config.agents_dir / op_config.subagent

            # Get workspace paths
            workspace_path = self._workspace_cache.get_workspace_path(agent_id)

            # Create KernelRunner instead of FunctionGemmaRunner
            runner = KernelRunner(
                node=node,
                ctx=ctx,
                config=self.config,
                bundle_path=bundle_path,
                event_emitter=self._event_emitter,
                workspace_path=workspace_path,
                stable_path=None,  # Could be a read-only snapshot
            )

            runners[operation] = (ctx, runner)

        # Execute all runners concurrently
        async def run_with_semaphore(
            operation: str,
            ctx: RemoraAgentContext,
            runner: KernelRunner,
        ) -> tuple[str, AgentResult]:
            async with self._semaphore:
                ctx.state = RemoraAgentState.EXECUTING
                try:
                    result = await runner.run()
                    ctx.state = RemoraAgentState.COMPLETED
                    return operation, result
                except Exception as e:
                    ctx.state = RemoraAgentState.ERRORED
                    logger.exception(f"Runner failed for {operation}")
                    return operation, AgentResult(
                        status=AgentStatus.ERRORED,
                        workspace_id=ctx.agent_id,
                        changed_files=[],
                        summary="",
                        details={},
                        error=str(e),
                    )

        tasks = [
            run_with_semaphore(op, ctx, runner)
            for op, (ctx, runner) in runners.items()
        ]

        results = await asyncio.gather(*tasks)

        return NodeResult(
            node_id=node.node_id,
            node_name=node.name,
            node_type=str(node.node_type),
            file_path=str(node.file_path),
            operation_results={op: result for op, result in results},
        )
```

---

## Part 6: Delete Obsolete Code

### Step 6.1: Remove Old Files

```bash
# Delete files that have moved to structured-agents
rm src/remora/runner.py
rm src/remora/grammar.py
rm src/remora/tool_parser.py
rm src/remora/execution.py

# Remove any related test files
rm -f tests/test_runner.py
rm -f tests/test_grammar.py
rm -f tests/test_tool_parser.py
rm -f tests/test_execution.py
```

### Step 6.2: Clean Up Imports

Search for and remove imports of deleted modules:

```bash
# Find files that import deleted modules
grep -r "from remora.runner import" src/
grep -r "from remora.grammar import" src/
grep -r "from remora.execution import" src/
grep -r "from remora.tool_parser import" src/
```

Update each file to remove these imports.

### Step 6.3: Update __init__.py

**File: `src/remora/__init__.py`**

Remove exports for deleted modules:

```python
# REMOVE:
# from remora.runner import FunctionGemmaRunner, AgentError
# from remora.grammar import build_functiongemma_grammar
# from remora.execution import ProcessIsolatedExecutor

# ADD:
from remora.kernel_runner import KernelRunner
```

---

## Part 7: Migrate Bundles

### Step 7.1: Understanding the Bundle Format

Bundles use a **registry-based** tool resolution system. Tools are NOT referenced by script path directly. Instead:

1. The bundle specifies which **registries** to use (e.g., `grail`)
2. Each tool references a **name** and **registry**
3. The `GrailRegistry` scans the configured directory for `.pym` files
4. Tool schemas are loaded from `.grail/{tool_name}/inputs.json` if present

### Step 7.2: Bundle Directory Structure

```
agents/docstring/
├── bundle.yaml              # Bundle manifest
├── tools/                   # Tool .pym files (scanned by GrailRegistry)
│   ├── read_current_docstring.pym
│   ├── read_type_hints.pym
│   ├── write_docstring.pym
│   └── submit.pym
│   └── .grail/              # Optional: pre-computed tool schemas
│       ├── read_current_docstring/
│       │   └── inputs.json
│       └── write_docstring/
│           └── inputs.json
└── context/                 # Context provider scripts
    └── docstring_style.pym
```

### Step 7.3: Convert Subagent YAML to Bundle Format

**Before (`agents/docstring/docstring_subagent.yaml`):**

```yaml
name: docstring_agent
max_turns: 15

initial_context:
  system_prompt: |
    You are a model that can do function calling...
  node_context: |
    Code to document:
    {{ node_text }}

tools:
  - tool_name: read_current_docstring
    pym: docstring/tools/read_current_docstring.pym
    tool_description: Read the existing docstring...

  - tool_name: write_docstring
    pym: docstring/tools/write_docstring.pym
    tool_description: Write or replace a docstring.
    inputs_override:
      docstring:
        description: "The docstring text to write."
    context_providers:
      - docstring/context/docstring_style.pym

  - tool_name: submit_result
    pym: docstring/tools/submit.pym
    tool_description: Submit the final result.
```

**After (`agents/docstring/bundle.yaml`):**

```yaml
name: docstring_agent
version: "1.0"

model:
  plugin: function_gemma
  adapter: google/functiongemma-270m-it
  grammar:
    mode: ebnf
    allow_parallel_calls: true
    args_format: permissive

initial_context:
  system_prompt: |
    You are a model that can do function calling with the following functions.
    <task_description>You are a Python documentation tool. Read the existing
    docstring and type hints, then write an appropriate docstring.</task_description>

    Respond with a single tool call each turn.
  user_template: |
    Code to document:
    {{ node_text }}

max_turns: 15
termination_tool: submit_result

tools:
  - name: read_current_docstring
    registry: grail
    description: Read the existing docstring from the current Python function or class.

  - name: read_type_hints
    registry: grail
    description: Extract parameter type annotations and return type.

  - name: write_docstring
    registry: grail
    description: Write or replace a docstring on the current function.
    inputs_override:
      docstring:
        type: string
        description: The docstring text to write.
      style:
        type: string
        description: The docstring style (google, numpy, sphinx).
    context_providers:
      - context/docstring_style.pym

  - name: submit_result
    registry: grail
    description: Submit the final result after docstring work is complete.
    inputs_override:
      summary:
        type: string
        description: A short summary of what was done.
      action:
        type: string
        description: The action taken (added, updated, skipped).
      changed_files:
        type: array
        description: List of file paths that were modified.

registries:
  - type: grail
    config:
      agents_dir: tools
```

### Step 7.4: Migration Script

Create a script to automate the conversion:

**File: `scripts/migrate_bundles.py`**

```python
#!/usr/bin/env python3
"""Migrate old subagent YAML files to new bundle.yaml format."""

import sys
from pathlib import Path
import yaml


def migrate_subagent(old_path: Path) -> dict:
    """Convert old subagent YAML to new bundle format."""
    with open(old_path) as f:
        old = yaml.safe_load(f)

    # Build new format
    new = {
        "name": old.get("name", old_path.parent.name + "_agent"),
        "version": "1.0",
        "model": {
            "plugin": "function_gemma",
            "adapter": old.get("model_id", "google/functiongemma-270m-it"),
            "grammar": {
                "mode": "ebnf",
                "allow_parallel_calls": True,
                "args_format": "permissive",
            },
        },
        "initial_context": {
            "system_prompt": old.get("initial_context", {}).get("system_prompt", ""),
            "user_template": old.get("initial_context", {}).get("node_context", "{{ node_text }}"),
        },
        "max_turns": old.get("max_turns", 20),
        "termination_tool": "submit_result",
        "tools": [],
        "registries": [
            {
                "type": "grail",
                "config": {
                    "agents_dir": "tools",
                },
            },
        ],
    }

    # Convert tools
    for tool in old.get("tools", []):
        new_tool = {
            "name": tool.get("tool_name"),
            "registry": "grail",
            "description": tool.get("tool_description", ""),
        }

        # Convert inputs_override
        if "inputs_override" in tool:
            new_tool["inputs_override"] = {}
            for name, override in tool["inputs_override"].items():
                new_tool["inputs_override"][name] = {
                    "type": override.get("type", "string"),
                    "description": override.get("description", ""),
                }

        # Convert context_providers (strip parent directory prefix)
        if "context_providers" in tool:
            new_tool["context_providers"] = [
                cp.replace(old_path.parent.name + "/", "")
                for cp in tool["context_providers"]
            ]

        new["tools"].append(new_tool)

    return new


def main():
    agents_dir = Path("agents")

    for subagent_file in agents_dir.glob("*/*_subagent.yaml"):
        print(f"Migrating: {subagent_file}")

        new_data = migrate_subagent(subagent_file)
        new_path = subagent_file.parent / "bundle.yaml"

        with open(new_path, "w") as f:
            yaml.dump(new_data, f, default_flow_style=False, sort_keys=False)

        print(f"  -> Created: {new_path}")

        # Optionally rename old file
        backup_path = subagent_file.with_suffix(".yaml.old")
        subagent_file.rename(backup_path)
        print(f"  -> Backed up: {backup_path}")


if __name__ == "__main__":
    main()
```

### Step 7.5: Reorganize Tool Files

After migration, move .pym files to match the expected structure:

```bash
# For each agent directory
cd agents/docstring

# Create tools directory if needed
mkdir -p tools

# Move tool .pym files (adjust paths as needed)
mv docstring/tools/*.pym tools/

# Move context providers
mkdir -p context
mv docstring/context/*.pym context/
```

### Step 7.6: Update Config References

Update `remora.yaml` to point to bundle directories:

```yaml
operations:
  lint:
    enabled: true
    subagent: lint  # Directory name containing bundle.yaml
  docstring:
    enabled: true
    subagent: docstring
  test:
    enabled: true
    subagent: test
```

---

## Part 8: Update Events Module

Simplify `events.py` since the heavy lifting is now in structured-agents:

**File: `src/remora/events.py`**

```python
"""Event system for Remora.

This module defines:
1. Event names and statuses
2. EventEmitter protocol for output
3. Concrete emitters (JSONL, Null, Composite)

The actual event translation from structured-agents happens in event_bridge.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Protocol, TextIO


class EventName:
    """Standard event names."""
    # Agent lifecycle
    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    AGENT_ERROR = "agent_error"

    # Model interaction
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"

    # Tool execution
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Turn tracking
    TURN_COMPLETE = "turn_complete"

    # Discovery
    DISCOVERY = "discovery"

    # Workspace
    WORKSPACE_ACCEPTED = "workspace_accepted"
    WORKSPACE_REJECTED = "workspace_rejected"


class EventStatus:
    """Standard status values."""
    OK = "ok"
    ERROR = "error"
    PENDING = "pending"


class EventEmitter(Protocol):
    """Protocol for event output."""

    def emit(self, payload: dict[str, Any]) -> None:
        """Emit an event."""
        ...

    def close(self) -> None:
        """Clean up resources."""
        ...


class NullEventEmitter:
    """Event emitter that discards all events."""

    def emit(self, payload: dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass


class JsonlEventEmitter:
    """Event emitter that writes JSONL to a file or stream."""

    def __init__(
        self,
        output: Path | TextIO | None = None,
        include_payloads: bool = True,
        max_payload_chars: int = 40000,
    ):
        self._include_payloads = include_payloads
        self._max_chars = max_payload_chars

        if output is None:
            self._file = sys.stdout
            self._should_close = False
        elif isinstance(output, Path):
            self._file = open(output, "a")
            self._should_close = True
        else:
            self._file = output
            self._should_close = False

    def emit(self, payload: dict[str, Any]) -> None:
        """Write event as JSONL."""
        if not self._include_payloads:
            # Strip large fields
            payload = {k: v for k, v in payload.items() if k != "response_preview"}

        line = json.dumps(payload, default=str)
        if len(line) > self._max_chars:
            line = line[:self._max_chars] + "..."

        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._should_close:
            self._file.close()


class CompositeEventEmitter:
    """Fan-out to multiple emitters."""

    def __init__(self, emitters: list[EventEmitter]):
        self._emitters = emitters

    def emit(self, payload: dict[str, Any]) -> None:
        for emitter in self._emitters:
            try:
                emitter.emit(payload)
            except Exception:
                pass  # Don't let one emitter failure stop others

    def close(self) -> None:
        for emitter in self._emitters:
            try:
                emitter.close()
            except Exception:
                pass
```

---

## Part 9: Clean Up Config

### Step 9.1: Simplify RunnerConfig

Since most runner logic is now in structured-agents, simplify config:

**In `src/remora/config.py`:**

```python
class RunnerConfig(BaseModel):
    """Configuration for the agent runner."""
    # These are passed to structured-agents KernelConfig
    max_tokens: int = 4096
    temperature: float = 0.1
    tool_choice: str = "auto"
    max_history_messages: int = 50

    # REMOVE: use_grammar_enforcement (now handled by bundle grammar config)
    # REMOVE: include_prompt_context (now handled by bundle templates)
    # REMOVE: include_tool_guide (now handled by bundle system prompt)
```

---

## Part 10: Verification

### Step 10.1: Run All Tests

```bash
# Run the full test suite
uv run pytest -v

# Check for import errors
uv run python -c "from remora.kernel_runner import KernelRunner; print('OK')"
uv run python -c "from remora.event_bridge import RemoraEventBridge; print('OK')"
```

### Step 10.2: Integration Test

Create an end-to-end test:

**File: `tests/test_e2e_refactor.py`**

```python
"""End-to-end tests for the refactored system."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from remora.kernel_runner import KernelRunner
from remora.results import AgentStatus


class TestE2ERefactor:
    @pytest.fixture
    def sample_bundle(self, tmp_path):
        """Create a sample bundle for testing."""
        bundle_dir = tmp_path / "test_bundle"
        bundle_dir.mkdir()
        (bundle_dir / "tools").mkdir()

        (bundle_dir / "bundle.yaml").write_text("""
name: test_agent
version: "1.0"

model:
  plugin: function_gemma
  grammar:
    mode: ebnf
    allow_parallel_calls: true
    args_format: permissive

initial_context:
  system_prompt: You are a test agent.
  user_template: "Process: {{ node_text }}"

max_turns: 5
termination_tool: submit_result

tools:
  - name: analyze
    registry: grail
    description: Analyze code

  - name: submit_result
    registry: grail
    description: Submit result
    inputs_override:
      summary:
        type: string
        description: Summary

registries:
  - type: grail
    config:
      agents_dir: tools
""")

        return bundle_dir

    @pytest.mark.asyncio
    async def test_kernel_runner_executes(self, sample_bundle):
        """Verify KernelRunner can execute a simple workflow."""
        mock_node = MagicMock()
        mock_node.node_id = "test-node"
        mock_node.name = "test_func"
        mock_node.node_type = "function"
        mock_node.file_path = Path("/test.py")
        mock_node.text = "def test(): pass"
        mock_node.start_line = 1
        mock_node.end_line = 1

        mock_ctx = MagicMock()
        mock_ctx.agent_id = "test-agent"

        mock_config = MagicMock()
        mock_config.server.base_url = "http://localhost:8000/v1"
        mock_config.server.api_key = "EMPTY"
        mock_config.server.timeout = 60
        mock_config.server.default_adapter = "test"
        mock_config.runner.max_tokens = 2048
        mock_config.runner.temperature = 0.1
        mock_config.runner.tool_choice = "auto"
        mock_config.runner.max_history_messages = 50
        mock_config.cairn.home = None
        mock_config.cairn.pool_workers = 2
        mock_config.cairn.timeout = 60
        mock_config.cairn.limits_preset = "default"
        mock_config.cairn.limits_override = {}

        mock_emitter = MagicMock()

        with patch("remora.kernel_runner.GrailBackend"):
            with patch("remora.kernel_runner.AgentKernel") as MockKernel:
                mock_kernel = AsyncMock()
                mock_result = MagicMock()
                mock_result.termination_reason = "termination_tool"
                mock_result.final_tool_result = MagicMock()
                mock_result.final_tool_result.name = "submit_result"
                mock_result.final_tool_result.output = '{"status": "success", "summary": "Done"}'
                mock_kernel.run.return_value = mock_result
                mock_kernel.close = AsyncMock()
                MockKernel.return_value = mock_kernel

                with patch("remora.kernel_runner.load_bundle") as mock_load:
                    mock_bundle = MagicMock()
                    mock_bundle.name = "test_agent"
                    mock_bundle.manifest.model.adapter = None
                    mock_bundle.max_turns = 5
                    mock_bundle.termination_tool = "submit_result"
                    mock_bundle.tool_schemas = []
                    mock_bundle.get_plugin.return_value = MagicMock()
                    mock_bundle.get_grammar_config.return_value = MagicMock()
                    mock_bundle.build_tool_source.return_value = MagicMock()
                    mock_bundle.build_initial_messages.return_value = []
                    mock_load.return_value = mock_bundle

                    runner = KernelRunner(
                        node=mock_node,
                        ctx=mock_ctx,
                        config=mock_config,
                        bundle_path=sample_bundle,
                        event_emitter=mock_emitter,
                    )

                    result = await runner.run()

                    assert result.status == AgentStatus.SUCCESS
                    assert result.summary == "Done"
                    mock_kernel.run.assert_called_once()
```

Run:

```bash
uv run pytest tests/test_e2e_refactor.py -v
```

### Step 10.3: Manual Verification

```bash
# Try analyzing a simple file
uv run remora analyze tests/fixtures/sample.py --operations docstring

# Check that events are emitted
uv run remora analyze tests/fixtures/sample.py --operations docstring 2>&1 | head -20
```

---

## Summary

You have now refactored Remora to use the `structured-agents` library:

1. **Removed** ~1,400 lines of code (runner.py, grammar.py, tool_parser.py, execution.py)
2. **Created** `KernelRunner` - thin wrapper around structured-agents AgentKernel
3. **Created** `RemoraEventBridge` - translates events to Remora's format
4. **Updated** `Coordinator` to use KernelRunner
5. **Migrated** subagent YAML files to bundle.yaml format
6. **Simplified** events.py and config.py

The architecture is now:

```
Remora (Orchestration Layer)
├── discovery/          # CST parsing - UNCHANGED
├── context/            # State management - UNCHANGED
├── orchestrator.py     # Uses KernelRunner
├── kernel_runner.py    # NEW: Wraps structured-agents
├── event_bridge.py     # NEW: Event translation
├── externals.py        # Grail externals - UPDATED
└── cli.py              # CLI - UNCHANGED

structured-agents (Execution Layer)
├── kernel.py           # Agent loop
├── plugins/            # Model-specific handling (FunctionGemma, etc.)
├── backends/           # Tool execution (GrailBackend)
├── bundles/            # Bundle loading with registry-based tools
├── registries/         # Tool discovery (GrailRegistry)
├── tool_sources/       # ToolSource protocol
├── grammar/            # Grammar builders (EBNF, JSON Schema)
└── observer/           # Event streaming
```

This is a much cleaner separation of concerns:
- **structured-agents**: Handles the mechanics of tool-calling agents
- **Remora**: Handles codebase navigation and orchestration

### Key API Differences from Original Plan

| Original Guide | Actual API |
|----------------|------------|
| `AgentKernel(backend=...)` | `AgentKernel(tool_source=...)` |
| `tools[].script` | `tools[].registry` + GrailRegistry |
| N/A | `bundle.build_tool_source(backend)` |
| N/A | `bundle.get_grammar_config()` |
| ContextManager `base_context` | ContextManager `initial_context` |
