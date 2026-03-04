# Companion Refactor — Context

> **CRITICAL RULES:**
> - **NO SUBAGENTS** — Do ALL work directly.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.

---

## Current State

**Phase:** PLANNING COMPLETE — Ready for user review before implementation.

**Last action:** Created all project planning documents:
- `ASSUMPTIONS.md` — Defines "first-class" and "remora ethos" concretely
- `DECISIONS.md` — Resolves 6 key architectural decisions (AgentNode mapping, event model, workspace, subscriptions, package location, runtime wiring)
- `PLAN.md` — 6-phase incremental refactor plan with acceptance criteria
- `PROGRESS.md` — Task tracker (all pending)
- `CONTEXT.md` — This file

---

## Key Decision Summary

1. **D1 (AgentNode):** Thin bridge — companion agents use core primitives (EventStore, SubscriptionPattern, _FrozenEvent) but do NOT become AgentNodes. They're service agents, not code-node agents.
2. **D2 (Events):** Migrate to `_FrozenEvent` Pydantic models. Prefix with `Companion` to avoid collisions.
3. **D3 (Workspace):** New `EventStoreWorkspace` — writes go through EventStore, reads from in-memory cache. `InMemoryWorkspace` stays for unit tests.
4. **D4 (Subscriptions):** Replace manual `_on_path_change()` routing with `SubscriptionPattern` registration in `SubscriptionRegistry`.
5. **D5 (Package):** Move to `src/remora/companion/`. Demo code stays in `remora_demo/`.
6. **D6 (Runtime):** Registry-driven agent discovery. No more hardcoded wiring.

---

## What To Do Next

**Check in with the user** — The planning docs are complete. Ask if the plan and decisions look good before starting implementation. Key question: Does the user agree with D1 (thin bridge over forcing companion agents into AgentNode)?

---

## Commands

```bash
# Sync deps
devenv shell -- uv sync --extra companion --extra dev

# Run companion tests
devenv shell -- bash -c "uv run --extra companion --extra dev python -m pytest tests/companion/ -v --timeout=30 --no-cov --no-header"

# Run core tests
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

---

## Key Files

| File | Purpose |
|------|---------|
| `src/remora/core/events.py` | `_FrozenEvent` base, `RemoraEvent` union |
| `src/remora/core/event_store.py` | EventStore — SQLite append-only log |
| `src/remora/core/subscriptions.py` | SubscriptionPattern, SubscriptionRegistry |
| `src/remora/core/agent_node.py` | AgentNode — code-node agents only |
| `remora_demo/companion/runtime.py` | Current CompanionRuntime (to be refactored) |
| `remora_demo/companion/agents/base.py` | Current AgentBase, InMemoryWorkspace |
| `remora_demo/companion/models/events.py` | Current companion events (frozen dataclasses) |

---

> **REMINDER:**
> - **NO SUBAGENTS** — Do ALL work directly.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.
