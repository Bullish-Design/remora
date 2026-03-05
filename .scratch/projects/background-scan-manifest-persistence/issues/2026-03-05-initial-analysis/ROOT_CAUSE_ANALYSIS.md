# ROOT CAUSE ANALYSIS — 2026-03-05 Initial Investigation

## Artifact Set
- Parent project: `.scratch/projects/lsp-startup-initial-connection/`
- Server log: `.remora/logs/server-2026-03-05_143406.log`
- Client log: `.remora/logs/client-2026-03-05_143359.log`
- Filesystem: `.remora/` directory inspection

## Timeline of Discovery

### 1. Initial Symptoms (From Parent Project)
**Time**: 2026-03-05 14:33:59 - 14:34:22

**Observed**:
- Startup attach delayed by 7 seconds (13 retries)
- Chat submit sent by client but never received by server handler
- Panel requests timed out 4 times during normal cursor movement
- `batch_append SLOW duration_ms=8663.8` warning in server log

**Initial Hypothesis**: SQLite write contention starving interactive operations

### 2. Investigation: Why Are Writes So Heavy?
**Question**: What is causing 8.6-second batch_append operations?

**Discovery**:
```bash
$ grep "_background_scan: found.*source files" server.log
found 405 source files

$ grep -c "_background_scan: parsed" server.log
29

$ ls .remora/scan-manifest.json
ls: cannot access '.remora/scan-manifest.json': No such file exists
```

**Analysis**:
- Scan should process 405 files
- Only 29 files processed before shutdown
- NO manifest file exists
- **Conclusion**: Every startup re-scans entire workspace from scratch

### 3. Why Doesn't Manifest Exist?
**Code Review**: `src/remora/lsp/__main__.py:336-339`

```python
try:
    _save_manifest(next_manifest)
except Exception:
    log.warning("failed to save scan manifest %s", manifest_path, exc_info=True)
```

**Location**: Line 337, INSIDE the scan loop's exception handler, AFTER all files processed

**Discovery**: Manifest is only saved ONCE at the very end of scan loop. If scan is interrupted (user quits, timeout, crash), **manifest never saves**.

### 4. Why Is Scan So Slow?
**Math**:
- 29 files in ~13 seconds = ~0.45 seconds per file average
- 405 files * 0.45s/file = **182 seconds (3+ minutes)**
- But log shows server shutdown at 15 seconds

**Why So Slow?**:
1. **Heavy parsing**: markdown files with 100+ nodes (DOCUMENTATION_REWORK.md → 106 nodes)
2. **SQLite writes**: Each node emits NodeDiscoveredEvent → EventStore.batch_append
3. **No caching**: Without manifest, ALL files parsed every time
4. **WAL buildup**: EventStore WAL is 4.1MB (large, needs checkpoint)

### 5. The Vicious Cycle
```
NO MANIFEST
    ↓
SCAN ALL 405 FILES (3-4 min)
    ↓
HEAVY SQLITE WRITES (8+ sec locks)
    ↓
INTERACTIVE OPS TIMEOUT
    ↓
USER QUITS IN FRUSTRATION
    ↓
SCAN NEVER COMPLETES
    ↓
MANIFEST NEVER SAVES
    ↓
[BACK TO TOP]
```

## Root Cause Statement

**The background workspace scan never completes because:**

1. **Duration**: Full scan takes 3-4 minutes for 405 files
2. **User Behavior**: Users quit/restart Neovim before 3-4 minutes
3. **Manifest Design**: Manifest only saved at end (line 337), not incrementally
4. **Result**: Manifest never persists, so next startup re-scans everything again

**Why This Causes Interactive Operation Failures:**

1. **SQLite Contention**: Scanning emits thousands of events via `batch_append`
2. **Exclusive Locks**: SQLite write locks block concurrent operations for 8+ seconds
3. **Timeout Mismatch**: Interactive operations have 1-2 second timeouts
4. **Starvation**: Chat submit (2s timeout) and panel fetch (1.5s timeout) fail during scan

## Falsification Evidence

**What WOULD indicate a different root cause:**
- Manifest file exists and is up-to-date → FALSIFIED (file doesn't exist)
- Scan completes but manifest fails to save → FALSIFIED (scan never reaches line 337)
- SQLite writes are fast (<100ms) → FALSIFIED (8.6 seconds observed)
- Interactive operations succeed during scan → FALSIFIED (4 timeouts observed)

**Confidence Level**: HIGH (95%+)

## Affected Code Paths

### Primary
- `src/remora/lsp/__main__.py:168-349` (_background_scan function)
  - Line 170-187: manifest load/save helpers
  - Line 226-228: skip unchanged files (never triggers without manifest)
  - Line 337: manifest save (only reached after full scan)

### Secondary (Symptoms)
- `src/remora/lsp/notifications.py:42-144` (on_input_submitted timeout)
- `src/remora/lsp/handlers/commands.py` (cmd_get_agent_panel timeout)
- `src/remora/core/event_store.py` (batch_append blocking)

## Next Steps

See `PROPOSED_FIXES.md` for solution approach.
