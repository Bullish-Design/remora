# Repo Cleanup Planning — Context

**Project status: COMPLETE**

## Summary

Planning project to analyze the entire remora repo and produce a cleanup plan aligned with the EventBased architecture. All deliverables produced:

- `REPO_CLEANUP_ANALYSIS.md` (1008 lines, 15 sections) — committed as `45e5df7`
- 10 shadow tree notes (per-directory analysis)
- 4-phase execution plan in `PLAN.md`
- Assumptions documented in `ASSUMPTIONS.md`

## Follow-Up Deliverable

`REMORA_LAUNCH_PLAN.md` (858 lines, 7 sections) — consolidates ALL findings from all 4 code reviews into a single deduplicated, prioritized action plan. Supersedes this project's `PLAN.md` as the authoritative execution roadmap.

## Key Discovery

The Option A unification project is marked COMPLETE, but project diagnostics reveal **broken imports still exist** in the LSP layer:
- `lsp/__init__.py` exports deleted `ASTAgentNode` and `ToolSchema`
- `lsp/handlers/actions.py` and `commands.py` reference `ASTAgentNode`
- `lsp/server.py` references undefined `AgentRunner`

This is tracked in `REMORA_LAUNCH_PLAN.md` as item D15.
