# REPO RULES — Background Scan Manifest Persistence

## Log Markers for Validation

### Server Log Markers (`.remora/logs/server-*.log`)

#### Scan Lifecycle
- **Scan start**: `_background_scan: starting`
- **File discovery**: `_background_scan: found 405 source files`
- **File parsed**: `_background_scan: parsed <file> -> <N> nodes`
- **Incremental save**: `_background_scan: incremental manifest save (X/Y files, Z unchanged)`
- **Slow write warning**: `_background_scan: batch_append SLOW ... duration_ms=`
- **Scan completion**: `_background_scan: COMPLETE — X nodes from Y parsed files (Z total, W unchanged skipped, P pauses)`

#### Interactive Operations
- **Chat submit received**: `on_input_submitted: params=`
- **Turn execution start**: `execute_turn: START`
- **Panel request start**: `cmd_get_agent_panel: get_node_at_position START`
- **Panel timeout warning**: `cmd_get_agent_panel: TIMEOUT`
- **Submit timeout warning**: `on_input_submitted: emit_event TIMEOUT`

### Client Log Markers (`.remora/logs/client-*.log`)

#### Startup
- **Setup complete**: `M.setup: COMPLETE`
- **First client check**: `get_client: NO remora clients found!`
- **Connection success**: `ensure_autostart_connected: connected after N startup retries`

#### Interactive Operations
- **Chat command**: `CMD RemoraChat`
- **Input request**: `HANDLER $/remora/requestInput ... sending $/remora/submitInput ... buf_notify sent`
- **Panel timeout**: `panel.do_fetch_agent_data: TIMEOUT`

### Filesystem Markers

#### Manifest State
```bash
# Check if manifest exists
ls .remora/scan-manifest.json

# Check manifest size (number of files)
jq '. | length' .remora/scan-manifest.json

# Check manifest entry format
jq '.[0] | keys' .remora/scan-manifest.json
# Expected: ["mtime_ns", "size"]
```

#### Database State
```bash
# EventStore size
ls -lh .remora/events/events.db
ls -lh .remora/events/events.db-wal

# RemoraDB size
ls -lh .remora/indexer.db
ls -lh .remora/indexer.db-wal
```

## Success Criteria Markers

### Phase 1: Incremental Manifest Saves
**Must Appear in Logs**:
1. `_background_scan: incremental manifest save` (multiple times per scan)
2. `_background_scan: COMPLETE` (after full scan)
3. `X unchanged skipped` where X > 0 on second startup

**Must Exist in Filesystem**:
1. `.remora/scan-manifest.json` exists
2. Manifest has JSON content (not empty)
3. Manifest entries have `mtime_ns` and `size` fields

### Phase 2: Interactive Operations During Scan
**Must Appear in Logs**:
1. `on_input_submitted: params=` (within 2s of client send)
2. `execute_turn: START` (after submit)
3. Zero `panel.do_fetch_agent_data: TIMEOUT` messages

**Must NOT Appear in Logs**:
1. `on_input_submitted: emit_event TIMEOUT`
2. `cmd_get_agent_panel: TIMEOUT`
3. `batch_append SLOW duration_ms=` values >2000ms

## Testing Commands

### Baseline Current State
```bash
# Check current manifest state
ls -lh .remora/scan-manifest.json || echo "Manifest does not exist"

# Find most recent server log
ls -t .remora/logs/server-*.log | head -1

# Check if last scan completed
grep "COMPLETE" $(ls -t .remora/logs/server-*.log | head -1)

# Check skip rate in last scan
grep "unchanged skipped" $(ls -t .remora/logs/server-*.log | head -1)
```

### Validate Fix #1 (Incremental Saves)
```bash
# Delete manifest for fresh test
rm -f .remora/scan-manifest.json

# Start server, wait 30s, kill it
devenv shell -- nv2 remora_demo/companion/demo/harness.py &
NV_PID=$!
sleep 30
kill $NV_PID

# Verify manifest exists
ls -lh .remora/scan-manifest.json
jq '. | length' .remora/scan-manifest.json

# Expected: manifest exists with 50-100 entries
```

### Validate Fix #2 (Interactive Operations)
```bash
# Start server with fresh manifest (triggers full scan)
rm -f .remora/scan-manifest.json
devenv shell -- nv2 remora_demo/companion/demo/harness.py

# In Neovim:
# 1. Wait 5 seconds (scan active)
# 2. Open panel: <leader>ra
# 3. Type message and hit Enter

# Check logs for success
grep "on_input_submitted" .remora/logs/server-*.log | tail -1
grep "TIMEOUT" .remora/logs/client-*.log | tail -5

# Expected:
# - on_input_submitted appears
# - Zero TIMEOUT messages
```

## Debugging Commands

### Scan Progress Monitoring
```bash
# Watch scan in real-time
tail -f .remora/logs/server-*.log | grep -E "(background_scan|parsed|COMPLETE|SLOW)"
```

### Manifest Corruption Check
```bash
# Validate JSON format
jq empty .remora/scan-manifest.json && echo "Valid JSON" || echo "CORRUPTED"

# Check for expected fields
jq 'to_entries[0].value | has("mtime_ns") and has("size")' .remora/scan-manifest.json
```

### SQLite Health Check
```bash
# Check WAL size (should be <2MB after checkpoint)
ls -lh .remora/events/events.db-wal
ls -lh .remora/indexer.db-wal

# Force checkpoint (if needed)
sqlite3 .remora/events/events.db "PRAGMA wal_checkpoint(FULL);"
```

## Known Pitfalls

1. **Manifest exists but is empty `{}`**: Scan started but no files processed yet
2. **Manifest has stale entries**: File deleted but manifest not updated (expected, benign)
3. **Large WAL files (>5MB)**: Checkpoint not running, causing slow writes
4. **`asyncio.sleep(0)` not yielding**: Need `asyncio.sleep(0.05)` or higher for actual yield
5. **Atomic write not atomic**: Use `pathlib.Path.replace()`, not `os.rename()` (former is atomic on POSIX)
