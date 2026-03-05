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

## 2026-03-05 Fix #2 Update

Implemented aggressive scan preemption tuning in `src/remora/lsp/__main__.py`:
- `scan_append_chunk_size`: 32 -> 8
- `scan_pause_window_seconds`: 3.0 -> 5.0
- Per-chunk yield: `await asyncio.sleep(0)` -> `await asyncio.sleep(0.05)`

Added regression coverage in `tests/unit/test_lsp_background_scan_manifest.py`:
- New test verifies chunked `batch_append` calls are `[8, 8, 4]` for a 20-node file.
- Verifies per-chunk `0.05` yield occurs.
- Verifies user-activity pause window is 5.0s.

Validation run after Fix #2:
- `devenv shell -- pytest tests/unit/test_lsp_background_scan_manifest.py -q` (pass)
- `devenv shell -- pytest tests/unit/test_llm_config.py -q` (pass)
- `devenv shell -- ruff check src/remora/lsp/__main__.py tests/unit/test_lsp_background_scan_manifest.py` (pass)

Next required validation:
- Real manual Neovim run after Fix #2 to confirm panel timeout regression is resolved.

## 2026-03-05 Offline Scan Script Update

Added a standalone overnight scan script at `scripts/scan_repo.py`.

Purpose:
- Run the full repository scan out-of-band (during downtime) without Neovim.
- Populate EventStore + edge DB and persist `scan-manifest.json` incrementally.
- Produce a lock/status artifact for operators: `.remora/scan-manifest.lock`.

Behavior summary:
- Uses the same supported suffixes/skip-dir logic as `_background_scan`.
- Reuses AST parsing + node ID preservation via `ASTWatcher.parse_and_inject_ids`.
- Emits `NodeDiscoveredEvent`/`NodeRemovedEvent` through `EventStore.batch_append`.
- Updates edges via `RemoraDB.update_edges`.
- Saves manifest atomically every `--manifest-save-interval` files (default 10).
- Shows tqdm bars:
  - repository-level files progress
  - per-file event chunk progress

Validation completed:
- `devenv shell -- ruff check scripts/scan_repo.py` (pass)
- `devenv shell -- python scripts/scan_repo.py --help` (pass)

Logging instrumentation update:
- Added high-detail scan logging to `scripts/scan_repo.py` with:
  - stderr + logfile output (`--log-level`, `--log-file`)
  - per-file phase logs (`read`, `list_nodes`, `parse`, `batch_append`, `update_edges`)
  - per-chunk timing logs + slow-operation warnings
  - lock file heartbeat/phase updates for in-flight visibility
- Added `--slow-operation-seconds` tuning flag.
- Smoke-tested on a temp repo with `--log-level DEBUG` (full run completed).

## 2026-03-05 EventStore Batch-Append Deep Logging Update

Added deeper instrumentation inside `EventStore.batch_append` in `src/remora/core/event_store.py`:
- Per-event prep/serialization logs with `payload_bytes` and `source_len`.
- Per-event `event start`/`event end` logs with `insert_ms`, `projection_ms`, and `total_ms`.
- `event SLOW` warnings that include event identity + payload/source sizes + phase breakdown.
- Batch tx summary now includes `total_insert_ms`, `total_projection_ms`, and `commit_ms`.

Validation:
- `devenv shell -- ruff check src/remora/core/event_store.py` (pass)
- `devenv shell -- remora-scan-repo --root browser_demo --log-level DEBUG --slow-operation-seconds 0.1` (pass)

Current diagnosis from latest full-repo log (`scan-repo-2026-03-05_162556.log`):
- Slow point is not `BEGIN IMMEDIATE` lock acquisition.
- Slow point is `projection.apply()` for a `NodeDiscoveredEvent` in `docs/EventBased_Concept.md` (chunk 6/47, idx 1/8, ~10.25s).
- This localizes the stall to projection code path (`NodeProjection._project_node_discovered`) rather than SQLite writer lock contention.

Benchmark confirmation on the exact slow node payload:
- Queried `events.db` for `node_id=rm_7m9iybrl` (`node_type=code_block`, `source_len=1340`).
- Direct timing (`devenv shell -- python -c ...`) of `_is_stub(source_code)`:
  - call #1: `13031.6ms`
  - call #2: `12859.7ms`
- This reproduces the observed 10s scan stalls and confirms pathological regex performance in `_is_stub` is the dominant bottleneck for this case.

## 2026-03-05 Temporary Mitigation: Disable Projection Stub Detection

Per user request, scaffold/stub detection in projection was disabled to unblock scan throughput immediately:
- `NodeProjection._project_node_discovered()` no longer calls `_is_stub()`.
- Discovered nodes are now projected with `status='idle'`.
- Projection no longer emits follow-up `ScaffoldRequestEvent` on discovered stubs.
- Added detailed rationale docstring in `src/remora/core/projections.py` documenting the measured regex pathological behavior and re-enable criteria.

Validation:
- `devenv shell -- ruff check src/remora/core/projections.py` (pass)
- `devenv shell -- remora-scan-repo --root browser_demo --log-level INFO` (pass)

## 2026-03-05 Startup Attach Diagnostics Update

Implemented additional diagnostics for delayed LSP attach behavior:

1) Neovim client autostart retries now surface lock-owner hints during retry, not only on terminal failure.
- File: `src/remora/lsp/nvim/lua/remora/init.lua`
- Behavior:
  - During `ensure_autostart_connected` retry loop, lock hint checks run on attempt 1 and every 5 attempts.
  - When a new hint appears, client logs warning + emits `vim.notify("[Remora] Startup waiting: ...")`.
  - On successful connection, hint state is reset.

2) Launcher now logs explicit lock-acquire diagnostics before server startup.
- File: `src/remora/lsp/__init__.py`
- Behavior:
  - Emits pre-acquire lock metadata snapshot when `.remora/lsp.pid` exists.
  - Emits structured lock-acquire failure line with owner pid/parent/heartbeat age/paths.
  - Emits structured lock-acquired line (pid/parent/paths) after successful acquire.

Validation:
- `devenv shell -- ruff check src/remora/lsp/__init__.py` (pass)

## 2026-03-05 Startup Attach Mitigation (Client Control-Flow + Logging)

Implemented direct mitigations for delayed initial attach in Neovim client:

1) Removed bootstrap buffer startup path.
- `kick_lsp_start()` now starts only from real loaded user buffers with supported filetype and non-empty filename.
- Synthetic startup buffers are no longer created.

2) Unified explicit startup into a single shared loop.
- `get_client_with_retry()` no longer issues its own `vim.lsp.start` calls.
- It now only ensures `ensure_autostart_connected()` is running and polls for availability.

3) Added startup timeout recycle.
- New env-controlled timeout: `REMORA_LSP_AUTOSTART_TIMEOUT_MS` (default `3000`).
- If no attach by timeout, client performs a one-time recycle:
  - attempts to stop pending/remora clients,
  - clears pending state,
  - re-requests startup.

4) Fixed client log timestamp coherence.
- `src/remora/lsp/nvim/lua/remora/log.lua` now emits `HH:MM:SS.mmm` from a single `gettimeofday` clock source.
- This removes out-of-order millisecond timestamps caused by mixing `os.date` and `hrtime`.

Sanity validation:
- `devenv shell -- nvim --headless -u NONE ... require(\"remora.init\") ... +qa` (pass)

Next required validation:
- Manual Neovim startup run and inspect:
  - latest `client-*.log`
  - latest `server-*.log`
  - `~/.local/state/nvim/lsp.log`
- Confirm attach occurs without waiting for first panel/chat command and with reduced retry duration.

## 2026-03-05 Startup Attach Mitigation Follow-Up

After first mitigation run, logs showed:
- startup no longer depended on first panel/chat command (good),
- but there was still delayed attach and control-loop noise:
  - false `pending client ... disappeared before attach`,
  - timeout/recycle firing with `pending_client_id=nil`,
  - client timestamps showing `.000` only.

Implemented follow-up fixes:
- Removed pending-ID disappearance check (too racy before client registration).
- Timeout/recycle now only applies when a start request exists (`pending_client_id` + `pending_started_ms`).
- Start requests are attempted whenever no pending startup exists (throttled by `REMORA_LSP_KICK_MIN_MS`), rather than sparse attempt buckets.
- Added autocmd trigger on `{BufEnter, BufWinEnter, FileType}` for startable buffers to reduce delay between first real file open and start request.
- Reduced silent poll logging noise:
  - `get_client(..., silent=true)` logs debug instead of warning when no client exists.
- Fixed logger `gettimeofday` handling for Neovim API variants (table or `(sec,usec)` returns), restoring non-zero millisecond timestamps.

Quick validation:
- `devenv shell -- nvim --headless -u NONE ... require("remora.init") ...` (pass)
- logger smoke output now includes non-zero milliseconds in new client log.

## 2026-03-05 Latest Manual Run Diagnosis (client-171612 / server-171713)

Current state from latest manual logs:
- Background scan path is now healthy:
  - `_background_scan: COMPLETE — ... (407 unchanged skipped)`
  - No scan-time SQLite stalls in this run.
- Interactive panel/read paths are healthy:
  - `cmd_get_agent_panel` lookups complete in ~1-4ms.
  - `get_recent_events` calls complete in ~50-60ms.
- Chat submit path is healthy up to runner trigger:
  - `on_input_submitted` reached and emitted `HumanChatEvent` in ~7ms.

Remaining issues:
1) Startup attach still has client-side thrash.
- Client log shows repeated `startup timeout ... recycling` from ~17:16:17 to ~17:17:08.
- It cycles through client ids 2..14, then `gave up after 60 retries`.
- A usable client eventually appears later (id=15), so startup is delayed/noisy.

2) Agent execution still fails in workspace initialization.
- First turn: `execute_agent_turn` times out at 30s while stuck after `initializing workspace service`.
- Next turn: immediate `AgentErrorEvent`:
  - `Failed to create stable workspace: [WORKSPACE_OPEN_FAILED] Failed to open workspace: .remora/swarm/stable.db`.
- Current on-disk workspace state is very large:
  - `.remora/swarm/stable.db` ~2.1GB
  - `.remora/swarm/stable.db-wal` ~3.8GB
- Direct standalone `cairn_open_workspace(.remora/swarm/stable.db)` succeeds outside the hot path, suggesting intermittent contention/race and/or pathological init cost rather than permanent corruption.

Most likely current bottleneck:
- `CairnWorkspaceService.initialize()` does `open_workspace(stable.db)` + FULL project sync on first agent turn.
- With multi-GB stable DB/WAL and 30s runner timeout, initialization can overrun timeout and cascade into follow-on workspace-open failures.
