# Repo Cleanup — Assumptions

These assumptions inform decisions made during cleanup.

---

## Architecture

- **EventBased architecture** (per `docs/EventBased_Concept.md`) is the target state. Anything that doesn't serve it is a candidate for removal.
- **Option A unification** is complete. The LSP subsystem reads from EventStore via AgentNode. `ASTAgentNode`, `lsp/extensions.py`, and RemoraDB `nodes` table are already deleted.
- **Cairn/Grail** are legitimate runtime dependencies for tool execution. Code that bridges to them (e.g., `cairn_bridge.py`, `cairn_externals.py`) stays.

## Repo Hygiene

- **`.scratch/`** is for dev working notes only. Never committed to git.
- **Runtime artifacts** (`.remora/`, `.grail/`, `*.db`, `*.db-wal`) must be gitignored, never tracked.
- **Vendored reference code** (`.context/`) is useful for dev but not for the repo. Gitignore it.
- **Old agent bundles** (`agents/`) are already gitignored and have no migration path to AgentExtension.

## Safety

- **Phase 1 removals are zero-risk** — temp files, old reviews, dead demo workspace. Nothing references them.
- **Phase 2 moves are safe** — file moves don't change behavior. Only risk is broken links in other docs, which can be fixed.
- **Phase 3 requires verification** — code changes must be validated by running the test suite.
- **Phase 4 is content-only** — documentation rewrites don't affect code behavior.

## Test Suite

- Test command: `python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`
- Known pre-existing failure: `test_lsp_handlers_register_and_advertise_capabilities` (missing `workspace/executeCommand`).
- Devenv is currently broken (iocraft hash mismatch) — may not be able to run tests directly.
