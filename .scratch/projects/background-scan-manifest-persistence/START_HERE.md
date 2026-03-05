# START HERE — Background Scan Manifest Persistence

If you are a new agent/session, do this in order:

1. Read core project files:
   - `ASSUMPTIONS.md`
   - `CONTEXT.md`
   - `PROGRESS.md`
   - `ISSUES.md`

2. Read initial analysis artifacts:
   - `issues/2026-03-05-initial-analysis/ROOT_CAUSE_ANALYSIS.md`
   - `issues/2026-03-05-initial-analysis/PROPOSED_FIXES.md`
   - `issues/2026-03-05-initial-analysis/IMPLEMENTATION_PLAN.md`

3. Verify current state:
   - Check if `.remora/scan-manifest.json` exists
   - Check size of `.remora/events/events.db-wal` (should be <5MB ideally)
   - Run manual startup and monitor scan completion

4. Implementation approach:
   - Start with Fix #1 (incremental manifest saves) - highest impact
   - Validate with full scan completion test
   - Move to Fix #2-4 only after manifest persistence proven

## Quick Reference

**Problem**: Background scan never completes, so manifest never saves, so every startup re-scans all 405 files, causing 8+ second SQLite write locks that block interactive operations.

**Root Cause**: Manifest only saved at end of scan (line 337 of `__main__.py`), but scan takes 3-4 minutes and gets interrupted before completion.

**Critical Fix**: Save manifest incrementally during scan, not just at end.

**Related Files**:
- `src/remora/lsp/__main__.py` (lines 168-349: `_background_scan`)
- `.remora/scan-manifest.json` (does not exist - the problem)
- `.remora/logs/server-*.log` (evidence of incomplete scans)
