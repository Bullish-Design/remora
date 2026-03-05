# ISSUES — Background Scan Manifest Persistence

## Active Issues
- `ISSUE_001` — Scan manifest never persists, causing full workspace re-scan on every startup
  - Summary: `issues/2026-03-05-initial-analysis/ROOT_CAUSE_ANALYSIS.md`
  - Proposed fixes: `issues/2026-03-05-initial-analysis/PROPOSED_FIXES.md`
  - Implementation plan: `issues/2026-03-05-initial-analysis/IMPLEMENTATION_PLAN.md`

## Historical Pitfalls To Avoid
- **Treating symptoms instead of root cause**: More logging, better preemption help but don't fix manifest persistence
- **Waiting for full scan completion**: 3-4 minutes is too long; users quit before completion
- **All-or-nothing manifest saves**: Single save at end means interrupted scan loses all progress
- **Ignoring SQLite contention**: Large batch_append operations starve interactive paths
- **Assuming scan will complete**: Real-world usage shows frequent interruptions (user quits, editor restarts, system suspend)

## Related Issues from Other Projects
- `lsp-startup-initial-connection/ISSUE_001`: Startup attach delay + submit/panel stall
  - **Connection**: Symptoms of this manifest bug (heavy SQLite writes cause timeouts)
  - **Resolution**: Should be resolved when manifest persists and unchanged files are skipped
