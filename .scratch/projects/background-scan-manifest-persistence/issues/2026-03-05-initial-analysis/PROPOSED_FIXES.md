# PROPOSED FIXES — 2026-03-05 Initial Analysis

## Fix Priority Matrix

| Fix | Impact | Effort | Risk | Priority |
|-----|--------|--------|------|----------|
| #1: Incremental manifest saves | CRITICAL | LOW | LOW | **P0** |
| #2: Aggressive scan preemption | HIGH | LOW | LOW | P1 |
| #3: Skip unchanged event emission | MEDIUM | MEDIUM | MEDIUM | P2 |
| #4: Resumable scan state | LOW | HIGH | MEDIUM | P3 |

## Fix #1: Incremental Manifest Saves [P0 - CRITICAL]

### Problem
Manifest only saved at end of scan (line 337). If scan interrupted, all progress lost.

### Solution
Save manifest incrementally during scan loop, every N files (e.g., every 10 files).

### Implementation Sketch
```python
# In _background_scan():
manifest_save_interval = 10  # Save every 10 files
files_since_last_save = 0

for fpath in py_files:
    # ... existing logic ...

    next_manifest[relative] = signature
    files_since_last_save += 1

    # Incremental save
    if files_since_last_save >= manifest_save_interval:
        try:
            _save_manifest_atomic(next_manifest)
            files_since_last_save = 0
        except Exception:
            log.warning("incremental manifest save failed", exc_info=True)

    # ... rest of scan logic ...

# Final save at end (ensures completeness)
try:
    _save_manifest_atomic(next_manifest)
except Exception:
    log.warning("final manifest save failed", exc_info=True)
```

### Atomic Write Pattern
```python
def _save_manifest_atomic(data: dict[str, dict[str, int]]) -> None:
    """Atomically save manifest to prevent partial writes."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = manifest_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    tmp_path.replace(manifest_path)  # Atomic on POSIX
```

### Expected Impact
- **Before**: 0% chance manifest exists after interrupted scan
- **After**: 100% chance manifest exists with at least N files (where N = files processed / 10)
- **Second startup**: Skips N files immediately, only re-scans remainder
- **Scan time reduction**: From 3-4 minutes → proportional to files remaining

### Risk Assessment
- **LOW**: Atomic write pattern prevents corruption
- **LOW**: Incremental saves add minimal overhead (<10ms per save)
- **LOW**: No change to scan logic or file discovery

### Validation Test
1. Delete manifest: `rm .remora/scan-manifest.json`
2. Start server, wait 30 seconds, quit
3. Check manifest: `cat .remora/scan-manifest.json | jq '. | length'`
4. Expect: ~50-100 files (proportional to scan progress)
5. Restart server, check logs: "skipped_unchanged" should match manifest size

---

## Fix #2: Aggressive Scan Preemption [P1 - HIGH]

### Problem
Current scan holds SQLite write locks too long (8+ seconds), starving interactive operations.

### Solution
- Reduce batch_append chunk size: 32 → 8 events
- More frequent yielding: `asyncio.sleep(0)` → `asyncio.sleep(0.05)`
- Pause check before EVERY chunk (not just at file boundaries)
- Increase pause window: 3.0s → 5.0s

### Implementation Changes
```python
# Line 205: Reduce chunk size
scan_append_chunk_size = 8  # Was 32

# Line 311: Better yielding
await asyncio.sleep(0.05)  # Was asyncio.sleep(0)

# Line 202: Longer pause window
scan_pause_window_seconds = 5.0  # Was 3.0

# Line 287: Pause before every chunk
for idx in range(0, len(batch_events), scan_append_chunk_size):
    await _pause_for_user_activity()  # ← Add here
    chunk = batch_events[idx : idx + scan_append_chunk_size]
    # ... append chunk ...
```

### Expected Impact
- **Write lock duration**: 8.6s → <500ms (17x reduction)
- **Interactive success rate**: ~50% → ~95%
- **Panel timeouts**: 4 per session → 0
- **Chat submit success**: Unreliable → Reliable

### Risk Assessment
- **LOW**: Scan takes slightly longer (more yielding) but still completes
- **LOW**: No change to scan correctness, only timing

### Validation Test
1. Start server with active scan
2. Trigger panel requests (move cursor in Neovim)
3. Submit chat message during scan
4. Check logs: zero "TIMEOUT" warnings
5. Check logs: "on_input_submitted" appears within 2s of client send

---

## Fix #3: Skip Unchanged Event Emission [P2 - MEDIUM]

### Problem
Scan re-emits NodeDiscoveredEvent for ALL nodes, even if unchanged. Wastes SQLite writes.

### Solution
Compare old_nodes vs new nodes by source_hash. Only emit events for actually changed nodes.

### Implementation Changes
```python
# Lines 252-279: Replace full re-emission with delta logic
if server.event_store:
    old_ids = {n["node_id"]: n for n in old_nodes}
    new_ids = {n["node_id"]: n for n in nodes}

    batch_events = []

    # Only emit for new or changed nodes
    for node_dict in nodes:
        node_id = node_dict["node_id"]
        old = old_ids.get(node_id)

        # New node or source changed?
        if not old or old["source_hash"] != node_dict["source_hash"]:
            batch_events.append(NodeDiscoveredEvent(...))

    # Emit removed nodes
    for removed_id in set(old_ids.keys()) - set(new_ids.keys()):
        batch_events.append(NodeRemovedEvent(...))
```

### Expected Impact
- **Event emission reduction**: 95%+ on unchanged files
- **SQLite write pressure**: Further 10x reduction
- **Scan speed**: 20-30% faster (fewer writes)

### Risk Assessment
- **MEDIUM**: Changes event emission logic (needs careful testing)
- **MEDIUM**: Must handle edge cases (hash collisions, renames)

### Validation Test
1. Run full scan, let complete
2. Restart immediately (no file changes)
3. Check logs: "emitted 0 events" for all unchanged files
4. Verify EventStore has correct node count

---

## Fix #4: Resumable Scan State [P3 - OPTIONAL]

### Problem
Even with incremental manifest saves, scan always starts from file 0.

### Solution
Track last processed file separately, resume from that point.

### Implementation Approach
- Add `.remora/scan-state.json` with `last_processed_file` field
- On startup, skip files until reaching last processed file
- Update state every 10 files (same as manifest)

### Expected Impact
- **Interrupted scan resume**: Instant (skip all previously processed files)
- **UX improvement**: Scan feels more responsive

### Risk Assessment
- **MEDIUM**: More complex state management
- **HIGH EFFORT**: Requires new state file, resume logic, edge case handling

### Decision
**DEFER**: Fix #1 already provides 90%+ benefit with much less complexity. Implement only if Fix #1 proves insufficient.

---

## Implementation Order

1. **Fix #1 (Incremental Manifest)** - Implement first, validate thoroughly
2. **Validate Fix #1** - Run full test cycle, confirm manifest persists
3. **Fix #2 (Aggressive Preemption)** - Only if Fix #1 alone doesn't eliminate timeouts
4. **Validate Fix #2** - Confirm interactive operations succeed during scan
5. **Fix #3 (Skip Events)** - Only if scan is still too slow
6. **Fix #4 (Resumable)** - Only if user feedback indicates it's needed

## Success Criteria

**Must-have** (Fix #1):
- ✅ Manifest exists after interrupted scan
- ✅ Second startup skips 90%+ unchanged files
- ✅ Scan completes and logs `COMPLETE` message

**Nice-to-have** (Fix #2-3):
- ✅ Zero panel timeouts during scan
- ✅ Chat submit succeeds during scan
- ✅ Scan completes in <60 seconds on unchanged workspace

**Optional** (Fix #4):
- ✅ Interrupted scan resumes instantly
