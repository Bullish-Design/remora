# Event-Based Concept Gap Analysis — PLAN

## NO SUBAGENTS — Do all work directly. No Task tool. No exceptions.

## Goal

Systematically compare `docs/EventBased_Concept.md` (the authoritative design document, 2120 lines) against the actual codebase to find major functionality gaps — things called out in the design that are not yet implemented.

## Steps

1. **Read all relevant source files** — core modules, LSP layer, tools, config, extensions.
2. **Check tree-sitter queries** — verify query packs match concept doc expectations.
3. **Write GAP_ANALYSIS.md** — structured gap analysis, section by section against the concept doc.
4. **Finalize** — update CONTEXT.md and PROGRESS.md.

## Acceptance Criteria

- Every section of EventBased_Concept.md has been audited against actual code.
- All gaps documented with: what the concept says, what exists, what's missing.
- GAP_ANALYSIS.md is complete and saved to this project directory.

## NO SUBAGENTS — Do all work directly. No Task tool. No exceptions.
