# DEV GUIDE STEP 4: Orchestration Layer + Cairn Interface

## Goal
Spawn a coordinator per node and collect structured results.

## Why This Matters
This layer connects discovery to execution and manages concurrency.

## Implementation Checklist
- Implement `process_node` to spawn `coordinator.pym` via Cairn.
- Add concurrency controls (`max_concurrent`) and timeouts.
- Map coordinator output into `NodeResult`.

## Suggested File Targets
- `remora/orchestrator.py`
- `remora/results.py` (shared result models)

## Implementation Notes
- Match coordinator input/output schema in `SPEC.md` section 6.
- Use async concurrency primitives to limit parallel execution.
- Preserve error details for failed agent spawns.

## Testing Overview
- **Unit test:** Mock Cairn spawn/wait returns expected `NodeResult`.
- **Unit test:** Concurrency limit enforced with multiple nodes.
- **Error test:** Spawn failure returns `AGENT_001`/`AGENT_003`.
