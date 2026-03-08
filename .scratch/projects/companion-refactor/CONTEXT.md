# Companion Refactor — Context

> **CRITICAL RULES:**
> - **NO SUBAGENTS** — Do ALL work directly.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.

---

## Current State

**Phase:** PLANNING — Creating implementation guide (COMPANION_REFACTOR_GUIDE.md).

**Concept doc:** `COMPANION_REFACTOR_CONCEPT.md` — complete. Read this first.

**Approach:** Full clean-slate rewrite. No backwards compatibility. Delete everything old,
replace with node-resident agent architecture backed by Cairn.

---

## Core Vision (summary)

Every CST node gets its own persistent `NodeAgent` backed by a Cairn workspace.
The companion sidebar = the active node's accumulated knowledge (not a signal pipeline).
Chat = one input channel into the NodeAgent. MicroSwarms organize each exchange async.

## Key Invariants

- Cairn is REQUIRED — no optional fallback.
- `AgentNode`, `CairnWorkspaceService`, `AgentWorkspace`, `EventBus`, `EventStore` are UNCHANGED.
- `CursorFocusEvent.focused_agent_id` IS the node_id — router uses it directly.
- All companion commands surface via `workspace/executeCommand` (no new LSP methods).

## What To Do Next

Implement COMPANION_REFACTOR_GUIDE.md phases in order:
1. Delete old companion code (Phase 0)
2. New events.py (Phase 1)
3. New config.py (Phase 2)
4. node_workspace.py (Phase 3)
5. swarms/ (Phase 4)
6. links/ (Phase 5)
7. sidebar/ (Phase 6)
8. node_agent.py (Phase 7)
9. registry.py (Phase 8)
10. router.py (Phase 9)
11. startup.py (Phase 10)
12. lsp/handlers/companion.py (Phase 11)
13. __main__.py wiring (Phase 12)
14. Tests (Phase 13)
15. Neovim plugin (Phase 14)

## Commands

```bash
devenv shell -- uv sync --extra dev
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
devenv shell -- tach check
```

> **REMINDER:**
> - **NO SUBAGENTS** — Do ALL work directly.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.
