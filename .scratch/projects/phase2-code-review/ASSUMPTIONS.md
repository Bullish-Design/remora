# Phase 2 Code Review — Assumptions

## ABSOLUTE RULE — NO SUBAGENTS
**NEVER use the Task tool.** Do all work directly — read files, search, write, edit, run commands yourself. No delegation. No exceptions.

## Purpose
Comprehensive code review of the entire Remora codebase (excluding remora_demo/) after
the Option A LSP→EventStore unification. Verify architectural alignment with the
EventBased_Concept.md vision, code quality, integration completeness, and test coverage.

## Scope
- `src/remora/` — all subpackages (core, lsp, service, ui, adapters, cli, models, utils, nvim)
- `tests/` — all test files
- Excludes: `remora_demo/` (being worked on separately)

## Success criteria
- Architecture matches EventBased_Concept.md vision
- No dead code, no stale abstractions from pre-unification
- All modules are integrated and functional
- Test suite is thorough with no gaps in critical paths
- Code is clean, elegant, and follows DRY/YAGNI

## Review dimensions
1. **Architecture alignment** — does code match the vision?
2. **Code quality** — readability, correctness, edge cases
3. **Integration** — do modules work together coherently?
4. **Dead code** — stale imports, unused functions, orphaned modules
5. **Test coverage** — gaps, quality of assertions, missing edge cases

---

## REMINDER — NO SUBAGENTS
**NEVER use the Task tool.** This rule is absolute and non-negotiable.
