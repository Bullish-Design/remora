# Implementation Guide: Step 6 — Context Builder (Two-Track Memory)

## Overview

This step implements **Idea 6: Simplify the Context System** from the design document. It transforms the 5-file context package into a single, elegant EventBus subscriber that implements the Two-Track Memory concept.

## Contract Touchpoints
- Consumes `ToolResultEvent` and `AgentCompleteEvent` emitted by EventBus.
- Produces short-track summaries and optional long-track store lookups for prompts.

## Done Criteria
- [ ] `ContextBuilder.handle()` updates short-track and knowledge maps from events.
- [ ] `build_context_for()` combines recent actions with optional indexer context.
- [ ] Unit tests cover rolling window behavior and tool-error summaries.

## Prerequisites

Before starting this step, complete:
- **Step 1: Unified Event System** — `src/remora/events.py` must exist with `RemoraEvent`, `ToolResultEvent`, `AgentCompleteEvent`
- **Step 2: Discovery Consolidation** — `src/remora/discovery.py` must exist with `CSTNode`

---

## What This Step Does

### Current State (5 Files)

```
src/remora/context/
├── __init__.py         # Re-exports ContextManager, DecisionPacket, etc.
├── manager.py          # ContextManager with apply_event() switch statement (221 lines)
├── models.py          # DecisionPacket, RecentAction, KnowledgeEntry (148 lines)
├── contracts.py        # ToolResult schema (conflicts with structured-agents)
├── hub_client.py      # "Lazy Daemon" pattern for Hub integration
└── summarizers.py     # Text summarization utilities
```

### Target State (1 File)

```
src/remora/
└── context.py          # Single ContextBuilder class (~150 lines)
```

### Key Changes

| Old | New |
|-----|-----|
| `ContextManager` | `ContextBuilder` |
| `apply_event()` with dict switch | `handle()` with pattern matching on typed events |
| `contracts.py` ToolResult | Use structured-agents' `ToolResultEvent` directly |
| `hub_client.py` Lazy Daemon | Direct store read via optional `store` parameter |
| `summarizers.py` | Absorbed as helper functions |

---

## Implementation Steps

### Step 6.1: Create `src/remora/context.py`

Create the new context module with the following implementation:

```python
"""Context Builder - Two-Track Memory implementation.

This module provides bounded context for agents by:
- Short Track: Rolling window of recent actions (deque with maxlen)
- Long Track: Full event stream via EventBus subscription

Usage:
    builder = ContextBuilder(window_size=20, store=node_store)
    
    # Subscribe to events
    event_bus.subscribe(ToolResultEvent, builder.handle)
    event_bus.subscribe(AgentCompleteEvent, builder.handle)
    
    # Build context for a node
    context = builder.build_context_for(node)
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.discovery import CSTNode
    from remora.events import AgentCompleteEvent, RemoraEvent, ToolResultEvent


@dataclass
class RecentAction:
    """A recent action for the Short Track.
    
    Represents a distilled summary of a tool execution,
    not the raw result.
    """
    tool: str
    outcome: str  # "success", "error", "partial"
    summary: str
    timestamp: float = field(default_factory=time.time)


def _summarize_output(output: Any, max_length: int = 100) -> str:
    """Truncate and summarize tool output for the Short Track.
    
    Args:
        output: The raw tool output
        max_length: Maximum characters to include
        
    Returns:
        A short summary string
    """
    if output is None:
        return "no output"
    
    if isinstance(output, dict):
        # Extract meaningful keys from dict output
        keys = list(output.keys())[:3]
        return f"dict({', '.join(keys)})"
    
    if isinstance(output, list):
        return f"list[{len(output)} items]"
    
    s = str(output)
    if len(s) > max_length:
        return s[:max_length - 3] + "..."
    return s


def _extract_knowledge(result: dict[str, Any]) -> str:
    """Extract key information from agent result for knowledge accumulation.
    
    Args:
        result: The RunResult from AgentCompleteEvent
        
    Returns:
        A knowledge string summarizing the result
    """
    if not result:
        return "no result"
    
    # Look for common result fields
    if "summary" in result:
        return str(result["summary"])
    
    if "message" in result:
        msg = result["message"]
        if isinstance(msg, dict) and "content" in msg:
            content = msg["content"]
            if len(content) > 100:
                return content[:97] + "..."
            return content
    
    # Fallback: extract keys
    keys = [k for k in result.keys() if not k.startswith("_")]
    if keys:
        return f"fields: {', '.join(keys[:5])}"
    
    return "completed"


class ContextBuilder:
    """Builds bounded context from the event stream.
    
    Implements the Two-Track Memory concept:
    - Short Track: Rolling window of recent actions (via deque with maxlen)
    - Long Track: Full event stream (via EventBus subscription)
    
    This replaces the old ContextManager which used a large switch statement
    on string-based event types.
    
    Usage:
        builder = ContextBuilder(window_size=20)
        
        # Subscribe to events
        event_bus.subscribe(ToolResultEvent, builder.handle)
        event_bus.subscribe(AgentCompleteEvent, builder.handle)
        
        # Get context for agent prompts
        context_section = builder.build_prompt_section()
        full_context = builder.build_context_for(node)
    """
    
    def __init__(
        self,
        window_size: int = 20,
        store: "NodeStateStore | None" = None,
    ):
        """Initialize the ContextBuilder.
        
        Args:
            window_size: Maximum number of recent actions to track (Short Track)
            store: Optional NodeStateStore for Hub index integration
        """
        self._recent: deque[RecentAction] = deque(maxlen=window_size)
        self._knowledge: dict[str, str] = {}
        self._store = store
    
    async def handle(self, event: RemoraEvent) -> None:
        """EventBus subscriber - updates context from events.
        
        Pattern matches on typed events (not string-based).
        This is the core of the simplified context system.
        
        Args:
            event: Any RemoraEvent from the EventBus
        """
        # Use pattern matching on event types
        match event:
            case ToolResultEvent(name=name, output=output, is_error=is_error):
                self._recent.append(RecentAction(
                    tool=name or "unknown",
                    outcome="error" if is_error else "success",
                    summary=_summarize_output(output),
                ))
            
            case AgentCompleteEvent(agent_id=aid, result=result):
                if aid and result:
                    self._knowledge[aid] = _extract_knowledge(result)
            
            case _:
                # Ignore other events - they don't affect context
                pass
    
    def build_prompt_section(self) -> str:
        """Render current Short Track as a prompt section.
        
        Returns:
            Formatted string with recent actions and knowledge
        """
        lines = ["## Recent Actions"]
        
        # Show last 10 actions (most recent at bottom for readability)
        recent_list = list(self._recent)
        for action in recent_list[-10:]:
            status = "✓" if action.outcome == "success" else "✗"
            lines.append(f"- {status} {action.tool}: {action.summary}")
        
        if self._knowledge:
            lines.append("\n## Knowledge")
            for agent_id, knowledge in self._knowledge.items():
                lines.append(f"- {agent_id}: {knowledge}")
        
        return "\n".join(lines)
    
    def build_context_for(self, node: CSTNode) -> str:
        """Build full context: Hub index data + Short Track.
        
        This combines:
        1. Related code from the indexer store (Long Track integration)
        2. Rolling recent actions (Short Track)
        
        Args:
            node: The CSTNode to build context for
            
        Returns:
            Complete context string for the agent prompt
        """
        sections = []
        
        # Pull related node data from indexer store (if available)
        if self._store:
            try:
                related = self._store.get_related(node.node_id)
                if related:
                    sections.append("## Related Code")
                    for rel in related[:5]:  # Limit to 5 related nodes
                        sections.append(f"- {rel}")
            except Exception:
                # Store not available or query failed - skip silently
                pass
        
        # Add the Short Track
        sections.append(self.build_prompt_section())
        
        return "\n".join(sections)
    
    def get_recent_actions(self) -> list[RecentAction]:
        """Get all recent actions (Short Track).
        
        Returns:
            List of RecentAction objects, newest last
        """
        return list(self._recent)
    
    def get_knowledge(self) -> dict[str, str]:
        """Get accumulated knowledge (Long Track summary).
        
        Returns:
            Dict mapping agent_id to knowledge string
        """
        return self._knowledge.copy()
    
    def clear(self) -> None:
        """Clear all context. Useful for new sessions."""
        self._recent.clear()
        self._knowledge.clear()


# For backwards compatibility
__all__ = [
    "ContextBuilder",
    "RecentAction",
]
```

### Step 6.2: Update Exports in `src/remora/__init__.py`

Read the current `__init__.py` and add the new exports:

```python
# Add to existing exports
from remora.context import ContextBuilder, RecentAction

# Update __all__
__all__ = [
    # ... existing exports ...
    # Context
    "ContextBuilder",
    "RecentAction",
]
```

### Step 6.3: Delete the Old Context Directory

After confirming no other imports exist, delete the context directory:

```bash
rm -rf src/remora/context/
```

**Important:** Before deleting, verify no other code imports from `remora.context`:

```bash
grep -r "from remora.context import" src/ --include="*.py"
grep -r "from remora.context." src/ --include="*.py"
```

---

## Writing Tests

Create `tests/test_context.py`:

```python
"""Tests for ContextBuilder (Two-Track Memory)."""

import pytest

from remora.context import ContextBuilder, RecentAction
from remora.events import ToolResultEvent, AgentCompleteEvent


class TestRecentAction:
    """Test RecentAction dataclass."""
    
    def test_creation(self):
        action = RecentAction(
            tool="read_file",
            outcome="success",
            summary="Read 50 lines"
        )
        assert action.tool == "read_file"
        assert action.outcome == "success"
        assert action.timestamp > 0
    
    def test_outcome_values(self):
        """Outcome must be success, error, or partial."""
        success = RecentAction(tool="t", outcome="success", summary="s")
        error = RecentAction(tool="t", outcome="error", summary="s")
        partial = RecentAction(tool="t", outcome="partial", summary="s")
        
        assert success.outcome == "success"
        assert error.outcome == "error"
        assert partial.outcome == "partial"


class TestContextBuilder:
    """Test ContextBuilder functionality."""
    
    @pytest.fixture
    def builder(self):
        """Fresh ContextBuilder for each test."""
        return ContextBuilder(window_size=5)
    
    @pytest.mark.asyncio
    async def test_handle_tool_result_success(self, builder):
        """Tool success adds to recent actions."""
        event = ToolResultEvent(
            name="read_file",
            call_id="call-1",
            output="file content here",
            is_error=False,
        )
        
        await builder.handle(event)
        
        actions = builder.get_recent_actions()
        assert len(actions) == 1
        assert actions[0].tool == "read_file"
        assert actions[0].outcome == "success"
    
    @pytest.mark.asyncio
    async def test_handle_tool_result_error(self, builder):
        """Tool error adds to recent actions with error outcome."""
        event = ToolResultEvent(
            name="write_file",
            call_id="call-2",
            output="Permission denied",
            is_error=True,
        )
        
        await builder.handle(event)
        
        actions = builder.get_recent_actions()
        assert len(actions) == 1
        assert actions[0].outcome == "error"
    
    @pytest.mark.asyncio
    async def test_handle_agent_complete(self, builder):
        """Agent completion adds to knowledge."""
        event = AgentCompleteEvent(
            graph_id="graph-1",
            agent_id="agent-lint-1",
            result={"summary": "Fixed 3 lint errors"},
        )
        
        await builder.handle(event)
        
        knowledge = builder.get_knowledge()
        assert "agent-lint-1" in knowledge
        assert knowledge["agent-lint-1"] == "Fixed 3 lint errors"
    
    @pytest.mark.asyncio
    async def test_rolling_window(self, builder):
        """Window size limits recent actions."""
        # Add more actions than window_size
        for i in range(10):
            event = ToolResultEvent(
                name=f"tool-{i}",
                call_id=f"call-{i}",
                output=f"output-{i}",
                is_error=False,
            )
            await builder.handle(event)
        
        actions = builder.get_recent_actions()
        # Should be limited to window_size (5)
        assert len(actions) == 5
        # Oldest should have been dropped
        assert actions[0].tool == "tool-5"
        assert actions[-1].tool == "tool-9"
    
    def test_build_prompt_section(self, builder):
        """Prompt section formats recent actions correctly."""
        # Add some actions directly
        builder._recent.append(RecentAction(
            tool="read_file",
            outcome="success",
            summary="Read main.py"
        ))
        builder._recent.append(RecentAction(
            tool="lint",
            outcome="error",
            summary="3 errors found"
        ))
        
        section = builder.build_prompt_section()
        
        assert "## Recent Actions" in section
        assert "✓ read_file:" in section
        assert "✗ lint:" in section
    
    def test_build_prompt_section_with_knowledge(self, builder):
        """Prompt section includes knowledge when present."""
        builder._knowledge["agent-1"] = "Fixed bugs"
        builder._knowledge["agent-2"] = "Added tests"
        
        section = builder.build_prompt_section()
        
        assert "## Knowledge" in section
        assert "agent-1: Fixed bugs" in section
        assert "agent-2: Added tests" in section
    
    def test_clear(self, builder):
        """Clear removes all context."""
        builder._recent.append(RecentAction(
            tool="test", outcome="success", summary="done"
        ))
        builder._knowledge["agent-1"] = "knowledge"
        
        builder.clear()
        
        assert len(builder.get_recent_actions()) == 0
        assert len(builder.get_knowledge()) == 0
    
    def test_window_size_default(self):
        """Default window size is 20."""
        builder = ContextBuilder()
        assert builder._recent.maxlen == 20
    
    def test_window_size_custom(self):
        """Custom window size works."""
        builder = ContextBuilder(window_size=50)
        assert builder._recent.maxlen == 50


class TestHelperFunctions:
    """Test helper functions."""
    
    def test_summarize_output_none(self):
        """None output handled correctly."""
        from remora.context import _summarize_output
        result = _summarize_output(None)
        assert result == "no output"
    
    def test_summarize_output_dict(self):
        """Dict output shows keys."""
        from remora.context import _summarize_output
        result = _summarize_output({"foo": 1, "bar": 2})
        assert "foo" in result
        assert "bar" in result
    
    def test_summarize_output_list(self):
        """List output shows length."""
        from remora.context import _summarize_output
        result = _summarize_output([1, 2, 3])
        assert "3 items" in result
    
    def test_summarize_output_truncates(self):
        """Long strings are truncated."""
        from remora.context import _summarize_output
        long_string = "x" * 200
        result = _summarize_output(long_string, max_length=100)
        assert len(result) == 100
        assert result.endswith("...")
    
    def test_extract_knowledge_summary(self):
        """Extracts from summary field."""
        from remora.context import _extract_knowledge
        result = _extract_knowledge({"summary": "Fixed 5 bugs"})
        assert result == "Fixed 5 bugs"
    
    def test_extract_knowledge_message(self):
        """Extracts from message.content field."""
        from remora.context import _extract_knowledge
        result = _extract_knowledge({
            "message": {"content": "Hello world"}
        })
        assert result == "Hello world"
    
    def test_extract_knowledge_fallback(self):
        """Falls back to field list."""
        from remora.context import _extract_knowledge
        result = _extract_knowledge({"foo": 1, "bar": 2})
        assert "foo" in result
        assert "bar" in result
    
    def test_extract_knowledge_empty(self):
        """Empty result handled."""
        from remora.context import _extract_knowledge
        result = _extract_knowledge({})
        assert result == "completed"
```

---

## Verification

### Basic Import Test
```bash
cd /home/andrew/Documents/Projects/remora
python -c "from remora import ContextBuilder, RecentAction; print('Import OK')"
```

### Run Tests
```bash
cd /home/andrew/Documents/Projects/remora
python -m pytest tests/test_context.py -v
```

### Verify No Broken Imports
```bash
grep -r "from remora.context import" src/ --include="*.py"
grep -r "remora.context\." src/ --include="*.py"
```

---

## Common Pitfalls

1. **Pattern matching import error** — Use `match` statement requires Python 3.10+. Ensure project targets 3.10+.

2. **Store type hint** — Use string type hint `"NodeStateStore | None"` to avoid circular import. The actual type will be from the indexer module.

3. **deque maxlen** — Must set `maxlen` at creation: `deque(maxlen=window_size)`. Setting it later doesn't work.

4. **Event field access** — Structured-agents events use `name` not `tool_name`. Match your pattern matching to actual event fields.

5. **Optional store** — The `_store` is optional. Always check `if self._store:` before using, and wrap in try/except.

6. **Ignoring other events** — The catch-all `case _:` is intentional. Unknown event types should not raise errors.

---

## Files Created/Modified Summary

| File | Action | Description |
|------|--------|-------------|
| `src/remora/context.py` | CREATE | ~150 lines - ContextBuilder + RecentAction |
| `src/remora/__init__.py` | MODIFY | Add ContextBuilder, RecentAction exports |
| `tests/test_context.py` | CREATE | ~180 lines - Comprehensive tests |
| `src/remora/context/` | DELETE | Old 5-file package (after verification) |

---

## What This Preserves

- **Two-Track Memory concept** — Short Track (rolling window) + Long Track (event stream)
- **DecisionPacket behavior** — Bounded context for agent prompts
- **Hub index integration** — Via optional store parameter
- **Knowledge accumulation** — Agent results stored in `_knowledge` dict

---

## What This Eliminates

- `context/manager.py` — Switch statement replaced with pattern matching
- `context/contracts.py` — Conflicting ToolResult schema (use structured-agents')
- `context/hub_client.py` — Lazy Daemon pattern (direct store read)
- `context/summarizers.py` — Absorbed as helper functions
- **5 files → 1 file**

---

## Next Step

After this step is complete and verified, proceed to **Step 7: Executor Implementation** (Idea 4) which separates topology from execution and integrates with `Agent.from_bundle()`.
