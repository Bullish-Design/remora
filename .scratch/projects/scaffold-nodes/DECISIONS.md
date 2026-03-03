# DECISIONS — Scaffold Nodes

## Decision 1: Scaffold is a status value, not a new node_type

**Date:** 2026-03-02
**Assumptions consulted:** ASSUMPTIONS.md #1

**Options considered:**
1. New `node_type = "scaffold"` — rejected because node_type represents what the code IS (class, function, file), not its lifecycle state
2. New boolean field `is_scaffold: bool` — rejected because it adds a field to AgentNode, and status already handles lifecycle
3. New status value `status = "scaffold"` — chosen

**Decision:** Use `status = "scaffold"` as the discriminator. This requires zero model changes and fits the existing status lifecycle (idle → running → idle/error). Scaffold is just another state in that lifecycle, with the twist that the node hasn't been fully initialized yet.

**Rationale:** The status field already carries lifecycle semantics. A scaffold node transitions scaffold → running → idle once it fills itself in. This is the simplest change with the widest compatibility.

---

## Decision 2: ScaffoldRequestEvent carries intent, not full context

**Date:** 2026-03-02
**Assumptions consulted:** ASSUMPTIONS.md #2, #4

**Options considered:**
1. Pack parent source + sibling info into the event — rejected because events should be lightweight triggers, not data carriers
2. Just use NodeDiscoveredEvent with a flag — rejected because scaffold initialization is a distinct lifecycle trigger
3. Minimal event with node_id + intent string — chosen

**Decision:** `ScaffoldRequestEvent` carries `node_id`, `node_type`, `parent_id`, and `intent` (optional human hint). Context enrichment happens at prompt-build time, not event time.

**Rationale:** Events should be "something happened" signals. The rich context (parent source, sibling list) is assembled when the agent actually runs, using the standard prompt-building pipeline. This keeps events thin and the prompt builder responsible for context assembly.

---

## Decision 3: Stub detection lives in the projection, not the watcher

**Date:** 2026-03-02
**Assumptions consulted:** ASSUMPTIONS.md #9

**Options considered:**
1. Watcher marks nodes as stubs via a flag in the node dict — rejected because the watcher should just report what it sees
2. Projection detects stubs by inspecting source_code content — chosen
3. Extension matches on source_code to detect stubs — rejected because scaffold status assignment should happen before extension matching

**Decision:** `NodeProjection._project_node_discovered()` checks `source_code` content via `_is_stub()` helper. If it's a stub, status is set to `"scaffold"` instead of `"idle"`.

**Rationale:** The watcher's job is faithful AST parsing. The projection's job is materializing the read model with appropriate semantics. Stub detection is a semantic judgment that belongs in the projection layer.
