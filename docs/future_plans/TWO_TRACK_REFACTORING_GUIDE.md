# HubTrack Refactoring Guide

> **Version**: 1.0
> **Target**: Remora Library
> **Phases**: Two-Track Memory (Phase 1) + Node State Hub (Phase 2)

This guide provides step-by-step instructions for implementing the Two-Track Memory and Node State Hub concepts in Remora. It is designed to be followed by developers who are new to the codebase.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Phase 1: Two-Track Memory](#phase-1-two-track-memory)
   - [Step 1.1: Create Core Models](#step-11-create-core-models)
   - [Step 1.2: Create ContextManager](#step-12-create-contextmanager)
   - [Step 1.3: Define Tool Return Contract](#step-13-define-tool-return-contract)
   - [Step 1.4: Create Summarizer Framework](#step-14-create-summarizer-framework)
   - [Step 1.5: Update Tool Scripts](#step-15-update-tool-scripts)
   - [Step 1.6: Integrate with Runner](#step-16-integrate-with-runner)
   - [Step 1.7: Add Pull Hook Stub](#step-17-add-pull-hook-stub)
3. [Phase 2: Node State Hub](#phase-2-node-state-hub)
   - [Step 2.1: Create Hub Models](#step-21-create-hub-models)
   - [Step 2.2: Implement NodeStateKV](#step-22-implement-nodestekv)
   - [Step 2.3: Create Analysis Scripts](#step-23-create-analysis-scripts)
   - [Step 2.4: Implement Rules Engine](#step-24-implement-rules-engine)
   - [Step 2.5: Create File Watcher](#step-25-create-file-watcher)
   - [Step 2.6: Implement IPC Server](#step-26-implement-ipc-server)
   - [Step 2.7: Create Hub Daemon](#step-27-create-hub-daemon)
   - [Step 2.8: Implement HubClient](#step-28-implement-hubclient)
   - [Step 2.9: Wire Pull Hook](#step-29-wire-pull-hook)
4. [Migration Checklist](#migration-checklist)
5. [Appendix: Library APIs](#appendix-library-apis)

---

## Prerequisites

### Required Knowledge

- Python 3.11+ (async/await, type hints)
- Pydantic v2 (BaseModel, Field, validation)
- Basic understanding of event sourcing patterns

### Codebase Orientation

Before starting, familiarize yourself with these files:

| File | Purpose |
|------|---------|
| `remora/runner.py` | FunctionGemmaRunner - the agent execution loop |
| `remora/events.py` | Event emission infrastructure (Long Track exists here) |
| `remora/subagent.py` | SubagentDefinition and tool loading |
| `remora/orchestrator.py` | Coordinator that manages agent runs |
| `agents/*/tools/*.pym` | Grail tool scripts |

### Key Dependencies

| Library | Location | Purpose |
|---------|----------|---------|
| `grail` | `.context/grail/` | Script execution framework |
| `fsdantic` | `.context/fsdantic/` | Typed KV storage |
| `pydantic` | (installed) | Data validation |
| `watchfiles` | (to install) | File system watching |

---

## Phase 1: Two-Track Memory

**Goal**: Implement the Short Track (Decision Packet) alongside the existing Long Track (Event Stream).

**Duration Estimate**: This phase can be completed incrementally. Each step builds on the previous.

---

### Step 1.1: Create Core Models

**File to create**: `remora/context/models.py`

Create the data models for the Decision Packet system.

```python
"""Two-Track Memory models for Remora.

This module defines the Short Track data structures that provide
clean, distilled context to FunctionGemma.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class RecentAction(BaseModel):
    """A single action in the agent's recent history.

    This is a distilled summary of a tool call, not the raw result.
    The rolling window typically keeps the last 10 actions.
    """

    turn: int
    """Which turn this action occurred on."""

    tool: str
    """Name of the tool that was called."""

    summary: str
    """Human-readable summary of what happened (1-2 sentences max)."""

    outcome: Literal["success", "error", "partial"]
    """Overall outcome of the action."""


class KnowledgeEntry(BaseModel):
    """A piece of working knowledge learned during the session.

    Knowledge entries are key-value pairs that persist across turns
    and help the model maintain state without re-reading tool outputs.
    """

    key: str
    """Unique identifier for this knowledge (e.g., 'lint_errors_remaining')."""

    value: Any
    """The knowledge value (structured data, not raw text)."""

    source_turn: int
    """Turn number when this knowledge was acquired."""

    supersedes: str | None = None
    """If set, this entry replaces a previous entry with this key."""


class DecisionPacket(BaseModel):
    """The Short Track - what the model sees.

    This is a projection of the Long Track (event stream), optimized
    for FunctionGemma's context requirements. It provides clean,
    structured state rather than raw tool outputs.

    Key design principles:
    - Keep it small (target: <2K tokens when serialized)
    - Structure over prose (JSON-friendly fields)
    - Recent over complete (rolling window, not full history)
    """

    # === Identity ===
    agent_id: str
    """Unique identifier for this agent run."""

    turn: int = 0
    """Current turn number (0-indexed)."""

    # === Goal Context ===
    goal: str
    """High-level goal (e.g., 'Fix lint errors in foo.py')."""

    operation: str
    """Operation type (e.g., 'lint', 'test', 'docstring')."""

    node_id: str
    """Target node identifier."""

    node_summary: str = ""
    """Brief description of the target code."""

    # === Recent Actions (Rolling Window) ===
    recent_actions: list[RecentAction] = Field(default_factory=list)
    """Last N actions (typically 10). Oldest actions are dropped."""

    # === Working Knowledge ===
    knowledge: dict[str, KnowledgeEntry] = Field(default_factory=dict)
    """Key-value pairs of learned information."""

    # === Error State ===
    last_error: str | None = None
    """Most recent error summary (if any)."""

    error_count: int = 0
    """Total errors encountered this session."""

    # === Hub Context (Injected via Pull Hook) ===
    hub_context: dict[str, Any] | None = None
    """External context from Node State Hub (Phase 2)."""

    hub_freshness: datetime | None = None
    """When hub_context was last updated."""

    # === Metadata ===
    packet_version: str = "1.0"
    """Schema version for forward compatibility."""

    def add_action(
        self,
        tool: str,
        summary: str,
        outcome: Literal["success", "error", "partial"],
        max_actions: int = 10,
    ) -> None:
        """Add an action to recent history, maintaining rolling window."""
        action = RecentAction(
            turn=self.turn,
            tool=tool,
            summary=summary,
            outcome=outcome,
        )
        self.recent_actions.append(action)
        while len(self.recent_actions) > max_actions:
            self.recent_actions.pop(0)

    def update_knowledge(self, key: str, value: Any) -> None:
        """Update or add a knowledge entry."""
        self.knowledge[key] = KnowledgeEntry(
            key=key,
            value=value,
            source_turn=self.turn,
        )

    def record_error(self, error_summary: str) -> None:
        """Record an error occurrence."""
        self.last_error = error_summary
        self.error_count += 1

    def clear_error(self) -> None:
        """Clear the last error (but keep count)."""
        self.last_error = None
```

**Testing (Step 1.1)**:

Create `tests/test_context_models.py`:

```python
"""Tests for Two-Track Memory models."""

import pytest
from remora.context.models import DecisionPacket, RecentAction, KnowledgeEntry


class TestDecisionPacket:
    def test_create_minimal(self):
        """Can create a packet with required fields only."""
        packet = DecisionPacket(
            agent_id="test-001",
            goal="Fix lint errors",
            operation="lint",
            node_id="foo.py:bar",
        )
        assert packet.turn == 0
        assert packet.recent_actions == []
        assert packet.knowledge == {}

    def test_add_action_maintains_rolling_window(self):
        """Actions beyond max are dropped (oldest first)."""
        packet = DecisionPacket(
            agent_id="test-001",
            goal="Test",
            operation="lint",
            node_id="test",
        )

        for i in range(15):
            packet.add_action(
                tool=f"tool_{i}",
                summary=f"Action {i}",
                outcome="success",
                max_actions=10,
            )

        assert len(packet.recent_actions) == 10
        assert packet.recent_actions[0].tool == "tool_5"  # Oldest kept
        assert packet.recent_actions[-1].tool == "tool_14"  # Most recent

    def test_update_knowledge_overwrites(self):
        """Updating knowledge with same key replaces value."""
        packet = DecisionPacket(
            agent_id="test-001",
            goal="Test",
            operation="lint",
            node_id="test",
        )

        packet.update_knowledge("errors", 5)
        packet.turn = 1
        packet.update_knowledge("errors", 3)

        assert packet.knowledge["errors"].value == 3
        assert packet.knowledge["errors"].source_turn == 1

    def test_error_tracking(self):
        """Error count accumulates, last_error can be cleared."""
        packet = DecisionPacket(
            agent_id="test-001",
            goal="Test",
            operation="lint",
            node_id="test",
        )

        packet.record_error("First error")
        packet.record_error("Second error")

        assert packet.error_count == 2
        assert packet.last_error == "Second error"

        packet.clear_error()
        assert packet.last_error is None
        assert packet.error_count == 2  # Count preserved
```

Run tests:
```bash
pytest tests/test_context_models.py -v
```

**Verification Checklist**:
- [ ] All tests pass
- [ ] `DecisionPacket` can be serialized to JSON (`packet.model_dump_json()`)
- [ ] Rolling window behavior works correctly

---

### Step 1.2: Create ContextManager

**File to create**: `remora/context/manager.py`

The ContextManager projects events onto the Decision Packet.

```python
"""ContextManager - Projects events onto the Decision Packet.

This is the core of the Short Track system. It takes events from
the Long Track and updates the Decision Packet state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from remora.context.models import DecisionPacket, KnowledgeEntry, RecentAction

if TYPE_CHECKING:
    from remora.context.summarizers import Summarizer


class ContextManager:
    """Manages the Decision Packet for an agent run.

    The ContextManager is responsible for:
    1. Initializing the packet from initial context
    2. Applying events to update packet state
    3. Providing formatted context for prompts
    4. Integrating external context (Hub Pull Hook)

    Usage:
        ctx = ContextManager(initial_context)
        ctx.apply_event({"type": "tool_result", ...})
        prompt_context = ctx.get_prompt_context()
    """

    # Maximum actions to keep in rolling window
    MAX_RECENT_ACTIONS = 10

    def __init__(
        self,
        initial_context: dict[str, Any],
        summarizers: dict[str, "Summarizer"] | None = None,
    ) -> None:
        """Initialize the ContextManager.

        Args:
            initial_context: Must contain:
                - agent_id: str
                - goal: str
                - operation: str
                - node_id: str
                - node_summary: str (optional)
            summarizers: Optional dict mapping tool names to Summarizer instances.
        """
        self.packet = DecisionPacket(
            agent_id=initial_context["agent_id"],
            turn=0,
            goal=initial_context["goal"],
            operation=initial_context["operation"],
            node_id=initial_context["node_id"],
            node_summary=initial_context.get("node_summary", ""),
        )
        self._summarizers: dict[str, Summarizer] = summarizers or {}
        self._hub_client: Any = None  # Set via set_hub_client()

    def set_hub_client(self, client: Any) -> None:
        """Set the HubClient for Pull Hook integration (Phase 2)."""
        self._hub_client = client

    def apply_event(self, event: dict[str, Any]) -> None:
        """Apply an event to update the Decision Packet.

        This is the main event projection method. It routes events
        to the appropriate handler based on event type.

        Args:
            event: Event dict with at least a "type" field.
        """
        event_type = event.get("type") or event.get("event")

        if event_type == "tool_result":
            self._apply_tool_result(event)
        elif event_type == "turn_start":
            self._apply_turn_start(event)
        elif event_type == "hub_update":
            self._apply_hub_context(event)
        # model_request and model_response don't update packet state

    def increment_turn(self) -> None:
        """Increment the turn counter."""
        self.packet.turn += 1

    async def pull_hub_context(self) -> None:
        """Pull fresh context from Hub (Phase 2 integration).

        This is the Pull Hook - called at the start of each turn
        to inject external context into the Decision Packet.
        """
        if self._hub_client is None:
            return

        try:
            # Get context for current node
            context = await self._hub_client.get_context([self.packet.node_id])
            if context:
                self.packet.hub_context = context
                self.packet.hub_freshness = datetime.now(timezone.utc)
        except Exception:
            # Graceful degradation - Hub is optional
            pass

    def get_prompt_context(self) -> dict[str, Any]:
        """Get the current packet state for prompt building.

        Returns a dict suitable for template rendering or direct
        inclusion in the system prompt.
        """
        return {
            "goal": self.packet.goal,
            "operation": self.packet.operation,
            "node_id": self.packet.node_id,
            "node_summary": self.packet.node_summary,
            "turn": self.packet.turn,
            "recent_actions": [
                {
                    "tool": a.tool,
                    "summary": a.summary,
                    "outcome": a.outcome,
                }
                for a in self.packet.recent_actions
            ],
            "knowledge": {
                k: v.value for k, v in self.packet.knowledge.items()
            },
            "last_error": self.packet.last_error,
            "hub_context": self.packet.hub_context,
        }

    def register_summarizer(self, tool_name: str, summarizer: "Summarizer") -> None:
        """Register a summarizer for a specific tool."""
        self._summarizers[tool_name] = summarizer

    # --- Private Methods ---

    def _apply_tool_result(self, event: dict[str, Any]) -> None:
        """Handle tool_result events."""
        tool_name = event.get("tool_name") or event.get("tool", "unknown")
        data = event.get("data", {})

        # 1. Extract or generate summary
        summary = self._extract_summary(tool_name, data)

        # 2. Determine outcome
        outcome = self._determine_outcome(data)

        # 3. Add to recent actions
        self.packet.add_action(
            tool=tool_name,
            summary=summary,
            outcome=outcome,
            max_actions=self.MAX_RECENT_ACTIONS,
        )

        # 4. Apply knowledge delta
        knowledge_delta = data.get("knowledge_delta", {})
        for key, value in knowledge_delta.items():
            self.packet.update_knowledge(key, value)

        # 5. Handle errors
        if outcome == "error":
            error_msg = data.get("error") or data.get("message") or "Unknown error"
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            self.packet.record_error(str(error_msg)[:200])  # Truncate long errors
        else:
            self.packet.clear_error()

    def _apply_turn_start(self, event: dict[str, Any]) -> None:
        """Handle turn_start events."""
        turn = event.get("turn")
        if isinstance(turn, int):
            self.packet.turn = turn

    def _apply_hub_context(self, event: dict[str, Any]) -> None:
        """Handle hub_update events (external context injection)."""
        context = event.get("context", {})
        self.packet.hub_context = context
        self.packet.hub_freshness = datetime.now(timezone.utc)

    def _extract_summary(self, tool_name: str, data: dict[str, Any]) -> str:
        """Extract or generate a summary from tool result data.

        Priority:
        1. Tool-provided summary (in data["summary"])
        2. Registered summarizer for this tool
        3. Generic fallback
        """
        # Tool-provided summary (preferred)
        if "summary" in data and data["summary"]:
            return str(data["summary"])

        # Registered summarizer
        if tool_name in self._summarizers:
            try:
                raw_result = data.get("result") or data.get("raw_output") or data
                return self._summarizers[tool_name].summarize(raw_result)
            except Exception:
                pass  # Fall through to generic

        # Generic fallback
        if "error" in data:
            return f"{tool_name} failed"
        return f"Executed {tool_name}"

    def _determine_outcome(
        self, data: dict[str, Any]
    ) -> str:  # Literal["success", "error", "partial"]
        """Determine the outcome from tool result data."""
        # Explicit outcome field
        if "outcome" in data:
            outcome = data["outcome"]
            if outcome in ("success", "error", "partial"):
                return outcome

        # Infer from error presence
        if "error" in data and data["error"]:
            return "error"

        # Infer from status field
        status = data.get("status", "").lower()
        if status in ("error", "failed", "failure"):
            return "error"
        if status in ("partial", "warning"):
            return "partial"

        return "success"
```

**File to create**: `remora/context/__init__.py`

```python
"""Two-Track Memory context management for Remora."""

from remora.context.models import (
    DecisionPacket,
    KnowledgeEntry,
    RecentAction,
)
from remora.context.manager import ContextManager

__all__ = [
    "ContextManager",
    "DecisionPacket",
    "KnowledgeEntry",
    "RecentAction",
]
```

**Testing (Step 1.2)**:

Create `tests/test_context_manager.py`:

```python
"""Tests for ContextManager."""

import pytest
from remora.context import ContextManager, DecisionPacket


class TestContextManager:
    @pytest.fixture
    def initial_context(self):
        return {
            "agent_id": "test-001",
            "goal": "Fix lint errors in foo.py",
            "operation": "lint",
            "node_id": "foo.py:bar",
            "node_summary": "A utility function",
        }

    def test_init_creates_packet(self, initial_context):
        """ContextManager initializes a DecisionPacket."""
        ctx = ContextManager(initial_context)

        assert ctx.packet.agent_id == "test-001"
        assert ctx.packet.goal == "Fix lint errors in foo.py"
        assert ctx.packet.operation == "lint"
        assert ctx.packet.turn == 0

    def test_apply_tool_result_with_summary(self, initial_context):
        """Tool-provided summaries are used."""
        ctx = ContextManager(initial_context)

        ctx.apply_event({
            "type": "tool_result",
            "tool_name": "run_linter",
            "data": {
                "summary": "Found 3 lint errors",
                "knowledge_delta": {"lint_errors": 3},
            },
        })

        assert len(ctx.packet.recent_actions) == 1
        assert ctx.packet.recent_actions[0].summary == "Found 3 lint errors"
        assert ctx.packet.knowledge["lint_errors"].value == 3

    def test_apply_tool_result_error(self, initial_context):
        """Errors are tracked correctly."""
        ctx = ContextManager(initial_context)

        ctx.apply_event({
            "type": "tool_result",
            "tool_name": "run_linter",
            "data": {
                "error": "File not found",
            },
        })

        assert ctx.packet.recent_actions[0].outcome == "error"
        assert ctx.packet.last_error == "File not found"
        assert ctx.packet.error_count == 1

    def test_get_prompt_context(self, initial_context):
        """Prompt context is properly formatted."""
        ctx = ContextManager(initial_context)
        ctx.packet.turn = 2
        ctx.packet.add_action("run_linter", "Found 3 errors", "success")
        ctx.packet.update_knowledge("errors", 3)

        prompt_ctx = ctx.get_prompt_context()

        assert prompt_ctx["goal"] == "Fix lint errors in foo.py"
        assert prompt_ctx["turn"] == 2
        assert len(prompt_ctx["recent_actions"]) == 1
        assert prompt_ctx["knowledge"]["errors"] == 3

    def test_increment_turn(self, initial_context):
        """Turn counter increments correctly."""
        ctx = ContextManager(initial_context)

        assert ctx.packet.turn == 0
        ctx.increment_turn()
        assert ctx.packet.turn == 1
        ctx.increment_turn()
        assert ctx.packet.turn == 2
```

Run tests:
```bash
pytest tests/test_context_manager.py -v
```

**Verification Checklist**:
- [ ] All tests pass
- [ ] Event projection updates packet correctly
- [ ] Prompt context format is clean and structured

---

### Step 1.3: Define Tool Return Contract

**File to create**: `remora/context/contracts.py`

Define the expected structure for tool returns.

```python
"""Tool return contract definitions.

This module defines the expected structure for tool results in the
Two-Track Memory system. Tools should return results conforming
to ToolResult schema for optimal context management.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standard tool result structure for Two-Track Memory.

    Tools should return this structure to enable proper summary
    extraction and knowledge management.

    Example:
        return ToolResult(
            result={"errors": [...]},
            summary="Found 3 lint errors on lines 5, 12, 45",
            knowledge_delta={"lint_errors_remaining": 3},
            outcome="success",
        ).model_dump()
    """

    result: Any
    """The full raw result (goes to Long Track only)."""

    summary: str
    """Human-readable summary (1-2 sentences, goes to Short Track)."""

    knowledge_delta: dict[str, Any] = Field(default_factory=dict)
    """Key-value pairs to update in Decision Packet knowledge."""

    outcome: Literal["success", "error", "partial"] = "success"
    """Overall outcome of the operation."""

    error: str | None = None
    """Error message if outcome is 'error'."""


def make_success_result(
    result: Any,
    summary: str,
    knowledge_delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper to create a successful tool result.

    Args:
        result: Raw result data
        summary: Human-readable summary
        knowledge_delta: Optional knowledge updates

    Returns:
        Dict suitable for tool return
    """
    return ToolResult(
        result=result,
        summary=summary,
        knowledge_delta=knowledge_delta or {},
        outcome="success",
    ).model_dump()


def make_error_result(
    error: str,
    summary: str | None = None,
) -> dict[str, Any]:
    """Helper to create an error tool result.

    Args:
        error: Error message
        summary: Optional summary (defaults to error message)

    Returns:
        Dict suitable for tool return
    """
    return ToolResult(
        result=None,
        summary=summary or f"Error: {error}",
        outcome="error",
        error=error,
    ).model_dump()


def make_partial_result(
    result: Any,
    summary: str,
    knowledge_delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper to create a partial success tool result.

    Use this when the tool completed but with warnings or
    incomplete results.

    Args:
        result: Raw result data
        summary: Human-readable summary
        knowledge_delta: Optional knowledge updates

    Returns:
        Dict suitable for tool return
    """
    return ToolResult(
        result=result,
        summary=summary,
        knowledge_delta=knowledge_delta or {},
        outcome="partial",
    ).model_dump()
```

**Testing (Step 1.3)**:

Add to `tests/test_context_models.py`:

```python
from remora.context.contracts import (
    ToolResult,
    make_success_result,
    make_error_result,
    make_partial_result,
)


class TestToolResult:
    def test_success_result_helper(self):
        """make_success_result creates valid structure."""
        result = make_success_result(
            result={"errors": []},
            summary="No errors found",
            knowledge_delta={"lint_clean": True},
        )

        assert result["summary"] == "No errors found"
        assert result["outcome"] == "success"
        assert result["knowledge_delta"]["lint_clean"] is True

    def test_error_result_helper(self):
        """make_error_result creates valid structure."""
        result = make_error_result("File not found")

        assert result["outcome"] == "error"
        assert result["error"] == "File not found"
        assert "Error:" in result["summary"]

    def test_partial_result_helper(self):
        """make_partial_result creates valid structure."""
        result = make_partial_result(
            result={"fixed": 2, "remaining": 1},
            summary="Fixed 2 of 3 errors",
        )

        assert result["outcome"] == "partial"
        assert result["summary"] == "Fixed 2 of 3 errors"
```

---

### Step 1.4: Create Summarizer Framework

**File to create**: `remora/context/summarizers.py`

```python
"""Summarizer framework for tool result distillation.

Summarizers convert raw tool outputs into concise summaries for
the Decision Packet. They are the fallback when tools don't provide
their own summaries.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Summarizer(ABC):
    """Base class for tool result summarizers.

    Implement this to create custom summarizers for specific tools.
    Register them with ContextManager.register_summarizer().
    """

    @abstractmethod
    def summarize(self, raw_result: Any) -> str:
        """Generate a summary from raw tool output.

        Args:
            raw_result: The raw result from the tool

        Returns:
            A concise summary (1-2 sentences max)
        """
        ...

    def extract_knowledge(self, raw_result: Any) -> dict[str, Any]:
        """Extract knowledge entries from raw output.

        Override this to automatically populate knowledge_delta
        when the tool doesn't provide one.

        Args:
            raw_result: The raw result from the tool

        Returns:
            Dict of key-value pairs to add to knowledge
        """
        return {}


class ToolSidePassthrough(Summarizer):
    """Passes through tool-provided summaries.

    This is the default summarizer - it extracts summary from
    the result if present, otherwise returns a generic message.
    """

    def summarize(self, raw_result: Any) -> str:
        if isinstance(raw_result, dict):
            if "summary" in raw_result:
                return str(raw_result["summary"])
            if "message" in raw_result:
                return str(raw_result["message"])
        return "Tool completed"

    def extract_knowledge(self, raw_result: Any) -> dict[str, Any]:
        if isinstance(raw_result, dict):
            return raw_result.get("knowledge_delta", {})
        return {}


class LinterSummarizer(Summarizer):
    """Summarizer for linter tool results."""

    def summarize(self, raw_result: Any) -> str:
        if not isinstance(raw_result, dict):
            return "Ran linter"

        errors = raw_result.get("errors", [])
        fixed = raw_result.get("fixed", 0)

        if fixed > 0:
            remaining = len(errors)
            if remaining == 0:
                return f"Fixed all {fixed} lint errors"
            return f"Fixed {fixed} lint errors, {remaining} remaining"

        if not errors:
            return "No lint errors found"

        return f"Found {len(errors)} lint errors"

    def extract_knowledge(self, raw_result: Any) -> dict[str, Any]:
        if not isinstance(raw_result, dict):
            return {}

        return {
            "lint_errors_remaining": len(raw_result.get("errors", [])),
            "lint_errors_fixed": raw_result.get("fixed", 0),
        }


class TestRunnerSummarizer(Summarizer):
    """Summarizer for test runner results."""

    def summarize(self, raw_result: Any) -> str:
        if not isinstance(raw_result, dict):
            return "Ran tests"

        passed = raw_result.get("passed", 0)
        failed = raw_result.get("failed", 0)
        total = passed + failed

        if failed == 0:
            return f"All {total} tests passed"

        return f"{failed} of {total} tests failed"

    def extract_knowledge(self, raw_result: Any) -> dict[str, Any]:
        if not isinstance(raw_result, dict):
            return {}

        return {
            "tests_passed": raw_result.get("passed", 0),
            "tests_failed": raw_result.get("failed", 0),
        }


# Registry of built-in summarizers
BUILTIN_SUMMARIZERS: dict[str, Summarizer] = {
    "run_linter": LinterSummarizer(),
    "apply_fix": LinterSummarizer(),
    "run_tests": TestRunnerSummarizer(),
}


def get_default_summarizers() -> dict[str, Summarizer]:
    """Get a copy of built-in summarizers."""
    return BUILTIN_SUMMARIZERS.copy()
```

**Testing (Step 1.4)**:

Create `tests/test_summarizers.py`:

```python
"""Tests for summarizers."""

import pytest
from remora.context.summarizers import (
    LinterSummarizer,
    TestRunnerSummarizer,
    ToolSidePassthrough,
)


class TestLinterSummarizer:
    def test_summarize_no_errors(self):
        summarizer = LinterSummarizer()
        result = summarizer.summarize({"errors": []})
        assert "No lint errors" in result

    def test_summarize_with_errors(self):
        summarizer = LinterSummarizer()
        result = summarizer.summarize({"errors": [1, 2, 3]})
        assert "3 lint errors" in result

    def test_summarize_with_fixes(self):
        summarizer = LinterSummarizer()
        result = summarizer.summarize({"errors": [1], "fixed": 2})
        assert "Fixed 2" in result
        assert "1 remaining" in result

    def test_extract_knowledge(self):
        summarizer = LinterSummarizer()
        knowledge = summarizer.extract_knowledge({"errors": [1, 2], "fixed": 1})
        assert knowledge["lint_errors_remaining"] == 2
        assert knowledge["lint_errors_fixed"] == 1


class TestTestRunnerSummarizer:
    def test_summarize_all_passed(self):
        summarizer = TestRunnerSummarizer()
        result = summarizer.summarize({"passed": 5, "failed": 0})
        assert "All 5 tests passed" in result

    def test_summarize_with_failures(self):
        summarizer = TestRunnerSummarizer()
        result = summarizer.summarize({"passed": 3, "failed": 2})
        assert "2 of 5 tests failed" in result


class TestToolSidePassthrough:
    def test_passes_through_summary(self):
        summarizer = ToolSidePassthrough()
        result = summarizer.summarize({"summary": "Custom summary"})
        assert result == "Custom summary"

    def test_falls_back_to_message(self):
        summarizer = ToolSidePassthrough()
        result = summarizer.summarize({"message": "Operation complete"})
        assert result == "Operation complete"

    def test_generic_fallback(self):
        summarizer = ToolSidePassthrough()
        result = summarizer.summarize({"data": "something"})
        assert result == "Tool completed"
```

---

### Step 1.5: Update Tool Scripts

**Goal**: Modify existing `.pym` tool scripts to return the Two-Track format.

This step is incremental - update tools one at a time while maintaining backward compatibility.

**Example Update**: `agents/lint/tools/run_linter.pym`

Before (simplified):
```python
# ... existing code ...

async def main():
    result = await run_ruff_check(file_path)
    return result  # Raw result only
```

After:
```python
# ... existing code ...

async def main():
    result = await run_ruff_check(file_path)

    # Generate summary
    errors = result.get("errors", [])
    fixed = result.get("fixed", 0)

    if fixed > 0:
        summary = f"Fixed {fixed} lint errors, {len(errors)} remaining"
    elif not errors:
        summary = "No lint errors found"
    else:
        summary = f"Found {len(errors)} lint errors"

    # Return Two-Track format
    return {
        "result": result,
        "summary": summary,
        "knowledge_delta": {
            "lint_errors_remaining": len(errors),
            "lint_errors_fixed": fixed,
        },
        "outcome": "error" if errors else "success",
    }
```

**Testing (Step 1.5)**:

For each updated tool, verify:
1. The return value matches `ToolResult` schema
2. Summary is concise (< 100 chars)
3. `knowledge_delta` contains useful state

Create a test helper in `tests/utils/tool_contract.py`:

```python
"""Helpers for testing tool return contracts."""

from remora.context.contracts import ToolResult


def assert_valid_tool_result(result: dict) -> None:
    """Assert that a tool result follows the Two-Track contract."""
    # Must have required fields
    assert "result" in result or "summary" in result, "Missing result or summary"
    assert "summary" in result, "Missing summary"
    assert "outcome" in result, "Missing outcome"

    # Outcome must be valid
    assert result["outcome"] in ("success", "error", "partial"), f"Invalid outcome: {result['outcome']}"

    # Summary should be concise
    assert len(result["summary"]) < 200, f"Summary too long: {len(result['summary'])} chars"

    # knowledge_delta should be dict
    if "knowledge_delta" in result:
        assert isinstance(result["knowledge_delta"], dict), "knowledge_delta must be dict"

    # Validates against Pydantic model
    ToolResult.model_validate(result)
```

---

### Step 1.6: Integrate with Runner

**File to modify**: `remora/runner.py`

This is the key integration step. We'll add ContextManager alongside the existing messages list.

**Changes**:

1. Add ContextManager initialization in `__post_init__`
2. Apply events to ContextManager alongside message updates
3. Build prompts from Decision Packet context

```python
# Add to imports at top of runner.py
from remora.context import ContextManager
from remora.context.summarizers import get_default_summarizers

# In FunctionGemmaRunner class, add to __post_init__:
def __post_init__(self) -> None:
    # ... existing initialization ...

    # Initialize context manager (Two-Track Short Track)
    initial_context = {
        "agent_id": self.ctx.agent_id,
        "goal": f"{self.definition.name} on {self.node.name}",
        "operation": self.definition.name,
        "node_id": self.node.node_id,
        "node_summary": self._summarize_node(),
    }
    self.context_manager = ContextManager(
        initial_context,
        summarizers=get_default_summarizers(),
    )

def _summarize_node(self) -> str:
    """Generate a brief summary of the target node."""
    node = self.node
    return f"{node.node_type.value} '{node.name}' in {node.file_path.name}"


# Modify run() to update both tracks:
async def run(self) -> AgentResult:
    """Execute the model loop until a result is produced."""
    # Pull hub context at start (Phase 2 - no-op stub for now)
    await self.context_manager.pull_hub_context()

    message = await self._call_model(phase="model_load", tool_choice=self._tool_choice_for_turn(1))

    while self.turn_count < self.definition.max_turns:
        self.turn_count += 1
        self.context_manager.increment_turn()  # NEW: Track turn

        self.messages.append(self._coerce_message_param(message))
        tool_calls = message.tool_calls or []
        if not tool_calls:
            return self._handle_no_tool_calls(message)
        for tool_call in tool_calls:
            tool_function = getattr(tool_call, "function", None)
            name = getattr(tool_function, "name", None)
            if name == SUBMIT_RESULT_TOOL:
                return self._build_submit_result(getattr(tool_function, "arguments", None))

            # Execute tool
            tool_result_content = await self._dispatch_tool(tool_call)

            # NEW: Apply event to context manager
            self._apply_tool_result_event(name or "unknown", tool_result_content)

            tool_call_id = getattr(tool_call, "id", None) or _missing_identifier("tool-call")
            tool_name = name or _missing_identifier("tool-name")
            self.messages.append(
                cast(
                    ChatCompletionMessageParam,
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": tool_result_content,
                    },
                )
            )

        # Pull hub context before next model call (Phase 2)
        await self.context_manager.pull_hub_context()

        next_turn = self.turn_count + 1
        message = await self._call_model(phase="loop", tool_choice=self._tool_choice_for_turn(next_turn))

    raise AgentError(...)


def _apply_tool_result_event(self, tool_name: str, result_json: str) -> None:
    """Apply a tool result event to the context manager."""
    try:
        data = json.loads(result_json) if result_json else {}
    except json.JSONDecodeError:
        data = {"raw": result_json}

    self.context_manager.apply_event({
        "type": "tool_result",
        "tool_name": tool_name,
        "data": data,
    })
```

**Testing (Step 1.6)**:

Update `tests/test_runner.py` to verify context tracking:

```python
def test_context_manager_tracks_tool_calls(monkeypatch):
    """Context manager receives tool result events."""
    from remora.testing import patch_openai, make_definition, make_node, make_ctx
    from remora.testing import make_server_config, make_runner_config, tool_call_message

    patch_openai(monkeypatch, responses=[
        tool_call_message("run_linter", {}),
        tool_call_message("submit_result", {"summary": "Done"}),
    ])

    runner = FunctionGemmaRunner(
        definition=make_definition(),
        node=make_node(),
        ctx=make_ctx(),
        server_config=make_server_config(),
        runner_config=make_runner_config(),
    )

    # Mock grail executor to return Two-Track format
    async def mock_execute(*args, **kwargs):
        return {
            "result": {"errors": []},
            "summary": "No errors found",
            "knowledge_delta": {"lint_errors": 0},
            "outcome": "success",
        }

    # ... setup and run ...

    # Verify context manager state
    assert runner.context_manager.packet.turn > 0
    assert len(runner.context_manager.packet.recent_actions) > 0
```

**Verification Checklist**:
- [ ] Existing tests still pass (backward compatible)
- [ ] ContextManager is initialized with correct initial context
- [ ] Tool results are applied to context manager
- [ ] Turn counter increments correctly

---

### Step 1.7: Add Pull Hook Stub

The Pull Hook is the integration point for the Node State Hub (Phase 2). For now, we implement a no-op stub.

**File to create**: `remora/context/hub_client.py`

```python
"""Hub client stub for Pull Hook integration.

This module provides a stub implementation of the Hub client.
In Phase 2, this will be replaced with actual Hub communication.
"""

from __future__ import annotations

from typing import Any


class HubClientStub:
    """Stub Hub client that does nothing.

    This allows the ContextManager to call pull_hub_context()
    without errors, even when the Hub is not available.
    """

    async def get_context(self, node_ids: list[str]) -> dict[str, Any]:
        """Return empty context (Hub not implemented yet)."""
        return {}

    async def health_check(self) -> bool:
        """Return False (Hub not running)."""
        return False


# Singleton stub instance
_hub_client_stub = HubClientStub()


def get_hub_client() -> HubClientStub:
    """Get the Hub client instance.

    In Phase 2, this will attempt to connect to the actual Hub.
    For now, returns the stub.
    """
    return _hub_client_stub
```

**Update `remora/context/__init__.py`**:

```python
from remora.context.hub_client import HubClientStub, get_hub_client

__all__ = [
    # ... existing exports ...
    "HubClientStub",
    "get_hub_client",
]
```

---

## Phase 2: Node State Hub

**Goal**: Implement the background daemon that maintains a live index of codebase metadata.

**Prerequisites**: Phase 1 complete (Pull Hook stub exists)

---

### Step 2.1: Create Hub Models

**File to create**: `remora/hub/models.py`

```python
"""Node State Hub data models.

These models define the structure of metadata stored and
served by the Hub daemon.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NodeState(BaseModel):
    """State for a single code node.

    This is what the Hub stores and serves to clients.
    """

    # === Identity ===
    key: str
    """Unique key: 'node:{file_path}:{node_name}'"""

    file_path: str
    """Absolute path to the file containing this node."""

    node_name: str
    """Name of the function, class, or module."""

    node_type: Literal["function", "class", "module"]
    """Type of code node."""

    # === Content Hashes (for change detection) ===
    source_hash: str
    """SHA256 of the node's source code."""

    file_hash: str
    """SHA256 of the entire file."""

    # === Static Analysis Results ===
    signature: str | None = None
    """Function/class signature: 'def foo(x: int) -> str'"""

    docstring: str | None = None
    """First line of docstring (truncated)."""

    imports: list[str] = Field(default_factory=list)
    """List of imports used by this node."""

    decorators: list[str] = Field(default_factory=list)
    """List of decorators: ['@staticmethod', '@cached']"""

    # === Cross-File Analysis (Expensive, Lazy) ===
    callers: list[str] | None = None
    """Nodes that call this node: ['bar.py:process']"""

    callees: list[str] | None = None
    """Nodes this calls: ['os.path.join']"""

    # === Test Discovery ===
    related_tests: list[str] | None = None
    """Test functions that exercise this node."""

    # === Quality Metrics ===
    line_count: int | None = None
    """Number of lines in this node."""

    complexity: int | None = None
    """Cyclomatic complexity score."""

    # === Flags ===
    docstring_outdated: bool = False
    """True if signature changed but docstring didn't."""

    has_type_hints: bool = True
    """True if function has type annotations."""

    # === Freshness ===
    last_updated: datetime
    """When this state was last computed."""

    update_source: Literal["file_change", "dependency_change", "manual", "cold_start"]
    """What triggered this update."""


class FileIndex(BaseModel):
    """Tracking entry for a source file."""

    file_path: str
    """Absolute path to the file."""

    file_hash: str
    """SHA256 of file contents."""

    node_count: int
    """Number of nodes extracted from this file."""

    last_scanned: datetime
    """When this file was last scanned."""


class HubStatus(BaseModel):
    """Status information from the Hub."""

    running: bool
    """Whether the Hub daemon is running."""

    root_path: str
    """Project root being watched."""

    indexed_files: int
    """Number of files in the index."""

    indexed_nodes: int
    """Number of nodes in the index."""

    uptime_seconds: float
    """How long the Hub has been running."""

    last_update: datetime | None
    """When the index was last updated."""
```

**Testing (Step 2.1)**:

```python
"""Tests for Hub models."""

import pytest
from datetime import datetime
from remora.hub.models import NodeState, FileIndex, HubStatus


class TestNodeState:
    def test_create_function_node(self):
        state = NodeState(
            key="node:foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            signature="def bar(x: int) -> str",
            last_updated=datetime.now(),
            update_source="file_change",
        )

        assert state.node_type == "function"
        assert state.signature == "def bar(x: int) -> str"

    def test_serializes_to_json(self):
        state = NodeState(
            key="node:foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            last_updated=datetime.now(),
            update_source="cold_start",
        )

        json_str = state.model_dump_json()
        assert "foo.py" in json_str
```

---

### Step 2.2: Implement NodeStateKV

**File to create**: `remora/hub/storage.py`

This uses fsdantic for SQLite-backed storage.

```python
"""Node State KV storage using fsdantic.

This module provides persistent storage for NodeState objects
using fsdantic's TypedKVRepository.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from remora.hub.models import NodeState, FileIndex


class NodeStateKV:
    """SQLite-backed storage for NodeState.

    This is a lightweight wrapper around SQLite that stores
    NodeState objects as JSON blobs.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the KV store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")  # Concurrent reads
        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS node_state (
                key TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                node_name TEXT NOT NULL,
                node_type TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                state_json TEXT NOT NULL,
                last_updated REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_file_path
            ON node_state(file_path);

            CREATE INDEX IF NOT EXISTS idx_last_updated
            ON node_state(last_updated);

            CREATE TABLE IF NOT EXISTS file_index (
                file_path TEXT PRIMARY KEY,
                file_hash TEXT NOT NULL,
                node_count INTEGER NOT NULL,
                last_scanned REAL NOT NULL
            );
        """)
        self._conn.commit()

    def get(self, key: str) -> NodeState | None:
        """Get a NodeState by key."""
        cursor = self._conn.execute(
            "SELECT state_json FROM node_state WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return NodeState.model_validate_json(row[0])

    def get_many(self, keys: list[str]) -> dict[str, NodeState]:
        """Get multiple NodeStates by keys."""
        if not keys:
            return {}

        placeholders = ",".join("?" * len(keys))
        cursor = self._conn.execute(
            f"SELECT key, state_json FROM node_state WHERE key IN ({placeholders})",
            keys,
        )

        result = {}
        for row in cursor:
            key, state_json = row
            result[key] = NodeState.model_validate_json(state_json)
        return result

    def set(self, state: NodeState) -> None:
        """Store a NodeState."""
        self._conn.execute(
            """INSERT OR REPLACE INTO node_state
               (key, file_path, node_name, node_type, source_hash, state_json, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                state.key,
                state.file_path,
                state.node_name,
                state.node_type,
                state.source_hash,
                state.model_dump_json(),
                state.last_updated.timestamp(),
            ),
        )
        self._conn.commit()

    def delete(self, key: str) -> bool:
        """Delete a NodeState by key."""
        cursor = self._conn.execute(
            "DELETE FROM node_state WHERE key = ?",
            (key,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_by_file(self, file_path: str) -> list[NodeState]:
        """Get all NodeStates for a file."""
        cursor = self._conn.execute(
            "SELECT state_json FROM node_state WHERE file_path = ?",
            (file_path,),
        )
        return [NodeState.model_validate_json(row[0]) for row in cursor]

    def invalidate_file(self, file_path: str) -> list[str]:
        """Remove all nodes for a file, return deleted keys."""
        cursor = self._conn.execute(
            "SELECT key FROM node_state WHERE file_path = ?",
            (file_path,),
        )
        deleted = [row[0] for row in cursor]

        self._conn.execute(
            "DELETE FROM node_state WHERE file_path = ?",
            (file_path,),
        )
        self._conn.commit()
        return deleted

    def gc_orphans(self, max_age_hours: int = 24) -> int:
        """Remove stale entries older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        cursor = self._conn.execute(
            "DELETE FROM node_state WHERE last_updated < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cursor.rowcount

    # --- File Index Methods ---

    def get_file_index(self, file_path: str) -> FileIndex | None:
        """Get file index entry."""
        cursor = self._conn.execute(
            "SELECT file_hash, node_count, last_scanned FROM file_index WHERE file_path = ?",
            (file_path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return FileIndex(
            file_path=file_path,
            file_hash=row[0],
            node_count=row[1],
            last_scanned=datetime.fromtimestamp(row[2], tz=timezone.utc),
        )

    def set_file_index(self, index: FileIndex) -> None:
        """Store file index entry."""
        self._conn.execute(
            """INSERT OR REPLACE INTO file_index
               (file_path, file_hash, node_count, last_scanned)
               VALUES (?, ?, ?, ?)""",
            (
                index.file_path,
                index.file_hash,
                index.node_count,
                index.last_scanned.timestamp(),
            ),
        )
        self._conn.commit()

    def stats(self) -> dict[str, int]:
        """Get storage statistics."""
        node_count = self._conn.execute(
            "SELECT COUNT(*) FROM node_state"
        ).fetchone()[0]
        file_count = self._conn.execute(
            "SELECT COUNT(*) FROM file_index"
        ).fetchone()[0]
        return {"nodes": node_count, "files": file_count}

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
```

**Testing (Step 2.2)**:

```python
"""Tests for NodeStateKV."""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from remora.hub.storage import NodeStateKV
from remora.hub.models import NodeState


@pytest.fixture
def kv_store(tmp_path):
    """Create a temporary KV store."""
    db_path = tmp_path / "test.db"
    store = NodeStateKV(db_path)
    yield store
    store.close()


class TestNodeStateKV:
    def test_set_and_get(self, kv_store):
        state = NodeState(
            key="node:foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            last_updated=datetime.now(timezone.utc),
            update_source="file_change",
        )

        kv_store.set(state)
        retrieved = kv_store.get("node:foo.py:bar")

        assert retrieved is not None
        assert retrieved.node_name == "bar"
        assert retrieved.source_hash == "abc123"

    def test_get_missing_returns_none(self, kv_store):
        result = kv_store.get("nonexistent")
        assert result is None

    def test_invalidate_file_removes_all_nodes(self, kv_store):
        # Add multiple nodes for same file
        for name in ["foo", "bar", "baz"]:
            state = NodeState(
                key=f"node:test.py:{name}",
                file_path="/project/test.py",
                node_name=name,
                node_type="function",
                source_hash=f"hash_{name}",
                file_hash="file_hash",
                last_updated=datetime.now(timezone.utc),
                update_source="file_change",
            )
            kv_store.set(state)

        deleted = kv_store.invalidate_file("/project/test.py")

        assert len(deleted) == 3
        assert kv_store.get("node:test.py:foo") is None
```

---

### Step 2.3: Create Analysis Scripts

**Directory to create**: `agents/hub/tools/`

Create Grail scripts for static analysis.

**File**: `agents/hub/tools/extract_signatures.pym`

```python
"""Extract function/class signatures from a Python file.

This script parses a Python file and extracts metadata for
all functions and classes.
"""

from grail import Input, external
from typing import Any
import ast
import hashlib

file_path: str = Input("file_path")

@external
async def read_file(path: str) -> str:
    """Read file contents."""
    ...


async def main() -> dict[str, Any]:
    """Extract signatures from the file."""
    content = await read_file(file_path)
    file_hash = hashlib.sha256(content.encode()).hexdigest()

    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return {
            "error": f"Syntax error: {e}",
            "file_path": file_path,
        }

    nodes = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            nodes.append(_extract_function(node, content))
        elif isinstance(node, ast.AsyncFunctionDef):
            nodes.append(_extract_function(node, content, is_async=True))
        elif isinstance(node, ast.ClassDef):
            nodes.append(_extract_class(node, content))

    return {
        "file_path": file_path,
        "file_hash": file_hash,
        "nodes": nodes,
    }


def _extract_function(node: ast.FunctionDef, source: str, is_async: bool = False) -> dict:
    """Extract function metadata."""
    # Get source lines for this function
    lines = source.splitlines()
    start = node.lineno - 1
    end = node.end_lineno or start + 1
    func_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(func_source.encode()).hexdigest()

    # Build signature
    args = []
    for arg in node.args.args:
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"
        args.append(arg_str)

    returns = ""
    if node.returns:
        returns = f" -> {ast.unparse(node.returns)}"

    prefix = "async def" if is_async else "def"
    signature = f"{prefix} {node.name}({', '.join(args)}){returns}"

    # Get docstring
    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]  # First line, truncated

    # Get decorators
    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    return {
        "name": node.name,
        "type": "function",
        "signature": signature,
        "docstring": docstring,
        "decorators": decorators,
        "source_hash": source_hash,
        "line_count": end - start,
        "has_type_hints": node.returns is not None or any(a.annotation for a in node.args.args),
    }


def _extract_class(node: ast.ClassDef, source: str) -> dict:
    """Extract class metadata."""
    lines = source.splitlines()
    start = node.lineno - 1
    end = node.end_lineno or start + 1
    class_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(class_source.encode()).hexdigest()

    # Build signature
    bases = [ast.unparse(b) for b in node.bases]
    signature = f"class {node.name}"
    if bases:
        signature += f"({', '.join(bases)})"

    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    return {
        "name": node.name,
        "type": "class",
        "signature": signature,
        "docstring": docstring,
        "decorators": decorators,
        "source_hash": source_hash,
        "line_count": end - start,
        "has_type_hints": True,  # Classes don't have return annotations
    }
```

**Testing (Step 2.3)**:

Create integration tests that run the scripts against sample files.

---

### Step 2.4: Implement Rules Engine

**File to create**: `remora/hub/rules.py`

```python
"""Rules Engine for Hub updates.

The Rules Engine decides what actions to take when a file changes.
It is completely deterministic - no LLM involved.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remora.hub.models import NodeState


@dataclass
class UpdateAction(ABC):
    """Base class for update actions."""

    @abstractmethod
    async def execute(self, context: "RulesContext") -> dict[str, Any]:
        """Execute the update action."""
        ...


@dataclass
class ExtractSignatures(UpdateAction):
    """Extract signatures from a file."""
    file_path: Path

    async def execute(self, context: "RulesContext") -> dict[str, Any]:
        return await context.run_script(
            "hub/tools/extract_signatures.pym",
            {"file_path": str(self.file_path)},
        )


@dataclass
class ScanImports(UpdateAction):
    """Scan imports from a file."""
    file_path: Path

    async def execute(self, context: "RulesContext") -> dict[str, Any]:
        return await context.run_script(
            "hub/tools/scan_imports.pym",
            {"file_path": str(self.file_path)},
        )


@dataclass
class DeleteFileNodes(UpdateAction):
    """Delete all nodes for a file."""
    file_path: Path

    async def execute(self, context: "RulesContext") -> dict[str, Any]:
        deleted = context.kv.invalidate_file(str(self.file_path))
        return {"deleted": deleted, "count": len(deleted)}


@dataclass
class RulesContext:
    """Context for executing rules."""
    kv: Any  # NodeStateKV
    executor: Any  # GrailExecutor
    grail_dir: Path

    async def run_script(self, script: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return await self.executor.execute(
            pym_path=Path(script),
            grail_dir=self.grail_dir,
            inputs=inputs,
        )


class RulesEngine:
    """Decides what to recompute when a file changes."""

    def get_update_actions(
        self,
        change_type: str,  # "added", "modified", "deleted"
        file_path: Path,
        old_states: dict[str, NodeState] | None = None,
    ) -> list[UpdateAction]:
        """Determine actions to take for a file change.

        Args:
            change_type: Type of change
            file_path: Path to changed file
            old_states: Previous NodeStates for this file (if any)

        Returns:
            List of actions to execute
        """
        actions: list[UpdateAction] = []

        if change_type == "deleted":
            actions.append(DeleteFileNodes(file_path))
            return actions

        # For added/modified: always extract signatures
        actions.append(ExtractSignatures(file_path))
        actions.append(ScanImports(file_path))

        # Future: add more sophisticated rules
        # - If signature changed, find callers
        # - If new function, find tests
        # - If imports changed, update dependency graph

        return actions
```

---

### Step 2.5: Create File Watcher

**File to create**: `remora/hub/watcher.py`

```python
"""File watcher for the Hub daemon.

Uses watchfiles library for efficient filesystem monitoring.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Callable, Awaitable

try:
    import watchfiles
    WATCHFILES_AVAILABLE = True
except ImportError:
    WATCHFILES_AVAILABLE = False


class FileWatcher:
    """Watches a directory for Python file changes."""

    def __init__(
        self,
        root: Path,
        callback: Callable[[str, Path], Awaitable[None]],
    ) -> None:
        """Initialize the watcher.

        Args:
            root: Directory to watch
            callback: Async function called with (change_type, path)
        """
        if not WATCHFILES_AVAILABLE:
            raise RuntimeError("watchfiles not installed. Run: pip install watchfiles")

        self.root = root
        self.callback = callback
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start watching for changes."""
        async for changes in watchfiles.awatch(
            self.root,
            stop_event=self._stop_event,
            recursive=True,
        ):
            for change_type, path_str in changes:
                path = Path(path_str)

                # Only process Python files
                if not path.suffix == ".py":
                    continue

                # Skip __pycache__ and hidden files
                if "__pycache__" in path.parts or path.name.startswith("."):
                    continue

                # Map watchfiles change type to our string
                type_map = {
                    watchfiles.Change.added: "added",
                    watchfiles.Change.modified: "modified",
                    watchfiles.Change.deleted: "deleted",
                }
                change = type_map.get(change_type, "modified")

                try:
                    await self.callback(change, path)
                except Exception as e:
                    # Log but don't crash on errors
                    print(f"Error processing {path}: {e}")

    def stop(self) -> None:
        """Stop watching."""
        self._stop_event.set()
```

---

### Step 2.6: Implement IPC Server

**File to create**: `remora/hub/server.py`

```python
"""IPC server for Hub daemon.

Provides Unix socket interface for clients to query node state.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from remora.hub.storage import NodeStateKV


class HubServer:
    """Unix socket server for Hub queries."""

    def __init__(
        self,
        socket_path: Path,
        kv: NodeStateKV,
    ) -> None:
        self.socket_path = socket_path
        self.kv = kv
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start the server."""
        # Remove existing socket
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path),
        )

        # Set permissions
        self.socket_path.chmod(0o600)

    async def stop(self) -> None:
        """Stop the server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        if self.socket_path.exists():
            self.socket_path.unlink()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        try:
            data = await reader.read(65536)
            request = json.loads(data.decode())

            response = await self._handle_request(request)

            writer.write(json.dumps(response).encode())
            await writer.drain()
        except Exception as e:
            error_response = {"error": str(e)}
            writer.write(json.dumps(error_response).encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process a request and return response."""
        request_type = request.get("type")

        if request_type == "get_context":
            node_ids = request.get("nodes", [])
            states = self.kv.get_many(node_ids)
            return {
                "nodes": {
                    k: v.model_dump() for k, v in states.items()
                }
            }

        elif request_type == "health":
            stats = self.kv.stats()
            return {
                "status": "ok",
                "nodes": stats["nodes"],
                "files": stats["files"],
            }

        else:
            return {"error": f"Unknown request type: {request_type}"}
```

---

### Step 2.7: Create Hub Daemon

**File to create**: `remora/hub/daemon.py`

```python
"""Hub daemon implementation.

The main daemon that coordinates watching, indexing, and serving.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from remora.hub.models import NodeState, FileIndex
from remora.hub.storage import NodeStateKV
from remora.hub.rules import RulesEngine, RulesContext
from remora.hub.watcher import FileWatcher
from remora.hub.server import HubServer


class HubDaemon:
    """The Node State Hub daemon."""

    def __init__(
        self,
        root: Path,
        socket_path: Path = Path("/tmp/remora-hub.sock"),
        db_path: Path = Path("~/.cache/remora/hub.db"),
        grail_dir: Path | None = None,
        executor: Any = None,
    ) -> None:
        self.root = root.resolve()
        self.socket_path = socket_path
        self.db_path = db_path.expanduser()
        self.grail_dir = grail_dir or (root / "agents")
        self.executor = executor

        self.kv = NodeStateKV(self.db_path)
        self.rules = RulesEngine()
        self.server = HubServer(socket_path, self.kv)
        self.watcher = FileWatcher(root, self._handle_file_change)

        self._start_time = datetime.now(timezone.utc)

    async def run(self) -> None:
        """Run the daemon."""
        print(f"Hub starting: watching {self.root}")

        # 1. Cold start: index existing files
        await self._cold_start_index()

        # 2. Start server
        await self.server.start()
        print(f"Hub server listening on {self.socket_path}")

        # 3. Start watcher
        try:
            await self.watcher.start()
        except asyncio.CancelledError:
            pass
        finally:
            await self.server.stop()
            self.kv.close()
            print("Hub stopped")

    async def _cold_start_index(self) -> None:
        """Index all Python files on startup."""
        print("Cold start: indexing existing files...")

        indexed = 0
        for py_file in self.root.rglob("*.py"):
            # Skip __pycache__ and hidden
            if "__pycache__" in py_file.parts or py_file.name.startswith("."):
                continue

            # Check if file changed since last index
            file_hash = self._hash_file(py_file)
            existing = self.kv.get_file_index(str(py_file))

            if existing and existing.file_hash == file_hash:
                continue  # No changes

            await self._index_file(py_file, "cold_start")
            indexed += 1

        print(f"Cold start complete: indexed {indexed} files")

    async def _handle_file_change(self, change_type: str, path: Path) -> None:
        """Handle a file change event."""
        print(f"File change: {change_type} {path}")

        # Get old state for this file
        old_states = {
            s.key: s for s in self.kv.get_by_file(str(path))
        }

        # Get actions from rules engine
        actions = self.rules.get_update_actions(change_type, path, old_states)

        # Execute actions
        context = RulesContext(
            kv=self.kv,
            executor=self.executor,
            grail_dir=self.grail_dir,
        )

        for action in actions:
            result = await action.execute(context)

            # Process extract_signatures result
            if hasattr(action, "file_path") and "nodes" in result:
                await self._store_nodes(
                    result["file_path"],
                    result["file_hash"],
                    result["nodes"],
                    "file_change",
                )

    async def _index_file(self, path: Path, source: str) -> None:
        """Index a single file."""
        if self.executor is None:
            return  # No executor configured

        context = RulesContext(
            kv=self.kv,
            executor=self.executor,
            grail_dir=self.grail_dir,
        )

        # Run extraction
        result = await context.run_script(
            "hub/tools/extract_signatures.pym",
            {"file_path": str(path)},
        )

        if "error" in result:
            print(f"Error indexing {path}: {result['error']}")
            return

        await self._store_nodes(
            result["file_path"],
            result["file_hash"],
            result["nodes"],
            source,
        )

    async def _store_nodes(
        self,
        file_path: str,
        file_hash: str,
        nodes: list[dict],
        source: str,
    ) -> None:
        """Store extracted nodes in KV."""
        now = datetime.now(timezone.utc)

        # Store each node
        for node_data in nodes:
            key = f"node:{file_path}:{node_data['name']}"
            state = NodeState(
                key=key,
                file_path=file_path,
                node_name=node_data["name"],
                node_type=node_data["type"],
                source_hash=node_data["source_hash"],
                file_hash=file_hash,
                signature=node_data.get("signature"),
                docstring=node_data.get("docstring"),
                decorators=node_data.get("decorators", []),
                line_count=node_data.get("line_count"),
                has_type_hints=node_data.get("has_type_hints", False),
                last_updated=now,
                update_source=source,
            )
            self.kv.set(state)

        # Update file index
        self.kv.set_file_index(FileIndex(
            file_path=file_path,
            file_hash=file_hash,
            node_count=len(nodes),
            last_scanned=now,
        ))

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Compute SHA256 hash of file contents."""
        try:
            content = path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except OSError:
            return ""
```

---

### Step 2.8: Implement HubClient

**File to update**: `remora/context/hub_client.py`

Replace the stub with actual client implementation:

```python
"""Hub client for Pull Hook integration.

This client connects to the Hub daemon and retrieves node context.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from remora.hub.models import NodeState


class HubClient:
    """Client for the Hub daemon."""

    def __init__(
        self,
        socket_path: Path = Path("/tmp/remora-hub.sock"),
        timeout: float = 1.0,
    ) -> None:
        self.socket_path = socket_path
        self.timeout = timeout
        self._available: bool | None = None

    async def get_context(self, node_ids: list[str]) -> dict[str, NodeState]:
        """Get context for nodes from Hub.

        Returns empty dict if Hub is not available.
        """
        if not await self._is_available():
            return {}

        try:
            response = await self._send_request({
                "type": "get_context",
                "nodes": node_ids,
            })

            nodes = response.get("nodes", {})
            return {
                k: NodeState.model_validate(v)
                for k, v in nodes.items()
            }
        except Exception:
            return {}

    async def health_check(self) -> bool:
        """Check if Hub is healthy."""
        try:
            response = await self._send_request({"type": "health"})
            return response.get("status") == "ok"
        except Exception:
            return False

    async def _is_available(self) -> bool:
        """Check if Hub socket exists and is responsive."""
        if self._available is not None:
            return self._available

        if not self.socket_path.exists():
            self._available = False
            return False

        self._available = await self.health_check()
        return self._available

    async def _send_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send request to Hub and get response."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(self.socket_path)),
            timeout=self.timeout,
        )

        try:
            writer.write(json.dumps(request).encode())
            await writer.drain()

            data = await asyncio.wait_for(
                reader.read(65536),
                timeout=self.timeout,
            )

            return json.loads(data.decode())
        finally:
            writer.close()
            await writer.wait_closed()


def get_hub_client() -> HubClient:
    """Get the Hub client instance."""
    return HubClient()
```

---

### Step 2.9: Wire Pull Hook

**File to update**: `remora/context/manager.py`

Update `pull_hub_context` to use the real client:

```python
async def pull_hub_context(self) -> None:
    """Pull fresh context from Hub.

    This is called at the start of each turn to inject
    external context into the Decision Packet.
    """
    from remora.context.hub_client import get_hub_client

    if self._hub_client is None:
        self._hub_client = get_hub_client()

    try:
        context = await self._hub_client.get_context([self.packet.node_id])
        if context:
            # Convert NodeState to dict for packet
            node_state = context.get(self.packet.node_id)
            if node_state:
                self.packet.hub_context = {
                    "signature": node_state.signature,
                    "docstring": node_state.docstring,
                    "related_tests": node_state.related_tests,
                    "complexity": node_state.complexity,
                }
                self.packet.hub_freshness = node_state.last_updated
    except Exception:
        # Graceful degradation - Hub is optional
        pass
```

---

## Migration Checklist

### Phase 1 Completion

- [ ] Core models created (`remora/context/models.py`)
- [ ] ContextManager implemented (`remora/context/manager.py`)
- [ ] Tool return contract defined (`remora/context/contracts.py`)
- [ ] Summarizer framework created (`remora/context/summarizers.py`)
- [ ] At least one tool updated to return Two-Track format
- [ ] Runner integrated with ContextManager
- [ ] Pull Hook stub in place
- [ ] All existing tests still pass
- [ ] New tests added for context management

### Phase 2 Completion

- [ ] Hub models created (`remora/hub/models.py`)
- [ ] NodeStateKV implemented (`remora/hub/storage.py`)
- [ ] Analysis scripts created (`agents/hub/tools/*.pym`)
- [ ] Rules engine implemented (`remora/hub/rules.py`)
- [ ] File watcher working (`remora/hub/watcher.py`)
- [ ] IPC server implemented (`remora/hub/server.py`)
- [ ] Hub daemon working (`remora/hub/daemon.py`)
- [ ] HubClient connecting to daemon
- [ ] Pull Hook returning real context
- [ ] End-to-end test: start Hub, run Remora, verify context

---

## Appendix: Library APIs

### fsdantic

Key classes for KV storage:

```python
from fsdantic import (
    KVManager,           # Low-level KV operations
    KVTransaction,       # Grouped operations
    TypedKVRepository,   # Type-safe model storage
)

# Using TypedKVRepository
repo = TypedKVRepository[NodeState](agent_fs, prefix="node:")
await repo.save("foo.py:bar", node_state)
state = await repo.load("foo.py:bar", NodeState)
all_states = await repo.list_all(NodeState)
```

### grail

Key functions for script execution:

```python
import grail

# Load and run a script
script = grail.load("path/to/script.pym", grail_dir=".grail")
check_result = script.check()  # Validate
result = await script.run(
    inputs={"file_path": "/path/to/file.py"},
    externals={"read_file": read_file_impl},
    limits=grail.DEFAULT,
)

# Limits presets
grail.STRICT      # 8MB memory, 500ms
grail.DEFAULT     # 16MB memory, 2s
grail.PERMISSIVE  # 64MB memory, 10s
```

### watchfiles

```python
import watchfiles

# Watch for changes
async for changes in watchfiles.awatch("/path/to/dir"):
    for change_type, path in changes:
        print(f"{change_type}: {path}")

# Change types
watchfiles.Change.added
watchfiles.Change.modified
watchfiles.Change.deleted
```

---

## End of Guide

This guide provides a complete roadmap for implementing the Two-Track Memory and Node State Hub concepts in Remora. Follow the steps in order, ensuring tests pass at each checkpoint before proceeding.

For questions or issues, refer to:
- `HUBTRACK_CONCEPT.md` - Detailed concept analysis
- `TWO_TRACK_MEMORY_CONCEPT_v2.md` - Original Two-Track design
- `HUB_CONCEPT_v2.md` - Original Hub design
