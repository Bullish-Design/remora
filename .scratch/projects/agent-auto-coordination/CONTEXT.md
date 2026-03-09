# Context — Agent Auto-Coordination

*Update this file before every large context shift. Should answer:
"If I lost all memory right now, what do I need to know to continue?"*

---

## Current Status

**Project fully designed. No code changes made yet.**

Next task: **M0** — URI path normalization in `src/remora/lsp/handlers/documents.py`.

---

## The Core Idea in One Paragraph

Register a synthetic `"bootstrap-system"` agent in `SubscriptionRegistry` with
subscriptions to `NodeDiscoveredEvent` and `AgentNeededEvent`. When the
EventStore appends a `NodeDiscoveredEvent` (from file seeding), it queues a
trigger for "bootstrap-system". A new `run_from_event_store()` loop consumes
that trigger and emits `AgentNeededEvent` for the discovered node. That
`AgentNeededEvent` is also matched by "bootstrap-system" → trigger queued →
`handle_agent_needed()` called → file agent LLM runs. All subsequent
re-activation (file changes, cursor focus, human input) flows through the same
loop. No Python polling coordinator needed. No LLM coordinator needed.

---

## Key Architecture Decisions

- **"bootstrap-system" is NOT an LLM** — it's a Python dispatch mechanism using
  the existing `SubscriptionRegistry` + trigger queue infrastructure
- **Subscriptions registered BEFORE seeding** — critical ordering constraint in
  `initialize()`; events from seeding are not replayed
- **Directory node is structural only** — `kind="directory"`, no LLM agent in
  this project; enables graph hierarchy + future FileCreatedEvent target
- **run_once() kept as fallback** — controlled by `use_python_coordinator=False`
- **AgentNeededEvent goes through EventStore** — maintains audit trail;
  two-step dispatch: NodeDiscovered → AgentNeeded → handle_agent_needed

---

## Milestone Order and Rationale

```
M0: Fix URI bug (on-open activation works)
M1: SubscriptionPattern.node_id (scoped subscriptions, prerequisite for M3 correctness)
M2: stable_workspace property (small cleanup)
M3: run_from_event_store (the event loop itself — core of everything)
M4: Register bootstrap-system at startup (connects the loop to the event store)
M5: Directory node seeding (graph structure)
M6: Wire in LSP __main__.py (concurrent task startup)
M7: Deprecate Python polling (make event-driven path primary)
M8: Integration test (end-to-end validation)
```

---

## Key File Locations

| What | Where |
|------|-------|
| Bootstrap runner | `src/remora/bootstrap/runner.py` |
| Activation logic | `src/remora/bootstrap/activation.py` |
| Graph seeding | `src/remora/bootstrap/seed_graph.py` |
| Subscriptions | `src/remora/core/events/subscriptions.py` |
| CairnBridge | `src/remora/core/agents/cairn_bridge.py` |
| LSP entry | `src/remora/lsp/__main__.py` |
| did_open handler | `src/remora/lsp/handlers/documents.py` |
| Bootstrap tests | `tests/unit/bootstrap/` |
| Integration tests | `tests/integration/` |

---

## Test Commands

```bash
# Sync deps (once per session before first test run)
devenv shell -- uv sync --extra dev

# Fast bootstrap check
devenv shell -- pytest tests/unit/bootstrap/ -q

# Full suite (known pre-existing failure: test_lsp_handlers_register_and_advertise_capabilities)
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q

# Architecture check
devenv shell -- tach check
```

---

## Resumption After Compaction

1. Read `.scratch/CRITICAL_RULES.md` and `.scratch/REPO_RULES.md`
2. Check `PROGRESS.md` for first `[ ]` milestone
3. Read `CONTEXT.md` (this file)
4. Read the file being modified — never assume its current contents
5. Write failing test first (TDD), then implement
6. Verify: pytest tests/unit/bootstrap/ passes before moving to next milestone
