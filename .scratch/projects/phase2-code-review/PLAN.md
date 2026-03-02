# Phase 2 Code Review — Plan

## ABSOLUTE RULE — NO SUBAGENTS
**NEVER use the Task tool.** Do all work directly — read files, search, write, edit, run commands yourself. No delegation. No exceptions.

---

## Steps

1. **Read vision doc** — `docs/EventBased_Concept.md` for reference (DONE)
2. **Review all source files** in `src/remora/` excluding `remora_demo/` (DONE)
3. **Persist source findings** to `.scratch/projects/phase2-code-review/source-findings.md` (DONE)
4. **Review all test files** in `tests/` — structure, coverage, quality, gaps (IN PROGRESS)
5. **Cross-cutting analysis** — architecture alignment, integration coherence, dead code synthesis
6. **Write the report** — `EVENT_BASED_PHASE_2_CODE_REVIEW.md` at repo root
   - Write TOC first, save to file
   - Go section by section, appending
7. **Update project files** — CONTEXT.md, PROGRESS.md with final summary

## Acceptance Criteria

- Report covers all 5 review dimensions from ASSUMPTIONS.md
- Every CRITICAL/HIGH finding has a concrete recommendation
- Test gaps are identified with specific suggestions
- Report is saved to `EVENT_BASED_PHASE_2_CODE_REVIEW.md`

---

## REMINDER — NO SUBAGENTS
**NEVER use the Task tool.** This rule is absolute and non-negotiable.
