# Plan

NO SUBAGENTS: this analysis and planning work is executed directly in this workspace.

## Goal

Design the cleanest long-term fix for missing sidebar responses and prevent adjacent event-routing/history mismatches across Remora, without preserving legacy behavior.

## Deliverables

1. Revised root-cause analysis grounded in fresh-environment artifacts.
2. Full impact matrix for changing event-history semantics.
3. Recommended target architecture with explicit tradeoffs.
4. Concrete implementation roadmap for code and tests.

## Workstream Plan

1. Re-validate the failure chain in the fresh environment (`remora-example-workspace`).
- Confirm panel-closed input path.
- Confirm `AgentTextResponse` emission.
- Confirm panel history count mismatch.
- Confirm DB mismatch (`from_agent/to_agent` vs `payload.agent_id`).

2. Trace all consumers of `EventStore.get_recent_events()`.
- Classify each caller intent (timeline vs routed-message history).
- Identify semantic conflicts caused by overloading one API for multiple intents.

3. Audit event envelope consistency across write/read/notify paths.
- Compare live LSP notifications (`event.model_dump()`) with DB replay dicts (`row_to_event_dict`).
- Identify schema drift points (`agent_id`, `from_agent`, `to_agent`, `summary`, event `id`).

4. Evaluate fix options.
- Option A: broaden existing query with `json_extract(payload, '$.agent_id')`.
- Option B: split query APIs but keep current envelope style.
- Option C (target): canonical envelope + participant index + explicit query intents.

5. Select recommended architecture (Option C) and define migration approach.
- Replace overloaded `get_recent_events()` with explicit methods:
  - `get_recent_routed_messages(...)`
  - `get_recent_agent_timeline(...)`
- Introduce canonical event envelope shape for both live and replayed events.
- Introduce durable participant indexing for agent timeline queries.

6. Define required code and test changes.
- Event store schema/query/serialization changes.
- LSP server/panel/hover callsite updates.
- Bootstrap and turn-context updates.
- Regression/invariant tests to prevent future schema/query drift.

## Acceptance Criteria

1. Panel history correctness does not depend on panel-open state.
2. Event history APIs have explicit semantics and are not overloaded.
3. Live and replayed events share one canonical shape (including stable `id`).
4. Tests enforce invariants linking event emission, persistence, and retrieval.

NO SUBAGENTS: all tasks above are performed directly.
