# Remora Test Suite Refactoring Guide

## 1. Testing Philosophy & Overall Strategy

The Remora library has undergone a ground-up refactor, transitioning from a batch graph-execution model to a **reactive, subscription-driven Agent Swarm**. Because the fundamental mental model has changed, our testing approach must also change.

### The New Rules of Testing Remora
1. **Actual Coverage, Not Just Mocks:** We are moving away from heavily mocking our core stores (`EventStore`, `SwarmState`, `SubscriptionRegistry`). The new system's complexity lies in how these components interact. Mocking them hides race conditions and database locks.
2. **Integration over Unit Tests:** The most valuable tests will spin up a real `EventStore`, a real `SubscriptionRegistry`, and a real `AgentRunner` working together over temporary SQLite/KV database files.
3. **Example Data is King:** Do not use `event_1`, `event_2` abstract objects. Use real AST node metadata, real file paths, and realistic `RemoraEvent` subclasses (like `ContentChangedEvent` or `AgentMessageEvent`).

---

## 2. Infrastructure Setup (Junior Developer Guide)

Before writing tests for specific components, we need a robust fixture system in `tests/conftest.py`.

### Step 2.1: The Real-World Fixtures
Create realistic project structures in your temp directory for tests to operate on:
```python
@pytest.fixture
def sample_workspace(tmp_path: Path) -> Path:
    # Create a real mini-codebase
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def hello():\n    pass")
    return tmp_path
```

### Step 2.2: Mocking Only The LLM (The "Dummy Kernel")
We want to test everything *except* the actual LLM network request. You should implement a `DummyKernel` that deterministicly returns a programmatic response (e.g., yielding a specific tool call) so that `AgentRunner` can process it and we can observe the reactive outbox behavior without hitting an API.

**Target File:** `tests/conftest.py`
```python
import pytest
from remora.core.agent_runner import AgentKernel
from structured_agents import Message, AgentResult

class DummyKernel(AgentKernel):
    def __init__(self, predefined_responses: list[Message]):
        self.responses = predefined_responses
        self.call_count = 0
        
    async def run(self, *args, **kwargs) -> AgentResult:
        response_msg = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return AgentResult(
            final_message=response_msg,
            tool_calls=[],
            tool_results=[],
        )

@pytest.fixture
def dummy_kernel():
    # Returns a factory or pre-configured instance
    return DummyKernel
```
---

## Step 8.1: AgentRunner Cascade Prevention Tests

**Target File:** `tests/integration/test_agent_runner.py`

**Context:** The `AgentRunner` executes agent turns. Because agents can emit events that trigger other agents, we risk infinite loops (cascades). `AgentRunner` uses `trigger_cooldown_ms` and `max_trigger_depth` to prevent this.

### Test 1: Depth Limits
* **Goal:** Verify that a chain reaction of events stops at `max_trigger_depth`.
* **How to Test:**
  1. Boot a real `AgentRunner` with `max_trigger_depth = 3`.
  2. Create a `DummyKernel` for the agents that always outputs an `AgentMessageEvent` triggering the next agent in a chain.
  3. Emit the first event.
  4. Wait for the queue to settle.
  5. Assert that exactly 3 agent turns were executed (the initial, plus 2 deep), and no more. Observe the logs to ensure the depth limit warning fired.

```python
import pytest
import asyncio
from remora.core.agent_runner import AgentRunner
from remora.core.events import AgentMessageEvent

@pytest.mark.asyncio
async def test_agent_runner_depth_limit(dummy_kernel, event_store):
    # Setup runner with strict depth limit
    runner = AgentRunner(
        event_store=event_store,
        kernel=dummy_kernel(predefined_responses=[
            Message(role="assistant", content="", tool_calls=[
                # Simulating the kernel outputting an AgentMessageEvent
            ])
        ]),
        max_trigger_depth=3
    )
    
    # Run the runner in background
    runner_task = asyncio.create_task(runner.run_forever())
    
    # Emit initial trigger
    await event_store.append("graph_1", AgentMessageEvent(to_agent="agent_a", content="start"))
    
    # Let the cascade happen
    await asyncio.sleep(0.5) 
    
    # Assert runner stopped processing after 3 turns
    assert runner.kernel.call_count == 3
    
    runner.stop()
    await runner_task
```

### Test 2: Cooldowns
* **Goal:** Verify that emitting rapid identical triggers drops the duplicates.
* **How to Test:**
  1. Set `trigger_cooldown_ms = 500`.
  2. Manually append two `ManualTriggerEvent`s for the same `agent_id` back-to-back into the `EventStore`.
  3. Assert that only *one* task is spawned for that agent by `AgentRunner`, and the second is skipped organically by `_check_cooldown`.

### Test 3: Concurrent Trigger Handling
* **Goal:** Ensure `AgentRunner` respects `max_concurrency` when a flood of events arrives.
* **How to Test:**
  1. Set `max_concurrency = 2`.
  2. Program the `DummyKernel` to `await asyncio.sleep(0.1)` (simulate work).
  3. Emit 10 events simultaneously matching 10 different agents.
  4. Track the active tasks in `AgentRunner._tasks` or use a counter. Assert that at no point do more than 2 agents run concurrently.

---

## Step 8.2: SwarmStore Integration Tests

**Target File:** `tests/integration/test_swarm_store.py`

**Context:** The `SwarmState` (sometimes referred to as SwarmStore) and `SubscriptionRegistry` track agents and their reactive triggers. These are backed by SQLite/KV databases.

### Test 1: KV-Backed Agent Registry (State Persistence)
* **Goal:** Verify agents can be strictly upserted, queried, and survive runner reboots.
* **How to Test:**
  1. Initialize `SwarmState` tied to a `tmp_path`.
  2. Provide a realistic `AgentMetadata` (e.g., representing a function node in `main.py`).
  3. Call `upsert()`.
  4. Instantiate a *new* `SwarmState` instance pointing to the *same* `tmp_path` (simulating a restart).
  5. Assert that `get_agent()` correctly returns the identical agent profile intact.

```python
import pytest
from pathlib import Path
from remora.core.swarm_state import SwarmState, AgentMetadata

def test_swarm_state_persistence(tmp_path: Path):
    db_path = tmp_path / "swarm.db"
    
    # Init first instance
    swarm1 = SwarmState(db_path)
    swarm1.initialize()
    
    meta = AgentMetadata(
        agent_id="agent_a", node_type="function",
        file_path="src/main.py", parent_id=None,
        start_line=1, end_line=10
    )
    swarm1.upsert(meta)
    swarm1.close()
    
    # Init second instance (simulating reboot)
    swarm2 = SwarmState(db_path)
    swarm2.initialize()
    
    recovered = swarm2.get_agent("agent_a")
    assert recovered is not None
    assert recovered["file_path"] == "src/main.py"
    swarm2.close()
```

### Test 2: Subscription Pattern Matching Integration
* **Goal:** Test that patterns strictly adhere to the AND-logic properties using exact payloads.
* **How to Test:**
  1. Set up a `SubscriptionRegistry`.
  2. Register Agent A with `SubscriptionPattern(event_types=["ContentChanged"], path_glob="src/*.py")`.
  3. Register Agent B with `SubscriptionPattern(to_agent="agent_b")`.
  4. Create realistic dummy events.
  5. Call `get_matching_agents(event)`. Assert that it correctly routes matching events and *does not* return false positives for partial matches.

---

## Step 8.3: EventStore Trigger Queue Tests

**Target File:** `tests/integration/test_event_store.py`

**Context:** The `EventStore` is the message bus. Everything flows through it. Concurrent database access handles appending natively, and it feeds the `AgentRunner`.

### Test 1: Concurrent Event Appending
* **Goal:** Hammer the `EventStore` concurrently to ensure SQLite locks and connection pooling (if any) hold up without raising `OperationalError: database is locked`.
* **How to Test:**
  1. Use `asyncio.gather` to fire 200 `EventStore.append()` calls simultaneously from multiple coroutines.
  2. The events should have varying timestamps, payloads, and graphs.
  3. Once finished, query `get_event_count()` and assert exactly 200 events exist and the database integrity remains sound.

```python
import pytest
import asyncio
from remora.core.event_store import EventStore
from remora.core.events import ContentChangedEvent

@pytest.mark.asyncio
async def test_event_store_concurrent_append(tmp_path):
    store = EventStore(tmp_path / "events.db")
    await store.initialize()
    
    async def worker(worker_id: int):
        for i in range(20):
            event = ContentChangedEvent(file_path=f"file_{worker_id}.py")
            await store.append("graph_1", event)
            
    # 10 concurrent writers, 20 events each
    await asyncio.gather(*(worker(i) for i in range(10)))
    
    # We would need to add a get_event_count method to EventStore for this specific assertion, 
    # or query the sqlite DB directly in the test to verify count.
```

### Test 2: Subscription-Based Trigger Delivery Pipeline
* **Goal:** End-to-end trigger integration without the runner attached.
* **How to Test:**
  1. Initialize `EventStore` and link it to a pre-populated `SubscriptionRegistry`.
  2. Start an `asyncio.Task` that listens to `EventStore.get_triggers()`.
  3. Append an event that matches an agent.
  4. Assert that the task yields exactly `(matched_agent_id, inserted_event_id, the_event_object)`. This ensures that appending an event safely crosses the queue bridging layer in chronological order.

---

## Step 8.4: Real vLLM Integration Tests

**Target File:** `tests/integration/test_vllm_real.py`

**Context:** While we use a `DummyKernel` for most core logic testing to avoid network flakiness, we absolutely must test our actual vLLM integration against a real server to ensure prompts are formatted correctly and tool calls are parsed successfully by the model.

### Test 1: Real-World Generation & Tool Calling
* **Goal:** Verify that the `AgentKernel` correctly communicates with a live vLLM instance and handles its responses.
* **How to Test:**
  1. Configure the `AgentRunner` (or a direct `AgentKernel`) to use the live server at `http://remora-server:8000/v1`.
  2. Set the model identifier to `Qwen/Qwen3-4B-Instruct-2507-FP8`.
  3. Create a test agent context with a simple, deterministic task (e.g., "Use the `send_message` tool to say 'Hello' to 'agent_b'").
  4. Run the agent turn.
  5. Assert that the network call succeeds (no 400/500 errors).
  6. Assert that the model correctly triggers the tool call in its response, proving that our prompt formatting and the model's instruction-following capabilities are aligned for this specific model version.

```python
import pytest
from structured_agents import AgentKernel, Message, ModelAdapter, QwenResponseParser
from structured_agents.client import build_client
# ... imports for your tools ...

@pytest.mark.asyncio
@pytest.mark.requires_vllm
async def test_real_vllm_tool_calling():
    client = build_client({
        "base_url": "http://remora-server:8000/v1",
        "api_key": "EMPTY",
        "model": "Qwen/Qwen3-4B-Instruct-2507-FP8",
    })
    
    adapter = ModelAdapter(name="qwen", response_parser=QwenResponseParser())
    # Assuming SendMessageTool exists in your architecture
    tools = [SendMessageTool()] 
    tool_schemas = [t.schema for t in tools]
    
    kernel = AgentKernel(client=client, adapter=adapter, tools=tools)
    
    result = await kernel.run(
        [Message(role="user", content="Say hello to agent_b using the tool.")],
        tool_schemas,
        max_turns=1
    )
    
    assert len(result.tool_calls) > 0
    assert result.tool_calls[0].name == "send_message"
```

### Test 2: Grail Tool Execution
* **Goal:** Verify that the system can inject `grail` tools (via `.pym` scripts) and that the vLLM model correctly interprets the `ToolSchema` and supplies valid arguments, successfully running the isolated runtime.
* **How to Test:**
  1. Boot the `AgentRunner` pointing to the live server at `http://remora-server:8000/v1`.
  2. Instantiate a `GrailTool` (or multiple) derived from a simple `.pym` script (e.g., `math_operations.pym`).
  3. Attach these tools to the test agent.
  4. Provide a prompt requiring the model to utilize the Grail tool.
  5. Run the agent turn.
  6. Assert that a `ToolResultEvent` is emitted with `is_error=False`, showing the exact execution output from the Grail sandbox.

### Test 3: Multi-Agent Reactive Interaction
* **Goal:** Verify end-to-end integration of vLLM interacting dynamically across two real agents. This proves `EventStore` delivery, `AgentRunner` routing, tool calling (`send_message`), and actual model comprehension work seamlessly together.
* **How to Test:**
  1. Start `AgentRunner` with a live `EventStore` and `SubscriptionRegistry`.
  2. Setup Agent A and Agent B, both utilizing the live Qwen model.
  3. Ensure Agent B is subscribed to direct messages (`to_agent="agent_b"`).
  4. Inject an initial task for Agent A: "Ask Agent B what the weather is."
  5. Assert the sequence of events:
     - Agent A turn completes.
     - `EventStore` receives an `AgentMessageEvent` from A to B.
     - Agent B is triggered and runs its turn via vLLM.
     - Agent B emits a response `AgentMessageEvent` back to A.
  6. Verify the chain works completely autonomously via the reactive triggers without manual turn calling.

  *Note: These tests should ideally be marked with `@pytest.mark.integration` or `@pytest.mark.requires_vllm` so they can be optionally skipped in environments without backend access.*
