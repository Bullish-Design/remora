# .hidden/ Directory Analysis

## Summary

27 files, all historical. Total ~850KB of old reviews, refactor guides, session logs,
and plans from pre-EventBased architecture. All predate 2026-03-01 except the
Cairn integration refactor.

## Verdict: ALL KEEP (already archived)

The .hidden/ directory is the correct location for these files. They are already
"archived" by being in .hidden/. No action needed — just confirm they should stay.

## Notable files by category:

### Old Code Reviews (5 files, ~100KB)
- CODE_REVIEW.md — 2026-02-18
- CODE_REVIEW (2).md — FunctionGemma root cause analysis
- CODE_REVIEW - Pre 2 track pre hub.md — 2026-02-19
- MODEL_INTERACTION_REVIEW.md — FunctionGemma integration
- HARNESS_IMPROVEMENT_REVIEW.md — FunctionGemma harness review

### Old Refactor Guides (8 files, ~230KB)
- REFACTORING.md — 2026-02-18 refactoring guide
- REVIEW_REFACTOR.md — Implementation plan from old code review
- HARNESS_REFACTOR_GUIDE.md — FunctionGemma harness refactor
- TREESITTER_REFACTOR.md + V2 + CLARIFICATION — Tree-sitter refactor plans
- TEST_REFACTORING_GUIDE.md — Old test suite refactoring
- GRAIL_SCRIPT_REFACTOR.md + GRAIL_RUNTIME_TESTING_REFACTOR.md — Grail refactors

### Infrastructure Plans (4 files, ~80KB)
- VLLM_REFACTOR.md — vLLM server setup plan
- CAIRN_INTEGRATION_REFACTOR.md — Cairn API migration
- HUB_CONCEPT_v2.md + HUB_REFACTORING_GUIDE_v2.md — Old Hub architecture

### Misc (6 files, ~350KB)
- session-ses_38d4.md — 267KB session log (!!). Consider deleting for repo size.
- Workspace_Manager_Rambling.md — Bug fix notes
- DEVELOPMENT_REMAINING.md — Old MVP completion tracker
- ERROR_ANALYSIS.md — Old error analysis
- FINAL_UPDATES.md — Old root cause analysis
- FUTURE_ENHANCEMENTS.md — Discovery pipeline enhancement ideas (may still be relevant)
- REMORA_GRAIL_PYDANTREE_INTEGRATION.md — Old integration plan
- REMORA_VLLM_ISSUES.md — Old vLLM debugging session
- AST_SUMMARY_PLAN.md — AST summary engine plan (standalone library)

## Recommendation

These are fine where they are. The only action items:
1. Consider deleting `session-ses_38d4.md` (267KB session log bloating the repo)
2. `FUTURE_ENHANCEMENTS.md` has some ideas that may still be relevant — flag for review
3. Ensure .hidden/ is in .gitignore (it should be, but verify)
