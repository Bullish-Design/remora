# Documentation Rework Analysis — PLAN

## NO SUBAGENTS — Do all work directly. No Task tool. No exceptions.

## Goal
Thorough documentation analysis for production readiness. Identify stale/outdated docs, recommend structure, produce a comprehensive DOCUMENTATION_REWORK.md report.

## Steps

1. **Inventory** — List all documentation files (root .md, docs/, server/, .hidden/)
2. **Analyze root-level .md files** — Read each, categorize KEEP/REVISE/MOVE/DELETE/MERGE, write to `root-level-analysis.md`
3. **Analyze docs/ directory files** — Same treatment, write to `docs-dir-analysis.md`
4. **Analyze .hidden/ files** — Brief triage (most likely DELETE), write to `hidden-dir-analysis.md`
5. **Analyze server/ docs** — Write to `server-docs-analysis.md`
6. **Cross-reference against codebase** — Verify imports, CLI commands, APIs mentioned in docs actually exist. Write to `codebase-crossref.md`
7. **Write DOCUMENTATION_REWORK.md** — Final deliverable with:
   - Current state inventory
   - Accuracy assessment
   - Recommended documentation structure
   - File-by-file action items
   - New docs needed
   - Priority ordering

## Deliverable
`DOCUMENTATION_REWORK.md` in the project root (not in .scratch)

## NO SUBAGENTS — Do all work directly. No Task tool. No exceptions.
