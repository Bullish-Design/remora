# ASSUMPTIONS — Launch Plan Execution

## Project Audience
- Library consumers (developers building on Remora)
- Internal maintainers working on the LSP server and demo layers

## Scope
- `src/remora/` library code ONLY
- `remora_demo/` is OUT OF SCOPE
- Test suite under `tests/` is IN SCOPE (fixing, writing, cleaning tests)
- Neovim plugin files (`lua/remora/`, `plugin/`, `load.vim`) are IN SCOPE for fixes and deletion

## Constraints (from REMORA_LAUNCH_PLAN.md Section 7)
1. **NO SUBAGENTS** — all work done directly. No Task tool. No delegation. No exceptions.
2. **AgentNode is THE model** — single Pydantic BaseModel, no subclasses. Specialization via `AgentExtension`.
3. **EventStore is THE source of truth** — every state change is an event. All other state derived via projections.
4. **No `isinstance` in business logic** — projection dispatch (internal) is the exception.
5. **TDD** — failing test first, implement, verify pass.
6. **DRY/YAGNI** — no duplication, no speculative features.

## Key Invariants
- The `nodes` table is a projection of EventStore events — NOT independent state
- AgentNode fields are the canonical agent identity — no separate AgentState, AgentMetadata
- Events are immutable once appended
- A single SQLite database is the end-state (currently 4 separate DBs)
- The LSP runner is the surviving runner — core AgentRunner will be merged into it

## Authority Documents
| Document | Path | Role |
|----------|------|------|
| Architecture vision | `docs/EventBased_Concept.md` | All decisions measured against this |
| AgentNode design spec | `docs/plans/2026-03-02-agentnode-design.md` | AgentNode field definitions |
| AgentNode impl plan | `docs/plans/2026-03-02-agentnode-implementation.md` | Implementation approach |
| Architecture alignment | `docs/plans/EVENT_ARCHITECTURE_ALIGNMENT.md` | Event system design |
| Launch plan | `REMORA_LAUNCH_PLAN.md` | Master task list (this project executes it) |

## Testing Infrastructure
- Test command: `python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`
- Known pre-existing failures:
  - `test_lsp_handlers_register_and_advertise_capabilities` — missing `workspace/executeCommand`
  - 2 cairn merge-ops tests (skipped via `--ignore`)
  - 1 benchmark timeout (skipped via `--ignore`)
- Test fakes: `src/remora/testing/fakes.py` (`FakeAsyncOpenAI`, `FakeEventStore`)
- Deprecated shim: `tests/helpers.py` (re-exports from `remora.testing`)

## Decision-Making Framework
- When in doubt, consult `docs/EventBased_Concept.md`
- If the concept doc doesn't cover it, prefer the simpler option (YAGNI)
- Document non-obvious decisions in DECISIONS.md with rationale
