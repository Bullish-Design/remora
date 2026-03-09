# Assumptions — Agent Auto-Coordination

Context loaded before making decisions. Describes the audience, constraints,
invariants, and scenarios that shape *why* decisions get made.

---

## Project Goal

Build a fully autonomous, event-driven bootstrap system where:

1. Nodes appear in the graph (via `NodeDiscoveredEvent`)
2. The system automatically routes those events to activate file agents
3. File agents register scoped subscriptions
4. Future file changes re-activate only the relevant agent
5. **No Python polling loop. No LLM coordinator. Pure event-driven.**

---

## Core Insight

**Coordination is deterministic work. LLMs are for intelligent work.**

"Find unassigned nodes → activate them" is bookkeeping. Python does it
reliably in microseconds. An LLM adds latency, cost, and non-determinism
to a task that has a single correct answer.

The original "directory node as LLM coordinator" was discarded because:
- An LLM calling `emit_agent_needed_for_node` 200 times is fragile
- The Python coordinator already finds unassigned nodes correctly
- The problem was never the coordinator logic — it was the missing
  event-driven re-activation loop

The right separation: **Python handles coordination routing;
LLMs handle per-file intelligence.**

---

## System Architecture (Target State)

### The "bootstrap-system" pseudo-agent

A synthetic agent ID (`"bootstrap-system"`) is registered in `SubscriptionRegistry`
at startup with two subscriptions:

1. `SubscriptionPattern(event_types=["NodeDiscoveredEvent"])`
2. `SubscriptionPattern(event_types=["AgentNeededEvent"])`

This makes the event store's trigger queue route both event types to
`run_from_event_store`, which dispatches them to Python handlers — not an LLM.

**This is the key architectural move.** The `SubscriptionRegistry` already
supports registering any agent_id. The `run_from_event_store` loop already
consumes from the trigger queue. We add a branch: if trigger agent_id is
`"bootstrap-system"`, dispatch to a Python handler. Otherwise, re-activate
the LLM agent normally.

### Event flow (target state)

```
startup
  → register "bootstrap-system" subscriptions (BEFORE seeding)
  → seed_root_directory_node()    → creates "directory:." + edges to children
  → seed_module_nodes_from_filesystem()
      → NodeDiscoveredEvent per file
      → matches "bootstrap-system" subscription
      → trigger queued in event_store

run_from_event_store() [concurrent asyncio task]
  trigger: ("bootstrap-system", id, NodeDiscoveredEvent)
    → check: node already has agent? skip : emit AgentNeededEvent
  trigger: ("bootstrap-system", id, AgentNeededEvent)
    → handle_agent_needed() → file agent LLM runs
    → agent writes summary.md, registers subscriptions:
        ContentChangedEvent WHERE node_id = "module:src/app.py"

future: file saved
  → ContentChangedEvent → subscription matches file agent
  → trigger queued → run_from_event_store re-activates file agent
```

### The directory node (structural, not coordinator)

The directory node (`node_id="directory:."`, `kind="directory"`) exists in the
graph to:
1. Make the graph hierarchical (parent→child edges to file nodes)
2. Give agents a way to query "what's in my directory?"
3. Enable future: `FileCreatedEvent` → directory node's agent decides whether
   and what kind of agent to spin up for the new file

The directory node does NOT run an LLM agent in this project. Its value is
graph topology, not LLM coordination.

---

## Current State (Starting Point)

### What exists and works
- `seed_coordinator_node()` — seeds a "coordinator" agent node
- `seed_module_nodes_from_filesystem()` — seeds file nodes, emits `NodeDiscoveredEvent`
- `handle_agent_needed()` — activates an LLM agent for a node
- `SubscriptionRegistry` — persists subscriptions, `register(agent_id, pattern)`
- `_activation_lock` in `BootstrapRunner` — prevents concurrent activation conflicts
- 66 bootstrap tests passing

### What's broken (bugs from FINAL_CODE_REVIEW.md)
- **M_uri**: `run_for_file(uri)` gets raw LSP URI; nodes stored as relative paths → silent no-op
- **M_sub**: `SubscriptionPattern` has no `node_id` field → all `ContentChangedEvent` subscriptions are unscoped (fire for any file, not just the agent's file)
- **M_priv**: `activation.py` accesses `_stable_workspace` private attribute

### What's missing (new work)
- **No `run_from_event_store`**: events go into trigger queue but nothing consumes them
- **No "bootstrap-system" routing**: NodeDiscoveredEvent has no handler
- **No directory node**: graph is flat; no parent→child structure
- **No idempotency for system subscriptions**: re-starting the LSP should not
  double-register "bootstrap-system" subscriptions

---

## System Invariants

1. **EventStore is append-only.** All state changes go through `EventStore.append()`.
2. **AgentNode is a single Pydantic BaseModel.** No subclasses, ever.
3. **No isinstance in business logic.** Data-driven dispatch only.
4. **Layer rule:** `core` → `runner/bootstrap` → `adapters (lsp, service)`. Bootstrap MUST NOT import from `lsp/`.
5. **tach check passes** after every milestone.
6. **TDD**: failing test first, then implementation.
7. **66 bootstrap tests must continue to pass** through every milestone.

---

## Subscription Registration Ordering Constraint

**"bootstrap-system" subscriptions MUST be registered BEFORE seeding.**

If subscriptions are registered after `seed_module_nodes_from_filesystem()` runs,
the `NodeDiscoveredEvent`s emitted during seeding will not match any subscriptions
→ trigger queue is empty → `run_from_event_store` has nothing to process.

The seed events are NOT replayed retroactively. Registration order matters.

---

## Idempotency of "bootstrap-system" Subscriptions

On each LSP startup, `initialize()` runs. The "bootstrap-system" subscriptions
must not be duplicated across restarts. Before registering, check if they already
exist via `get_subscriptions("bootstrap-system")`. If both expected subscriptions
are present, skip registration.

---

## Scope Boundaries

**In scope:**
- `SubscriptionPattern.node_id` field + scoped matching
- `stable_workspace` public property
- URI path normalization in `documents.py`
- `"bootstrap-system"` subscription registration in `initialize()`
- `run_from_event_store()` with system dispatch logic
- `seed_root_directory_node()` + parent→child edges
- Remove/deprecate Python polling coordinator as primary path
- Tests for each milestone

**Out of scope:**
- `FileCreatedEvent` / filesystem watcher (future directory agent)
- Subdirectory hierarchy (each dir its own directory node)
- Directory node running an LLM agent (future)
- LSP scanner integration (NodeDiscoveredEvent from tree-sitter) — assume it works
