# CONTEXT — Background Scan Manifest Persistence

## Start-Here Summary
The background workspace scan never completes because it takes 3-4 minutes for 405 files, but users quit Neovim before completion. The scan manifest is only saved at the very end (line 337 of `__main__.py`), so it never persists. This creates a vicious cycle where every startup re-parses all files, causing 8+ second SQLite write locks that block interactive operations, frustrating users into quitting early again.

## Problem Discovery Timeline

### 2026-03-05: Initial Symptoms
From `lsp-startup-initial-connection` project investigation:
1. Startup takes 7+ seconds before client connects
2. Chat submit disappears (client sends, server never receives)
3. Panel requests timeout repeatedly (4 timeouts in one session)
4. Correlation: `batch_append SLOW duration_ms=8663.8` during panel timeouts

### Root Cause Analysis
Investigation revealed:
1. **No manifest file exists**: `.remora/scan-manifest.json` missing
2. **Scan never completes**: Server log shows only 29/405 files parsed before shutdown
3. **Every startup re-scans everything**: Without manifest, all files treated as "new"
4. **Heavy SQLite contention**: EventStore `batch_append` holds write lock for 8+ seconds
5. **Interactive operations starve**: 2s timeout for emit_event vs 8.6s lock hold time

## Evidence from Logs

### Server Log: 2026-03-05_143406.log
```
[14:34:07.581] INFO  _background_scan: found 405 source files
[14:34:07.704] DEBUG _background_scan: parsed AGENTS.md -> 3 nodes
[14:34:09.126] DEBUG _background_scan: parsed DOCUMENTATION_REWORK.md -> 106 nodes
...
[14:34:13.826] DEBUG _background_scan: parsed docs/ARCHITECTURE.md -> 67 nodes
[14:34:22.737] WARNING _background_scan: batch_append SLOW file=.../EventBased_Concept.md chunk_start=32 chunk_size=32 duration_ms=8663.8
[14:34:22.744] INFO  EventBus.emit: CursorFocusEvent
[END OF LOG - SERVER SHUTDOWN]
```

**Observations**:
- Scan started at 14:34:07, processed 29 files by 14:34:13 (~6 seconds)
- Projected total time: 405 files * (6s / 29 files) = ~84 seconds minimum
- Actual shutdown: 14:34:22 (~15 seconds into scan)
- **NO `_background_scan: COMPLETE` message**
- **NO manifest save** (line 337 never reached)

### Filesystem State
```
.remora/
  events/
    events.db        25M  (EventStore - node/event data)
    events.db-wal    4.1M (write-ahead log, large!)
  indexer.db         2.2M (RemoraDB - proposals/edges)
  indexer.db-wal     1.1M
  scan-manifest.json [DOES NOT EXIST]
```

## The Vicious Cycle

```
┌─────────────────────────────────────────┐
│ 1. No manifest exists                   │
├─────────────────────────────────────────┤
│ 2. Startup scans ALL 405 files          │
├─────────────────────────────────────────┤
│ 3. Scan takes 3-4 minutes               │
├─────────────────────────────────────────┤
│ 4. Heavy SQLite writes block operations │
├─────────────────────────────────────────┤
│ 5. Panel timeouts, submit failures      │
├─────────────────────────────────────────┤
│ 6. User quits before scan completes     │
├─────────────────────────────────────────┤
│ 7. Manifest never saves (line 337)      │
└──────────────┬──────────────────────────┘
               │
               └─────> Back to Step 1
```

## Code Hotspots

### `src/remora/lsp/__main__.py` Lines 168-349
```python
manifest_path = root_path / ".remora" / "scan-manifest.json"

def _load_manifest():
    try:
        data = json.loads(manifest_path.read_text())
        return parse_manifest(data)
    except FileNotFoundError:
        return {}  # ← Returns empty, so NO files skipped

def _save_manifest(data):
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, sort_keys=True))

# ... scan loop ...
for fpath in py_files:
    signature = {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
    next_manifest[relative] = signature

    if existing_manifest.get(relative) == signature:
        skipped_unchanged += 1
        continue  # ← Never happens when manifest is empty

    # ... parse file and emit events ...

# ← Line 337: Only reached if loop completes
try:
    _save_manifest(next_manifest)
except Exception:
    log.warning("failed to save scan manifest %s", manifest_path, exc_info=True)
```

**Problem**: `_save_manifest()` only called ONCE at the very end. If scan is interrupted (user quits, crash, timeout), all progress is lost.

## Related Issues from Parent Project

From `lsp-startup-initial-connection/ISSUE_001.md`:
- Chat submit disappears (server never logs `on_input_submitted`)
- Panel requests timeout 4 times in one session
- Correlation with `batch_append SLOW duration_ms=8663.8`

**Hypothesis**: These are symptoms of the manifest persistence bug. Once manifest saves properly and unchanged files are skipped, SQLite write pressure drops 90%+, eliminating the contention that causes timeouts.

## Why Junior Dev's Approach Was Wrong

The `lsp-startup-initial-connection` project proposed:
1. Add more logging/telemetry
2. Add submit receipt boundary logging
3. Strengthen scan preemption (smaller chunks, more yields)

**Analysis**:
- ✅ #3 is helpful but treats symptoms, not root cause
- ❌ #1-2 add complexity without addressing manifest persistence
- ❌ Missed the fundamental issue: scan never completes, manifest never saves

## Next Steps

See `issues/2026-03-05-initial-analysis/PROPOSED_FIXES.md` for implementation approach.

## 2026-03-05 Implementation Update

Implemented Fix #1 in `src/remora/lsp/__main__.py`:
- Added atomic manifest writer (`.json.tmp` + `replace`) to avoid partial writes.
- Added incremental manifest persistence every 10 processed files during `_background_scan`.
- Kept final manifest save at scan completion.

Added regression coverage in `tests/unit/test_lsp_background_scan_manifest.py`:
- Test starts background scan through `main()` with fakes.
- Blocks scan after 11th file and cancels task before completion.
- Asserts `.remora/scan-manifest.json` already exists and contains at least 10 entries.
- This test failed before code change and passes after code change.

Validation run:
- `devenv shell -- pytest tests/unit/test_lsp_background_scan_manifest.py -q` (pass)
- `devenv shell -- pytest tests/unit/test_llm_config.py -q` (pass)

Current baseline state check from START_HERE:
- `.remora/scan-manifest.json`: missing before fix validation.
- `.remora/events/events.db-wal`: 4.0MB (under 5MB target threshold but still elevated).

Remaining work:
- Manual Neovim startup/interrupt/restart validation in real harness logs.
- Decide whether Fix #2 preemption tuning is still needed after real validation.
