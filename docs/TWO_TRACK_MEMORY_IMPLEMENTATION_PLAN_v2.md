# Two-Track Memory Implementation Plan (v2)

**Goal**: Refactor the Remora Runner to use an "Event Sourcing" architecture.
**Audience**: Junior Developers & Contributors.
**Prerequisites**: Familiarity with `remora/runner.py` and `remora/events.py`.

---

## Overview
We are moving away from "chat history" as the primary source of truth. Instead, we will:
1.  Define a structured **Event Schem**.
2.  Define a structured **Decision Packet Schema**.
3.  Update **Grail Tools** to return both raw data and summaries.
4.  Update the **Runner** to update the Packet based on Events.

---

## Phase 1: The Schemas (Modeling the Data)
*Goal: Define the "shape" of our memory before writing logic.*

**1. Create `remora/memory/schemas.py`**
We need two main Pydantic models.

**A. `DecisionPacket`** (The Short Track / Model Input)
This is what the model sees.
```python
class DecisionPacket(BaseModel):
    # What are we doing?
    goal: str
    
    # What just happened? (Keep this brief! e.g., last 5 items)
    recent_history: list[str] = Field(default_factory=list)
    
    # What do we know? (Key-Value pairs of file summaries, etc.)
    knowledge: dict[str, str] = Field(default_factory=dict)
    
    # Useful for debugging model confusion
    last_error: str | None = None

    # Track which nodes have fresh Hub context
    hub_context_freshness: dict[str, float] = Field(default_factory=dict)
```

**B. `MemoryEvent`** (The Long Track / Log Entry)
This extends our existing event system.
```python
class PacketDelta(BaseModel):
    """How an event changes the memory."""
    add_history: str | None = None
    update_knowledge: dict[str, str] | None = None
    set_error: str | None = None

class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_name: str
    
    # Long Track: The full, raw truth
    raw_output: str | dict
    
    # Short Track: The instruction to update memory
    delta: PacketDelta
```

---

## Phase 2: The Context Manager (The Logic)
*Goal: Write the logic that updates the state.*

**1. Create `remora/memory/context.py`**
Create a class `ContextManager` that holds the `DecisionPacket`.

```python
class ContextManager:
    def __init__(self, initial_goal: str):
        self.packet = DecisionPacket(goal=initial_goal)
        
    def apply_event(self, event: ToolResultEvent):
        """Update the packet based on the event delta."""
        delta = event.delta
        
        # 1. Update History
        if delta.add_history:
            self.packet.recent_history.append(delta.add_history)
            # Keep history short (e.g., max 10 items)
            if len(self.packet.recent_history) > 10:
                self.packet.recent_history.pop(0)
                
        # 2. Update Knowledge
        if delta.update_knowledge:
            self.packet.knowledge.update(delta.update_knowledge)
            
        # 3. Update Error
        if delta.set_error:
            self.packet.last_error = delta.set_error

    def run_middleware(self, hooks: list[Callable]):
        """Run external hooks (like Hub) to enrich the packet."""
        for hook in hooks:
            hook(self.packet)
```

---

## Phase 3: Grail Integration (The Tools)
*Goal: Teach tools to summarize themselves.*

**1. Update `GrailExecutor`** in `remora/runner.py`
Currently, `_dispatch_tool_grail` just returns the string result.
We need it to return a `(raw_output, delta)` tuple.

**Mechanism:**
-   If the tool returns a generic dictionary, use a **Default Summarizer**:
    -   `raw_output` = The dictionary.
    -   `delta` = `add_history="Tool X returned data."`
-   Ideally, user tools return a special structure (future work), but for now, we can infer the delta or allow the tool to return a `_summary` field in its result dict.

*Junior Dev Note: Start by implementing a "Default Summarizer" in Python that takes any tool output and creates a safe, generic PacketDelta.*

---

## Phase 4: The Runner Loop (Putting it together)
*Goal: Refactor the main loop in `remora/runner.py`.*

**Current Loop:**
1.  Append message to chat history.
2.  Call model with entire chat history.

**New Loop:**
1.  Initialize `ContextManager`.
2.  **Start Turn:**
    -   Generate Prompt from `ContextManager.packet`.
    -   Call Model.
3.  **Tool Execution:**
    -   Execute Tool -> Get `raw_output` and `delta`.
    -   Create `ToolResultEvent(raw_output=..., delta=...)`.
    -   **Emit Event** (logs to file).
    -   **Apply Event** to `ContextManager` (updates packet).
4.  **Repeat.**

---

## Phase 5: Storage (The File System)
*Goal: Ensure the Long Track is saved.*

**1. Update `remora/events.py`**
Ensure that the `EventEmitter` writes these structured events to a persistent file.
-   Location: `.agentfs/traces/{agent_id}.jsonl`
-   Format: JSON Lines (one event object per line).

This serves as our "Long Track" database. We don't need a separate SQL database or KV store yet. A simple append-only JSONL file is perfect for debugging and auditing.

---

## Phase 6: Hub Integration (The Middleware)
*Goal: Connect the Context Manager to the Hub.*

**1. Define Middleware Interface**
- `ContextManager.run_middleware(packet)` allows external systems to modify the packet in-place before the prompt is generated.

**2. Implement Hub Hook**
- `remora.hub.client.refresh_context(packet)`
- Checks `packet.recent_history` for node IDs.
- Fetches `NodeState` from Hub KV.
- Updates `packet.knowledge` with summaries/signatures.

---

## Checklist for Implementation

- [ ] **Step 1**: Define `DecisionPacket` and `PacketDelta` schemas.
- [ ] **Step 2**: Implement `ContextManager` with `apply_event` logic.
- [ ] **Step 3**: Modify `GrailExecutor` to produce `PacketDelta` (even if generic).
- [ ] **Step 4**: Rewrite `FunctionGemmaRunner.run()` to use the Context/Event loop instead of the Message History loop.
- [ ] **Step 5**: Verify that `.agentfs/traces/` contains the full raw outputs.
- [ ] **Step 6**: Verify that the Model only sees the `DecisionPacket` JSON.
