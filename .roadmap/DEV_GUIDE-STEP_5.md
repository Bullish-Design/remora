# DEV GUIDE STEP 5: Coordinator Agent Contract

## Goal
Implement `coordinator.pym` to spawn specialized agents and aggregate results.

## Why This Matters
Coordinator orchestrates per-node work and is the gateway to specialized agents.

## Implementation Checklist
- Read standard inputs (`node_id`, `node_type`, `node_text`, etc.).
- Spawn specialized agents via `spawn_specialized_agent`.
- Await each agent with `wait_for_agent`.
- Aggregate results into the output schema.
- Log spawn/execution errors.

## Suggested File Targets
- `agents/coordinator.pym` (or equivalent path)

## Implementation Notes
- Follow schema in `SPEC.md` section 6.1.
- Ensure `errors` contains phase (`spawn` or `execution`).
- Return a complete `operations` map for requested operations.

## Testing Overview
- **Contract test:** Output schema matches spec for success.
- **Contract test:** Failed agent returns `status=failed` with error message.
- **Error test:** Spawn failure logged with `phase=spawn`.
