# Progress — Agent Auto-Coordination

## Status Legend
- `[ ]` pending
- `[>]` in-progress
- `[x]` done
- `[!]` blocked (see ISSUES.md)

---

## Milestones

| # | Milestone | Files | Status |
|---|-----------|-------|--------|
| M0 | URI path normalization | `lsp/handlers/documents.py` | `[ ]` |
| M1 | `SubscriptionPattern.node_id` + scoped matching | `core/events/subscriptions.py`, `bootstrap/activation.py` | `[ ]` |
| M2 | `stable_workspace` public property | `core/agents/cairn_bridge.py`, `bootstrap/activation.py` | `[ ]` |
| M3 | `run_from_event_store` with bootstrap-system dispatch | `bootstrap/runner.py` | `[ ]` |
| M4 | Register bootstrap-system subscriptions at startup | `bootstrap/runner.py` | `[ ]` |
| M5 | Seed root directory node + parent→child edges | `bootstrap/seed_graph.py` | `[ ]` |
| M6 | Wire `run_from_event_store` in LSP `__main__.py` | `lsp/__main__.py` | `[ ]` |
| M7 | Deprecate Python polling coordinator | `bootstrap/runner.py` | `[ ]` |
| M8 | Integration test: full event-driven flow | `tests/integration/test_auto_coordination.py` | `[ ]` |

---

## Test Baseline

- **Starting:** 66 bootstrap tests, full suite ~180 passing
- **Target after M8:** 80+ bootstrap tests, full suite passes, `tach check` passes

---

## Last Updated

2026-03-09 — project created and fully revised with "bootstrap-system" architecture
