# Decisions

1. Treat this as a system contract problem, not only a SQL predicate bug.
- Rationale: mismatch appears at multiple boundaries (query semantics, event envelope shape, live vs replay consistency).

2. Reject "broaden existing `get_recent_events` query" as the final architecture.
- Rationale: it fixes the symptom but overloads API semantics for unrelated consumers (`turn_context`, bootstrap).

3. Recommend architecture-first fix (no backward-compat mode):
- Split query intent (`routed_messages` vs `agent_timeline`).
- Enforce one canonical event envelope for both live notify and replay.
- Introduce participant indexing/projection for durable timeline queries.
