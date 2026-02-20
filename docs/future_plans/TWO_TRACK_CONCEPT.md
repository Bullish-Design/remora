# Concept Review: Two-Track Memory
## Executive Summary

After studying both concept documents and the current Remora codebase, this review provides a detailed analysis of how these concepts align with the existing architecture and what gaps need to be addressed.

**Key Finding**: The Two-Track Memory concept is well-aligned with Remora's current architecture - the "Long Track" essentially already exists via `JsonlEventEmitter`. The critical missing piece is the **Short Track (Decision Packet)** and the projection logic that distills events into clean, structured context for FunctionGemma.

---

## Part 1: Two-Track Memory Concept Review

### 1.1 What Exists Today

| Component | Current State | Location |
|-----------|--------------|----------|
| **Event Emission** | Complete | `remora/events.py` - `EventEmitter` protocol, `JsonlEventEmitter` |
| **Event Types** | Comprehensive | `EventName` enum: MODEL_REQUEST, MODEL_RESPONSE, TOOL_CALL, TOOL_RESULT, SUBMIT_RESULT, AGENT_ERROR |
| **Event Logging** | Active | Writes to `~/.cache/remora/events.jsonl` |
| **Conversation Logging** | Active | `LlmConversationLogger` creates human-readable transcripts |
| **Message History** | In-memory list | `FunctionGemmaRunner.messages` - full conversation sent to model |

### 1.2 Gap Analysis

| Two-Track Component | Current State | Gap |
|---------------------|--------------|-----|
| **Long Track (Event Stream)** | **EXISTS** | Already implemented via `JsonlEventEmitter`. Events are immutable, timestamped, and contain full payloads. |
| **Short Track (Decision Packet)** | **MISSING** | No `DecisionPacket` class exists. The model receives raw message history, not a distilled projection. |
| **Summary Delta** | **MISSING** | Tools return raw results. No mechanism to generate `summary_delta` alongside `raw_output`. |
| **Context Manager** | **MISSING** | No component that projects events → Decision Packet. The `LlmConversationLogger` does event → text, but not event → structured JSON. |
| **Hub Pull Hook** | **MISSING** | No integration point for external context injection. |

### 1.3 Critical Observations

**FunctionGemma's Needs**: The model requires **clean context**, not compressed context. This means:
- Tool results must be distilled to structured summaries
- The Decision Packet should be a well-defined JSON schema, not free-form text
- Raw outputs (full file contents, stack traces) stay in Long Track only

**Architecture Alignment**: The event sourcing pattern in the concept aligns well with Remora's existing `emit()` pattern. The change is:
- **Before**: Event → Log (fire and forget)
- **After**: Event → Log + Apply to DecisionPacket

### 1.4 Decision Packet Deep Dive

#### 1.4.1 Full Schema Design

```python
from pydantic import BaseModel, Field
from typing import Any, Literal
from datetime import datetime

class RecentAction(BaseModel):
    """A single action in the rolling history."""
    turn: int                          # Which turn this happened
    tool: str                          # Tool name
    summary: str                       # Distilled summary
    outcome: Literal["success", "error", "partial"]

class KnowledgeEntry(BaseModel):
    """A piece of working knowledge."""
    key: str                           # e.g., "lint_errors", "test_results"
    value: Any                         # Structured data
    source_turn: int                   # When this was learned
    supersedes: str | None = None      # Key this replaces (for updates)

class DecisionPacket(BaseModel):
    """The Short Track - what the model sees."""

    # === Identity ===
    agent_id: str
    turn: int                          # Current turn number

    # === Goal Context ===
    goal: str                          # "Fix lint errors in foo.py"
    operation: str                     # "lint", "test", "docstring"
    node_id: str                       # Current target
    node_summary: str                  # Brief description of the code

    # === Recent Actions (Rolling Window) ===
    recent_actions: list[RecentAction] = Field(default_factory=list, max_length=10)

    # === Working Knowledge (Structured) ===
    knowledge: dict[str, KnowledgeEntry] = Field(default_factory=dict)

    # === Error State ===
    last_error: str | None = None      # Most recent error summary
    error_count: int = 0               # Total errors this session

    # === Hub Context (Injected) ===
    hub_context: dict[str, Any] | None = None
    hub_freshness: datetime | None = None

    # === Metadata ===
    packet_version: str = "1.0"
```

#### 1.4.2 Projection Logic

The `ContextManager` applies events to maintain the Decision Packet. Here's the projection logic:

```python
class ContextManager:
    """Projects events onto the Decision Packet."""

    def __init__(self, initial_context: dict[str, Any]):
        self.packet = DecisionPacket(
            agent_id=initial_context["agent_id"],
            turn=0,
            goal=initial_context["goal"],
            operation=initial_context["operation"],
            node_id=initial_context["node_id"],
            node_summary=initial_context.get("node_summary", ""),
        )
        self._summarizers: dict[str, Summarizer] = {}

    def apply_event(self, event: dict[str, Any]) -> None:
        """Apply an event to update the Decision Packet."""
        event_type = event["type"]

        if event_type == "tool_result":
            self._apply_tool_result(event)
        elif event_type == "model_response":
            self._apply_model_response(event)
        elif event_type == "turn_start":
            self.packet.turn = event["turn"]
        elif event_type == "hub_update":
            self._apply_hub_context(event)

    def _apply_tool_result(self, event: dict[str, Any]) -> None:
        """Handle TOOL_RESULT events."""
        tool_name = event["tool"]
        raw_result = event["data"]["raw_output"]

        # 1. Get summary (tool-provided or generated)
        if "summary" in event["data"]:
            summary = event["data"]["summary"]
        else:
            summary = self._generate_summary(tool_name, raw_result)

        # 2. Add to recent actions (with rolling window)
        action = RecentAction(
            turn=self.packet.turn,
            tool=tool_name,
            summary=summary,
            outcome=self._infer_outcome(raw_result),
        )
        self.packet.recent_actions.append(action)
        if len(self.packet.recent_actions) > 10:
            self.packet.recent_actions.pop(0)

        # 3. Update knowledge (tool-specific logic)
        knowledge_delta = event["data"].get("knowledge_delta", {})
        for key, value in knowledge_delta.items():
            self.packet.knowledge[key] = KnowledgeEntry(
                key=key,
                value=value,
                source_turn=self.packet.turn,
            )

        # 4. Update error state
        if "error" in event["data"]:
            self.packet.last_error = event["data"]["error"]
            self.packet.error_count += 1
        else:
            self.packet.last_error = None

    def _generate_summary(self, tool_name: str, raw_result: Any) -> str:
        """Generate summary using pluggable summarizer."""
        if tool_name in self._summarizers:
            return self._summarizers[tool_name].summarize(raw_result)
        return f"Executed {tool_name}"  # Fallback

    def register_summarizer(self, tool_name: str, summarizer: "Summarizer") -> None:
        """Register a custom summarizer for a specific tool."""
        self._summarizers[tool_name] = summarizer
```

#### 1.4.3 Pluggable Summarizer Architecture

Since you want tool-side summaries as primary with fallback capability:

```python
from abc import ABC, abstractmethod

class Summarizer(ABC):
    """Base class for tool result summarizers."""

    @abstractmethod
    def summarize(self, raw_result: Any) -> str:
        """Generate a summary from raw tool output."""
        ...

    @abstractmethod
    def extract_knowledge(self, raw_result: Any) -> dict[str, Any]:
        """Extract knowledge entries from raw output."""
        ...


class LinterSummarizer(Summarizer):
    """Summarizer for linter tool results."""

    def summarize(self, raw_result: dict[str, Any]) -> str:
        errors = raw_result.get("errors", [])
        fixed = raw_result.get("fixed", 0)
        if fixed > 0:
            return f"Fixed {fixed} lint errors, {len(errors)} remaining"
        return f"Found {len(errors)} lint errors"

    def extract_knowledge(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "lint_errors_remaining": len(raw_result.get("errors", [])),
            "lint_errors_fixed": raw_result.get("fixed", 0),
        }


class ToolSidePassthrough(Summarizer):
    """Passes through tool-provided summaries (primary path)."""

    def summarize(self, raw_result: dict[str, Any]) -> str:
        return raw_result.get("summary", f"Tool completed")

    def extract_knowledge(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result.get("knowledge_delta", {})
```

#### 1.4.4 Tool Return Contract

Tools should return this structure:

```python
# Tool return format
{
    "result": { ... },              # Full raw output (Long Track)
    "summary": "Fixed 3 errors",    # Short description (Short Track)
    "knowledge_delta": {            # Updates to working knowledge
        "errors_remaining": 2,
        "files_modified": ["foo.py"]
    },
    "outcome": "success"            # success | error | partial
}
```

If a tool doesn't provide `summary`, the registered `Summarizer` generates one.

#### 1.4.5 Prompt Injection

The Decision Packet is injected into the system prompt:

```python
def build_system_prompt(packet: DecisionPacket) -> str:
    """Build the system prompt with Decision Packet."""
    return f"""You are a code maintenance agent.

## Current State
- Goal: {packet.goal}
- Target: {packet.node_id}
- Turn: {packet.turn}

## Recent Actions
{format_recent_actions(packet.recent_actions)}

## Working Knowledge
{format_knowledge(packet.knowledge)}

{format_error_state(packet.last_error) if packet.last_error else ""}

## Available Tools
...
"""
```

### 1.5 Tool Result Distillation Strategy

The key challenge is: **how do tools produce both raw output and summary?**

**Option A: Tool-side summaries** (Recommended)
- Each `.pym` script returns `{"result": ..., "summary": "..."}`
- Pros: Tool authors control summary quality
- Cons: Requires updating all existing tools

**Option B: Runner-side extraction**
- Runner applies heuristics to extract summaries from results
- Pros: No tool changes
- Cons: Fragile, tool-specific logic in runner

**Option C: Hybrid**
- Tools return structured results with known fields
- A `Summarizer` component extracts summaries based on result schema
- Pros: Separation of concerns
- Cons: Additional abstraction layer

### 1.6 Integration Points

```
                    ┌─────────────────────────────────────┐
                    │         FunctionGemmaRunner         │
                    │                                     │
                    │  messages[] ──────► KEEP (debug)    │
                    │                                     │
                    │  ┌─────────────────────────────┐   │
                    │  │    ContextManager (NEW)     │   │
                    │  │                             │   │
                    │  │  DecisionPacket ◄── Event   │   │
                    │  │        │                    │   │
                    │  │        └─► Prompt Builder   │   │
                    │  └─────────────────────────────┘   │
                    └─────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
            JsonlEventEmitter               Hub Pull Hook
            (Long Track - exists)           (Future)
```

---

## Part 2: Design Decisions (Confirmed)

Based on our discussion, the following decisions are locked in:

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Message History** | Keep both `messages[]` and `DecisionPacket` | Safer transition; messages for debugging, DecisionPacket for model |
| **Summary Strategy** | Tool-side primary, pluggable summarizer fallback | Tools control quality, but architecture allows overrides |

### 2.1 Dual-Track Architecture (messages[] + DecisionPacket)

Since we're keeping both, here's how they coexist:

```python
class FunctionGemmaRunner:
    def __init__(self, ...):
        # Long Track (for debugging, existing behavior)
        self.messages: list[ChatCompletionMessageParam] = []

        # Short Track (for model, new)
        self.context_manager = ContextManager(initial_context)

    async def run(self) -> AgentResult:
        while self.turn_count < self.max_turns:
            # Build prompt from DecisionPacket (not messages)
            prompt_context = self.context_manager.get_prompt_context()
            system_prompt = self._build_system_prompt(prompt_context)

            # Call model with clean context
            response = await self._call_model(system_prompt)

            # Update BOTH tracks
            self.messages.append(...)  # Long Track (full message)
            self.context_manager.apply_event(event)  # Short Track (distilled)

            # Emit to event stream (for JSONL logging)
            self._emit_event(event)
```

**Key insight**: The model sees `DecisionPacket`, but developers can inspect `messages[]` during debugging without reconstructing from the event stream.

### 4.2 Remaining Open Questions

1. **Summary Granularity**: How detailed should tool summaries be?
   - Goal: 1-2 sentences max, focus on outcome not process
   - Example: "Fixed 3 lint errors" not "Ran ruff with --fix flag on lines 12, 45, 67..."

2. **Incremental Adoption**: Can we ship Two-Track incrementally?
   - Proposal: Yes, start with `submit_result` tool, then expand
   - Tools without summaries use fallback summarizer

3. **Testing Strategy**: How do we test projection logic?
   - Proposal: Snapshot tests with known event sequences
   - Golden files: `events.jsonl` → expected `DecisionPacket`
