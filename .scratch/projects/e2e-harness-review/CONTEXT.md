# CONTEXT: E2E Harness Review

## Current State

**PROJECT COMPLETE.** The consolidated review document `E2E_HARNESS_UPDATES.md` has been written.

## What Happened

1. Updated `verify-e2e-live` PROGRESS.md and CONTEXT.md with final results (they were stale)
2. Created this project with PLAN.md, ASSUMPTIONS.md
3. Read all 12 scenario reports from verify-e2e-live
4. Read harness.py (510 lines) and keys.py (253 lines)
5. Read 4 key scenario files (chat, rewrite, golden_path, reject) for code reference
6. Wrote `E2E_HARNESS_UPDATES.md` (~500 lines) covering all findings

## Key Deliverable

`.scratch/projects/e2e-harness-review/E2E_HARNESS_UPDATES.md`

## Next Steps (if continuing)

The review document is ready for implementation. The priority order is:
1. **P0**: Add `wait_for_lsp_ready()` to keys.py, add assertions to all scenarios
2. **P1**: Fix focus management, add chat state isolation, add `wait_for_chat_prompt()`
3. **P2**: Agent discovery retry, LLM response verification
4. **P3**: Stronger panel_nav assertions, extension-specific verification
