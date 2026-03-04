# Documentation Rework — ASSUMPTIONS

1. **Target audience**: Developers who will work on/with Remora (not end-users). Docs should be accurate for the current codebase.
2. **Current architecture**: Remora V2 is an event-based reactive swarm system. The EventBased_Concept.md in docs/ is the canonical vision doc per REPO_RULES.md.
3. **Production readiness**: Docs should be clean, non-duplicative, and accurately reflect the current codebase. Stale docs confuse contributors.
4. **The .hidden/ directory**: Contains historical docs that were already "archived". Most should likely be deleted or remain archived.
5. **Root-level .md sprawl**: Many root .md files are one-off reviews/plans that don't belong at the root. They should be moved to .hidden/ or deleted.
6. **Completed projects**: Close Architecture Gaps and Fix Failing Tests are DONE. Docs referencing old state (659 tests, pre-Pydantic-consolidation) are stale.
7. **Test count**: Current suite is 1388 passed / 0 failed / 2 skipped. Any doc citing different numbers is outdated.
