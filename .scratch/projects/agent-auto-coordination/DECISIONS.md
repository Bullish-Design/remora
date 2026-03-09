# Decisions — Agent Auto-Coordination

---

## D1 — "bootstrap-system" is a pseudo-agent, not an LLM agent

**Decision:** Use a synthetic agent ID `"bootstrap-system"` registered in
`SubscriptionRegistry`. `run_from_event_store` dispatches its triggers to
Python handlers, not `handle_agent_needed`.

**Rationale:** Coordination (find unassigned nodes → emit events) is
deterministic. Using an LLM for it adds latency, cost, and non-determinism
for zero intelligence gain. Python handles this perfectly. The LLM stays in
the per-file subject matter expert agent where its intelligence matters.

**Alternative rejected:** LLM directory coordinator. Discarded because an LLM
calling `emit_agent_needed_for_node` 200 times is fragile, slow, and
unnecessary.

---

## D2 — Register bootstrap-system subscriptions BEFORE seeding

**Decision:** In `initialize()`, call `_register_system_subscriptions()` as
the very first operation after store setup, before any seeding call.

**Rationale:** `seed_module_nodes_from_filesystem` emits `NodeDiscoveredEvent`
for each file. Those events flow through `EventStore.append()` → subscription
matching → trigger queue. If "bootstrap-system" is not yet registered, those
events produce no triggers and are lost forever (events are not replayed).

**Implication:** The ordering in `initialize()` is load-bearing. Comments in
the code must make this clear.

---

## D3 — Directory node uses kind="directory", not kind="agent"

**Decision:** The directory node is seeded with `kind="directory"`,
`node_type="directory"`. It does NOT have `kind="agent"`.

**Rationale:** In this project, the directory node has no LLM agent. Marking
it `kind="agent"` would cause `_read_assigned_node_ids()` to include it in the
coordinator's agent list. Marking it `kind="directory"` makes it invisible to
the current coordinator queries and clearly documents its structural role.

**Future implication:** When a directory agent is added (future phase), it
will need its own activation path triggered by `FileCreatedEvent`. At that
point, the kind may be upgraded or a separate agent node linked to it.

---

## D4 — Directory node ID format: "directory:."

**Decision:** Root directory node ID is `"directory:."`. Subdirectory nodes
(future) would be `"directory:src/"`, `"directory:tests/"`, etc.

**Rationale:** Consistent with `"module:src/app.py"` format. The dot (`.`)
is the POSIX representation of the current directory. Clear, unambiguous,
filesystem-mapped.

---

## D5 — SubscriptionPattern.node_id uses eager template resolution

**Decision:** `_register_schema_subscriptions` resolves `"{node.id}"` templates
immediately using `node_attrs` at registration time. The resolved value is
stored in `SubscriptionPattern.node_id`.

**Rationale:** Lazy resolution would require storing the template + node_attrs
in the pattern, complicating serialization. Eager resolution is simpler and
correct since `node_attrs` is available when `handle_agent_needed` runs.

**Edge case:** If the template doesn't resolve (still contains `{node.`), log
a warning and register without `node_id` filter (fail open rather than
registering an unmatchable subscription).

---

## D6 — run_once() kept as optional fallback

**Decision:** `run_once()` and the Python polling coordinator are kept but
disabled by default via `use_python_coordinator: bool = False`. The primary
path is `run_from_event_store`.

**Rationale:** The directory agent + `run_from_event_store` are new code. If
the LLM fails, the schema is broken, or an edge case in the event routing is
hit, the Python fallback guarantees nodes eventually get assigned. Remove the
fallback only after the event-driven path is battle-tested.

---

## D7 — AgentNeededEvent emitted via EventStore.append, not direct handle_agent_needed

**Decision:** When `_handle_system_trigger` receives a `NodeDiscoveredEvent`,
it emits `AgentNeededEvent` via `EventStore.append()` rather than directly
calling `handle_agent_needed()`.

**Rationale:** This keeps the event-driven chain intact. The `AgentNeededEvent`
is a real event in the event log (observable, replayable, auditable). Directly
calling `handle_agent_needed()` would skip the event log. The extra async hop
through the trigger queue is worth the observability gain.

**Note:** This creates a two-step dispatch chain: `NodeDiscoveredEvent` trigger
→ emit `AgentNeededEvent` → `AgentNeededEvent` trigger → `handle_agent_needed`.
The trigger queue processes both in sequence.

---

## D8 — bootstrap-system subscription idempotency via get_subscriptions check

**Decision:** Before registering "bootstrap-system" subscriptions, check
`get_subscriptions("bootstrap-system")` and skip registration for any
event_type already present.

**Rationale:** `initialize()` is called on every LSP startup. Without
idempotency, each restart adds duplicate subscriptions, and duplicate entries
cause duplicate triggers (the same `AgentNeededEvent` would fire
`handle_agent_needed` twice per restart count).
