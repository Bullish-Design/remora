# Assumptions — Close Architecture Gaps

## Audience
- Solo developer building Remora (reactive agent swarm system)
- Changes must not break existing tests (4 known pre-existing failures + 6 collection errors excluded)

## Constraints
- All commands via `devenv shell -- <command>`
- TDD: failing test first, then implement
- NO subagents (Task tool)
- `AgentNode` is a single Pydantic BaseModel — no subclasses
- `EventStore` is single source of truth
- `execute_agent_turn()` is THE ONE execution path

## Key Design Invariants
- `CursorFocusEvent` uses `focused_agent_id` (not `agent_id`) because EventStore's `_row_to_dict()` strips `agent_id` from replay payload
- Subscribe/unsubscribe are Python `SwarmTool` classes, not `.pym` Grail scripts
- EventBus is downstream-only (forwarding for SSE/UI), not primary routing
- `run_from_event_store()` bridges EventStore trigger queue into runner's asyncio.Queue
- Deduplication needed when both subscription-based triggers AND manual `runner.trigger()` calls exist for the same event

## Dependencies Between Gaps
- Gap #4 (scaffold lifecycle) depends on Gap #2 (tags on AgentCompleteEvent) for the chain pattern
- Gap #1 (trigger wiring) is independent
- Gap #3 (swarm tools verification) is independent
