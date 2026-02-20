# TwoTrack Refactoring Guide

> **Version**: 1.0
> **Target**: Remora Library
> **Phases**: Two-Track Memory (Phase 1) 

This guide provides step-by-step instructions for implementing the Two-Track Memory concept in Remora. It is designed to be followed by developers who are new to the codebase.

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
3. [Migration Checklist](#migration-checklist)
4. [Appendix: Library APIs](#appendix-library-apis)

---

## Prerequisites

### Required Knowledge

- Python 3.11+ (async/await, type hints)
- Pydantic v2.10+ (BaseModel, Field, validation)
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

This guide provides a complete roadmap for implementing the Two-Track Memory concept in Remora. Follow the steps in order, ensuring tests pass at each checkpoint before proceeding.

