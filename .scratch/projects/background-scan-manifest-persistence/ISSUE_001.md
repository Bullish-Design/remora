# ISSUE_001 — Scan Manifest Never Persists

## Status
OPEN

## Summary
Background workspace scan never completes (takes 3-4 minutes, user quits before completion), so manifest never saves (line 337 only reached after full scan). This causes every startup to re-scan all 405 files, generating heavy SQLite writes (8+ second locks) that block interactive operations (chat submit, panel requests).

## Primary Artifacts
- `issues/2026-03-05-initial-analysis/ROOT_CAUSE_ANALYSIS.md` - Detailed investigation
- `issues/2026-03-05-initial-analysis/PROPOSED_FIXES.md` - Solution approaches
- `issues/2026-03-05-initial-analysis/IMPLEMENTATION_PLAN.md` - Step-by-step fix

## Affected Code
- `src/remora/lsp/__main__.py` lines 168-349 (`_background_scan` function)
  - Line 170-187: manifest load/save helpers
  - Line 226-228: unchanged file skip logic (never triggers without manifest)
  - Line 337: manifest save (only after full scan completion)

## Success Condition
Three proofs:
1. **Manifest persists**: `.remora/scan-manifest.json` exists after interrupted scan (30s runtime)
2. **Incremental progress**: Second startup skips 90%+ unchanged files
3. **Interactive operations succeed**: Chat submit and panel requests complete during active scan without timeouts

## Evidence

### Filesystem State (2026-03-05)
```bash
$ ls .remora/scan-manifest.json
ls: cannot access '.remora/scan-manifest.json': No such file exists

$ ls -lh .remora/events/events.db-wal
.rw-r--r--  4.1M andrew  5 Mar 14:34   events.db-wal  # Large WAL, needs checkpoint
```

### Server Log (server-2026-03-05_143406.log)
```
[14:34:07.581] INFO  _background_scan: found 405 source files
[14:34:07.704] DEBUG _background_scan: parsed AGENTS.md -> 3 nodes
...
[14:34:13.826] DEBUG _background_scan: parsed docs/ARCHITECTURE.md -> 67 nodes
[14:34:22.737] WARNING _background_scan: batch_append SLOW ... duration_ms=8663.8
[END OF LOG - NO COMPLETE MESSAGE]
```

**Analysis**:
- Only 29/405 files parsed before shutdown
- No `_background_scan: COMPLETE` message
- Manifest save at line 337 never reached

### Related Symptoms
From parent project `lsp-startup-initial-connection/ISSUE_001`:
- Chat submit sent by client but never received by server
- Panel requests timed out 4 times in one session
- `batch_append SLOW duration_ms=8663.8` correlates with timeouts

**Hypothesis**: These symptoms are caused by the missing manifest. Once manifest persists and unchanged files are skipped, SQLite write pressure drops 90%+, eliminating timeout conditions.

## Implementation Priority
**P0 - CRITICAL**: Fix #1 (Incremental manifest saves) blocks all other work and causes cascading failures in interactive operations.
