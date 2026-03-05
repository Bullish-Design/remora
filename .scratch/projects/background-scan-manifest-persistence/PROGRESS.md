# PROGRESS — Background Scan Manifest Persistence

## Phase 1: Root Cause Analysis — COMPLETE
- [x] Investigated startup delay and interactive operation failures
- [x] Discovered missing manifest file
- [x] Traced scan completion failure (interrupted at 29/405 files)
- [x] Identified vicious cycle: no manifest → full rescan → slow → interrupted → no manifest
- [x] Analyzed SQLite write contention (8.6s batch_append)
- [x] Documented evidence in `issues/2026-03-05-initial-analysis/`

## Phase 2: Design Solution — PENDING
- [ ] Review proposed fixes and prioritize
- [ ] Design incremental manifest save strategy (every N files? after each file?)
- [ ] Determine manifest update granularity vs performance trade-off
- [ ] Consider atomic write requirements (tmp file + rename pattern)
- [ ] Plan validation strategy for manifest correctness

## Phase 3: Implement Fix #1 (Incremental Manifest) — PENDING
- [ ] Add `_save_manifest_incremental()` helper
- [ ] Integrate incremental saves into scan loop (every 10 files)
- [ ] Use atomic write pattern (write to .tmp, then rename)
- [ ] Add error handling for partial manifest corruption
- [ ] Preserve existing manifest save at end for completeness

## Phase 4: Validate Fix #1 — PENDING
- [ ] Delete existing manifest (if any): `rm .remora/scan-manifest.json`
- [ ] Start server and monitor scan progress
- [ ] Interrupt scan at ~50% completion (quit Neovim)
- [ ] Verify manifest exists and has ~50% of files
- [ ] Restart server and verify skipped file count matches manifest entries
- [ ] Let scan complete and verify final manifest has all files
- [ ] Third startup should skip 100% of files

## Phase 5: Implement Fix #2 (Aggressive Preemption) — PENDING
- [ ] Reduce chunk size from 32 → 8 events
- [ ] Change `asyncio.sleep(0)` → `asyncio.sleep(0.05)` between chunks
- [ ] Add pause check BEFORE every chunk (not just at file boundaries)
- [ ] Test interactive operations during active scan

## Phase 6: Implement Fix #3 (Skip Unchanged Events) — PENDING
- [ ] Compare old_nodes vs new nodes by source_hash
- [ ] Only emit NodeDiscoveredEvent for actually changed nodes
- [ ] Only emit NodeRemovedEvent for nodes that actually disappeared
- [ ] Measure event emission reduction (expect 90%+ on unchanged files)

## Phase 7: Implement Fix #4 (Resumable Scan) — OPTIONAL
- [ ] Track scan progress separately from manifest
- [ ] Resume from last processed file on restart
- [ ] Handle edge cases (manifest exists but scan incomplete)

## Phase 8: Final Validation — PENDING
- [ ] Fresh workspace scan from scratch (no manifest)
- [ ] Verify scan completes and logs `COMPLETE` message
- [ ] Second startup: verify 90%+ files skipped
- [ ] Monitor panel requests: zero timeouts
- [ ] Monitor chat submit: reaches `on_input_submitted` handler
- [ ] Measure scan time: second startup <30s vs first startup 3-4min
- [ ] Check SQLite WAL size: should stay <1MB after checkpoint

## Abort Conditions
If three consecutive fix attempts fail to achieve "Definition of Done":
1. Manifest still doesn't persist after interrupted scan
2. Second startup still re-parses unchanged files
3. Interactive operations still timeout during scan

Then:
- Create `ISSUE_002.md` documenting failure mode
- Consider alternative approaches (different manifest storage, scan architecture)
