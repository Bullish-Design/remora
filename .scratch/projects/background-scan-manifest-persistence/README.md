# Background Scan Manifest Persistence

**Status**: ACTIVE
**Created**: 2026-03-05
**Priority**: P0 - CRITICAL

## Quick Summary

The background workspace scan never completes because it takes 3-4 minutes but users quit before completion. The manifest is only saved at the very end (line 337 of `__main__.py`), so it never persists. This creates a vicious cycle where every startup re-scans all 405 files, causing 8+ second SQLite write locks that block interactive operations (chat submit, panel requests).

## Critical Path Fix

**Implement incremental manifest saves** (save every 10 files during scan loop, not just at end). This breaks the cycle: interrupted scans save partial progress, subsequent startups skip unchanged files, SQLite write pressure drops 90%+.

## Project Structure

```
.scratch/projects/background-scan-manifest-persistence/
├── START_HERE.md              ← Entry point for new agents/sessions
├── README.md                  ← This file
├── ASSUMPTIONS.md             ← Constraints, success metrics, non-goals
├── CONTEXT.md                 ← Problem description and vicious cycle
├── PROGRESS.md                ← Phase tracking and completion status
├── ISSUES.md                  ← Issue index
├── ISSUE_001.md               ← Main issue summary
├── REPO_RULES.md              ← Log markers and validation commands
└── issues/
    └── 2026-03-05-initial-analysis/
        ├── ROOT_CAUSE_ANALYSIS.md    ← Investigation timeline and evidence
        ├── PROPOSED_FIXES.md         ← 4 fixes prioritized (P0-P3)
        └── IMPLEMENTATION_PLAN.md    ← Step-by-step implementation guide
```

## For New Agents/Sessions

1. **Start here**: Read `START_HERE.md`
2. **Understand the problem**: Read `CONTEXT.md`
3. **Review analysis**: Read `issues/2026-03-05-initial-analysis/ROOT_CAUSE_ANALYSIS.md`
4. **Choose approach**: Read `issues/2026-03-05-initial-analysis/PROPOSED_FIXES.md`
5. **Implement**: Follow `issues/2026-03-05-initial-analysis/IMPLEMENTATION_PLAN.md`
6. **Validate**: Use commands from `REPO_RULES.md`
7. **Update progress**: Mark phases complete in `PROGRESS.md`

## Key Metrics

### Current State (Broken)
- Manifest exists: ❌ NO
- Files skipped on startup: 0/405 (0%)
- Scan time on second startup: 3-4 minutes
- Interactive operations during scan: ~50% failure rate
- Panel timeouts per session: 4+

### Target State (Fixed)
- Manifest exists: ✅ YES (even after interrupted scan)
- Files skipped on startup: 360+/405 (90%+)
- Scan time on second startup: <30 seconds
- Interactive operations during scan: 95%+ success rate
- Panel timeouts per session: 0

## Related Projects

- **Parent**: `.scratch/projects/lsp-startup-initial-connection/`
  - Original investigation that discovered this issue
  - Junior dev's approach (more logging, better preemption) treated symptoms
  - This project addresses root cause (manifest persistence)

## Files to Modify

**Primary**:
- `src/remora/lsp/__main__.py` lines 168-349 (`_background_scan` function)

**No other files need changes for Fix #1** (incremental manifest saves).

## Quick Validation

```bash
# Check current state
ls .remora/scan-manifest.json || echo "Manifest missing (broken)"

# After implementing fix, test interrupted scan
rm -f .remora/scan-manifest.json
devenv shell -- nv2 remora_demo/companion/demo/harness.py &
sleep 30 && kill $!
ls .remora/scan-manifest.json && echo "Manifest persists (fixed)" || echo "Still broken"
```

## Contact / History

- **Discovered by**: Investigation session 2026-03-05
- **Root cause confirmed**: 2026-03-05 via log analysis and code review
- **Solution designed**: 2026-03-05 (Fix #1: incremental manifest saves)
- **Implementation status**: PENDING

## Success Definition

**Fix is successful when**:
1. Manifest file exists after 30-second interrupted scan
2. Second startup skips 90%+ of unchanged files
3. Chat submit and panel requests succeed during active scan
4. No more "batch_append SLOW" warnings on unchanged workspace
