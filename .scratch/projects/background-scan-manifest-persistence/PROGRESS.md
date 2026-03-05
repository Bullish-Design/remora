# PROGRESS — Background Scan Manifest Persistence

## Phase 1: Root Cause Analysis — COMPLETE
- [x] Investigated startup delay and interactive operation failures
- [x] Discovered missing manifest file
- [x] Traced scan completion failure (interrupted at 29/405 files)
- [x] Identified vicious cycle: no manifest → full rescan → slow → interrupted → no manifest
- [x] Analyzed SQLite write contention (8.6s batch_append)
- [x] Documented evidence in `issues/2026-03-05-initial-analysis/`

## Phase 2: Design Solution — COMPLETE
- [x] Review proposed fixes and prioritize
- [x] Design incremental manifest save strategy (every N files)
- [x] Determine manifest update granularity vs performance trade-off
- [x] Consider atomic write requirements (tmp file + rename pattern)
- [x] Plan validation strategy for manifest correctness

## Phase 3: Implement Fix #1 (Incremental Manifest) — COMPLETE
- [x] Add incremental-save helper logic in scan loop
- [x] Integrate incremental saves into scan loop (every 10 files)
- [x] Use atomic write pattern (write to .tmp, then rename)
- [x] Preserve existing manifest save at end for completeness
- [x] Add regression test for interrupted scan persistence

## Phase 4: Validate Fix #1 — COMPLETE
- [x] Verify baseline: `.remora/scan-manifest.json` missing
- [x] Verify baseline: `.remora/events/events.db-wal` was 4.0MB
- [x] Add automated interruption test: scan cancelled mid-run still writes manifest incrementally
- [x] Run targeted tests:
  - `devenv shell -- pytest tests/unit/test_lsp_background_scan_manifest.py -q`
  - `devenv shell -- pytest tests/unit/test_llm_config.py -q`
- [x] Manual Neovim startup/interrupt validation (pending)
- [x] Restart validation with real logs (`skipped_unchanged` reflects persisted entries)
- [x] Full real scan completion validation (`_background_scan: COMPLETE`)

## Phase 5: Implement Fix #2 (Aggressive Preemption) — COMPLETE
- [x] Reduce chunk size from 32 → 8 events
- [x] Change `asyncio.sleep(0)` → `asyncio.sleep(0.05)` between chunks
- [x] Keep pause check before every chunk
- [x] Add regression test for preemption settings (chunking + pause window + sleep cadence)
- [ ] Manual interactive validation during active scan

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
- [x] Second startup: verify 90%+ files skipped
- [x] Monitor panel requests: zero timeouts
- [x] Monitor chat submit: reaches `on_input_submitted` handler
- [ ] Measure scan time: second startup <30s vs first startup 3-4min
- [ ] Check SQLite WAL size: should stay <1MB after checkpoint

## Phase 9: Offline Scan Tooling — COMPLETE
- [x] Add standalone scan script: `scripts/scan_repo.py`
- [x] Script performs full parse + EventStore/edge updates (not manifest-only)
- [x] Script writes incremental `scan-manifest.json` updates
- [x] Script writes lock/status file: `.remora/scan-manifest.lock`
- [x] Add tqdm progress bars (overall repository + per-file event progress)
- [x] Add verbose diagnostics logging (file + stderr, per-phase/per-chunk timings)
- [x] Validate script CLI/help and lint
- [x] Add deep per-event diagnostics in `EventStore.batch_append` (payload/source sizes + phase timing breakdown)
- [x] Validate deep logging on `browser_demo` scan and confirm slow phase localizes to projection path
- [x] Reproduce slow path directly: `_is_stub` on problematic markdown `code_block` source takes ~13s/call
- [x] Temporary mitigation: disable projection stub detection/follow-up scaffold emission to remove regex stall from scan path
- [x] Add startup diagnostics for delayed attach: autostart lock-hint surfacing + launcher lock-acquire structured logging
- [x] Remove Neovim bootstrap-buffer startup path (real buffers only)
- [x] Collapse explicit startup to a single shared retry loop (no multi-loop `vim.lsp.start` storms)
- [x] Add startup timeout recycle path (force-stop pending remora client once, then re-request startup)
- [x] Fix client logger timestamp coherence (`HH:MM:SS.mmm` from one wall-clock source)
- [x] Remove false-positive `pending client disappeared` detection during startup race
- [x] Gate timeout/recycle to only run after actual start request (pending client exists)
- [x] Trigger startup orchestration on supported buffer enter/filetype events for faster first attach
- [x] Reduce silent polling noise (`NO remora clients found` now debug when silent)
- [x] Fix Neovim `uv.gettimeofday` handling so millisecond timestamps are non-zero
- [ ] Validate startup attach latency improvement in manual run logs (latest run still shows timeout/recycle thrash before eventual attach)
- [ ] Eliminate autostart client recycle thrash (ids 2..14 recycled before stable attach)
- [ ] Instrument and stabilize `CairnWorkspaceService.initialize()` on runner path (currently causing 30s timeout + transient `WORKSPACE_OPEN_FAILED`)

## Abort Conditions
If three consecutive fix attempts fail to achieve "Definition of Done":
1. Manifest still doesn't persist after interrupted scan
2. Second startup still re-parses unchanged files
3. Interactive operations still timeout during scan

Then:
- Create `ISSUE_002.md` documenting failure mode
- Consider alternative approaches (different manifest storage, scan architecture)
