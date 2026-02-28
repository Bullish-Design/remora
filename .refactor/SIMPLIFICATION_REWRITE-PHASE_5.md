# Phase 5 - Agent Runner (Reactive Execution)

## Goal
Create the reactive `AgentRunner` that consumes EventStore triggers and runs agent turns with cascade prevention. This replaces polling with event-driven execution.

## Guiding principles
- The runner should only react to `EventStore.get_triggers()`.
- Cascades must be bounded via depth and cooldown limits from config.
- Keep integration with existing kernel/executor code minimal and focused.

## Definition of done
- `agent_runner.py` exists and can process triggers.
- Cascades are limited by `max_trigger_depth` and `trigger_cooldown_ms`.
- Unit tests cover concurrency and cascade control behavior.

## Step-by-step implementation

### 1) Define the runner interface
Implementation:
- Create `src/remora/core/agent_runner.py`.
- Define `AgentRunner` with:
  - `event_store: EventStore`
  - `subscriptions: SubscriptionRegistry`
  - `swarm_state: SwarmState`
  - `config: Config`
  - `event_bus: EventBus | None`
- Define `async def run_forever(self) -> None` as the main loop.

Testing:
- Add a basic import test: `python -c "from remora.core.agent_runner import AgentRunner"`.

### 2) Implement trigger consumption
Implementation:
- In `run_forever`, iterate over `event_store.get_triggers()`.
- For each trigger tuple `(agent_id, event_id, event)`:
  - Gate by cascade prevention (see next steps).
  - Schedule execution with `asyncio.create_task` while honoring concurrency limit.
- Use `asyncio.Semaphore` based on `config.max_concurrency` to cap active turns.

Testing:
- Add a unit test with a fake EventStore that yields two triggers and verify both are processed with the semaphore.

### 3) Implement cascade prevention (depth limit)
Implementation:
- Use `correlation_id` from the event to track cascades.
- Maintain a dict `correlation_depth: dict[str, int]` in the runner.
- When a trigger arrives:
  - If `correlation_id` is missing, treat depth as 0.
  - If depth >= `config.max_trigger_depth`, skip execution and emit a warning event (optional).
  - Otherwise increment depth for this correlation during the turn and decrement after completion.

Testing:
- Add a unit test that simulates a correlation chain and verifies the runner refuses to execute beyond the limit.

### 4) Implement cooldown (time-based throttle)
Implementation:
- Track `last_trigger_time: dict[str, float]` keyed by `agent_id`.
- If a new trigger arrives within `config.trigger_cooldown_ms`, skip or delay it (choose one behavior and document it).
- Prefer skip with a trace log to keep behavior deterministic.

Testing:
- Add a test that sends two triggers for the same agent within the cooldown and verifies only one executes.

### 5) Load AgentState and build execution context
Implementation:
- For each trigger, load `AgentState` from `state.jsonl`.
- Build an execution context that includes:
  - Agent metadata
  - Triggering event
  - Recent chat history (if used by the kernel)
- Keep the event in context so the agent can react to it explicitly.

Testing:
- Add a test that loads state and confirms the trigger event is passed into the execution context.

### 6) Execute a single agent turn
Implementation:
- Reuse existing `GraphExecutor` or create a focused helper that runs one agent node.
- If using `GraphExecutor`:
  - Add a method to execute a single node by id without building the full graph.
- Emit events in this order:
  - `AgentStartEvent`
  - `TurnCompleteEvent` (from kernel)
  - `AgentCompleteEvent` or `AgentErrorEvent`
- Ensure outgoing events go through `EventStore.append()` so they can trigger other agents.

Testing:
- Add a unit test with a fake kernel that returns a deterministic result and verify event ordering.

### 7) Persist updated AgentState
Implementation:
- After a successful run, update `AgentState`:
  - Append to `chat_history` if there was a user chat event.
  - Update `connections` if new relationships are discovered.
  - Update `last_updated`.
- Save state back to `state.jsonl`.

Testing:
- Add a test that runs a fake turn and verifies the state file changes.

### 8) Graceful shutdown hooks
Implementation:
- Add a `stop()` method that cancels pending tasks and closes EventStore connections.
- Ensure the runner exits cleanly on cancellation.

Testing:
- Add a test that cancels `run_forever` and confirms no background tasks remain.

### 9) Wire runner into startup (temporary entry point)
Implementation:
- Add a minimal entry point (internal) to start the runner after reconciliation.
- Do not expose CLI commands here; that comes in Phase 7.

Testing:
- Run a small integration script (can be a test helper) that starts the runner, emits an event, and confirms the trigger is processed.

## Testing additions (unit/smoke/examples)
Unit tests to add/update:
- `tests/unit/test_agent_runner.py::test_cooldown_skips_fast_retriggers` (new).
- `tests/unit/test_agent_runner.py::test_depth_limit_blocks_cascade` (new).
- `tests/unit/test_agent_runner.py::test_emits_start_and_complete_events` (new).
- `tests/unit/test_agent_runner.py::test_state_persisted_after_turn` (new).

Smoke tests to add/update:
- `tests/integration/test_runner_smoke_real.py::test_runner_processes_single_trigger` (new) - uses real EventStore + SubscriptionRegistry on disk.
- `tests/integration/test_runner_smoke_real.py::test_runner_uses_semaphore_limits` (new).

Example tests to add:
- `tests/unit/test_agent_runner.py::test_correlation_depth_increments` (new).
- `tests/integration/test_runner_smoke_real.py::test_trigger_chain_emits_multiple_events` (new).

## Notes
- Do not implement polling or inbox checks. The only input should be `EventStore.get_triggers()`.
- Keep error handling explicit and emit `AgentErrorEvent` on failures.
