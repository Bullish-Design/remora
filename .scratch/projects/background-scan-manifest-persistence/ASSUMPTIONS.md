# ASSUMPTIONS — Background Scan Manifest Persistence

## Purpose
Fix the background scan manifest persistence so startup doesn't re-parse the entire workspace on every launch, eliminating 8+ second SQLite write locks that block interactive operations (chat submit, panel requests).

## User-Priority Outcomes
- Background scan completes successfully and saves manifest
- Subsequent startups skip unchanged files (should be 90%+ of workspace)
- SQLite write lock contention reduced by 10x or more
- Interactive operations (chat submit, panel fetch) succeed within timeout windows
- Scan can be interrupted and resumed without losing all progress

## Constraints
- Maintain existing scan logic and file discovery (don't change what gets scanned)
- Preserve manifest format (mtime_ns + size signature)
- Keep scan preemption hooks for user activity
- Use `devenv shell --` for all runtime/test commands
- Prefer minimal, falsifiable changes (one causal lever per pass)
- NO SUBAGENTS

## Definitions of Done
- **Manifest persists**: `.remora/scan-manifest.json` exists after scan, even if interrupted mid-way
- **Incremental progress**: Manifest updated every N files (e.g., every 10 files)
- **Unchanged files skipped**: Log shows "X unchanged skipped" matching majority of workspace
- **Scan completes**: Log contains `_background_scan: COMPLETE` message
- **Interactive operations succeed**: No panel timeout storms, chat submit reaches server handler
- **Idempotent restarts**: Second startup after full scan completes in <2 seconds of scan time

## Non-Goals (for this project)
- Optimizing parser performance or scan speed beyond manifest persistence
- Rewriting EventStore or SQLite architecture
- Changing scan file discovery logic or supported extensions
- Implementing distributed/parallel scanning
- Tuning SQLite WAL checkpoint behavior (separate concern)

## Success Metrics
- Manifest file exists and has content after interrupted scan
- `skipped_unchanged` count in logs shows >90% skip rate on second startup
- Total scan time on second startup: <30 seconds (vs 3-4 minutes currently)
- Zero `batch_append SLOW` warnings on second startup
- Zero panel timeout warnings during/after scan
