# IMPLEMENTATION PLAN — 2026-03-05 Initial Analysis

## Goal
Make background scan manifest persist incrementally so unchanged files are skipped on subsequent startups, eliminating SQLite write contention that blocks interactive operations.

## Phase 1: Implement Fix #1 (Incremental Manifest Saves)

### Step 1: Baseline Current State
**Commands**:
```bash
# Check if manifest exists
ls -lh .remora/scan-manifest.json

# If exists, back it up and delete
if [ -f .remora/scan-manifest.json ]; then
  cp .remora/scan-manifest.json .remora/scan-manifest.json.backup
  rm .remora/scan-manifest.json
fi

# Start fresh server and monitor
devenv shell -- nv2 remora_demo/companion/demo/harness.py

# In another terminal, watch scan progress
tail -f .remora/logs/server-*.log | grep -E "(background_scan|parsed|COMPLETE)"
```

**Expected Baseline**:
- No manifest file exists initially
- Scan processes some files, then stops (user quits or timeout)
- No `COMPLETE` message in logs
- No manifest file exists after shutdown

### Step 2: Modify _background_scan Function
**File**: `src/remora/lsp/__main__.py`

**Changes**:

1. **Add atomic manifest save helper** (after line 187):
```python
def _save_manifest_atomic(data: dict[str, dict[str, int]]) -> None:
    """Atomically save manifest using tmp file + rename pattern."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = manifest_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    tmp_path.replace(manifest_path)  # Atomic on POSIX
    log.debug("_save_manifest_atomic: saved %d files", len(data))
```

2. **Update _save_manifest to use atomic version** (replace line 185-187):
```python
def _save_manifest(data: dict[str, dict[str, int]]) -> None:
    _save_manifest_atomic(data)
```

3. **Add incremental save logic in scan loop** (after line 225):
```python
# Configuration
manifest_save_interval = 10  # Save every N files
files_since_last_save = 0

for fpath in py_files:
    try:
        relative = str(fpath.relative_to(root_path))
        stat = fpath.stat()
        signature = {"mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
        next_manifest[relative] = signature
        files_since_last_save += 1  # ← Add counter

        if existing_manifest.get(relative) == signature:
            skipped_unchanged += 1
            continue

        # ... existing parse/emit logic ...

        count += len(nodes)
        parsed += 1
        await asyncio.sleep(0.1)
        log.debug("_background_scan: parsed %s -> %d nodes", fpath.relative_to(root_path), len(nodes))

        # ← INCREMENTAL SAVE (after successful parse)
        if files_since_last_save >= manifest_save_interval:
            try:
                _save_manifest_atomic(next_manifest)
                files_since_last_save = 0
                log.info(
                    "_background_scan: incremental manifest save (%d/%d files, %d unchanged)",
                    len(next_manifest),
                    len(py_files),
                    skipped_unchanged,
                )
            except Exception:
                log.warning("_background_scan: incremental manifest save failed", exc_info=True)

    except Exception:
        log.warning("_background_scan: failed to parse %s", fpath, exc_info=True)
```

4. **Keep final save at end** (existing line 336-339, no change needed)

### Step 3: Validate Incremental Saves
**Test 1: Interrupted Scan Creates Manifest**
```bash
# Delete manifest
rm -f .remora/scan-manifest.json

# Start server
devenv shell -- nv2 remora_demo/companion/demo/harness.py &
NV_PID=$!

# Wait 30 seconds (should process ~60-100 files)
sleep 30

# Quit Neovim
kill $NV_PID

# Check manifest exists and has content
ls -lh .remora/scan-manifest.json
jq '. | length' .remora/scan-manifest.json

# Expected: manifest exists with 60-100 entries
```

**Test 2: Second Startup Skips Unchanged Files**
```bash
# Start server again (manifest now exists)
devenv shell -- nv2 remora_demo/companion/demo/harness.py

# In another terminal, monitor logs
tail -f .remora/logs/server-*.log | grep -E "(skipped_unchanged|parsed|COMPLETE)"

# Expected:
# - "skipped_unchanged" count matches manifest size
# - Only new files are parsed
# - Scan completes much faster
```

**Test 3: Full Scan Completion**
```bash
# Let scan run to completion (don't quit)
devenv shell -- nv2 remora_demo/companion/demo/harness.py

# Wait for COMPLETE message
# Expected:
# - "_background_scan: COMPLETE" in logs
# - manifest has all 405 files
# - Next startup skips 100% of files
```

### Step 4: Verify Interactive Operations
**Test 4: Chat Submit During Scan**
```bash
# Delete manifest to trigger full scan
rm -f .remora/scan-manifest.json

# Start Neovim
devenv shell -- nv2 remora_demo/companion/demo/harness.py

# In Neovim:
# 1. Wait 5 seconds (scan is active)
# 2. Open Remora panel: <leader>ra
# 3. Type a message and hit Enter
# 4. Verify message appears in panel

# Check logs:
grep "on_input_submitted" .remora/logs/server-*.log

# Expected: "on_input_submitted: params=" appears within 2 seconds
```

**Test 5: Panel Requests During Scan**
```bash
# Start Neovim with active scan
devenv shell -- nv2 remora_demo/companion/demo/harness.py

# In Neovim:
# 1. Open panel: <leader>ra
# 2. Move cursor to different agents rapidly
# 3. Panel should update without "TIMEOUT" errors

# Check client logs:
grep "TIMEOUT" .remora/logs/client-*.log

# Expected: zero TIMEOUT messages
```

## Phase 2: Implement Fix #2 (Optional - Only If Needed)

### Condition
Only proceed if Phase 1 testing shows:
- Interactive operations still timing out during scan, OR
- Scan still takes >2 minutes on unchanged workspace

### Changes
See `PROPOSED_FIXES.md` Fix #2 section for implementation details.

## Phase 3: Implement Fix #3 (Optional - Only If Needed)

### Condition
Only proceed if scan is still too slow after Fix #1+2.

### Changes
See `PROPOSED_FIXES.md` Fix #3 section for implementation details.

## Success Metrics

### Must Pass (Fix #1)
- [ ] Manifest exists after interrupted scan (30s runtime)
- [ ] Manifest has 50-100 entries after 30s scan
- [ ] Second startup skips files matching manifest size
- [ ] Full scan completes and logs `COMPLETE` message
- [ ] Manifest has all 405 files after completion
- [ ] Third startup skips 100% of files and completes in <10s scan time

### Should Pass (Interactive Operations)
- [ ] Chat submit reaches `on_input_submitted` during active scan
- [ ] Panel requests complete without TIMEOUT during active scan
- [ ] No `batch_append SLOW` warnings after unchanged files are skipped

### Nice To Have (Performance)
- [ ] Second startup scan completes in <60s (vs 3-4 minutes initially)
- [ ] SQLite WAL size stays <2MB after checkpoint
- [ ] CPU usage during scan <50% average

## Rollback Plan

If implementation causes regressions:

1. **Revert changes**: Git restore `src/remora/lsp/__main__.py`
2. **Delete corrupt manifest**: `rm .remora/scan-manifest.json`
3. **Restart server**: Fresh start with original behavior
4. **Document failure mode**: Create `ISSUE_002.md` with details

## Known Risks

### Risk 1: Manifest Corruption
**Probability**: LOW
**Impact**: MEDIUM (scan re-processes all files, but recovers)
**Mitigation**: Atomic write pattern (tmp + rename)

### Risk 2: Partial Manifest Causes Incorrect Skips
**Probability**: LOW
**Impact**: HIGH (missing nodes in EventStore)
**Mitigation**: Validate manifest on load, delete if invalid

### Risk 3: Incremental Saves Add Too Much Overhead
**Probability**: VERY LOW
**Impact**: LOW (scan takes slightly longer)
**Mitigation**: Adjust save interval (10 → 20 files)

## Next Actions

1. Read this plan thoroughly
2. Verify understanding of atomic write pattern
3. Implement Step 2 changes to `__main__.py`
4. Run validation tests from Step 3
5. Document results and update `PROGRESS.md`
