# Implementation Report — Step 08 Lock-Owner Lifecycle Hardening

## Scope
Implemented durable lock-owner lifecycle hardening for `remora-lsp` to prevent long-lived stale owners from blocking future Neovim sessions.

## Code Changes
- `src/remora/lsp/__init__.py`
  - Added lock metadata model and robust process lock manager:
    - heartbeat-based owner metadata updates in `.remora/lsp.pid` (pid + heartbeat_ms + ppid)
    - stale-owner detection and reclaim path (validate owner process + workspace match, terminate stale owner, retry lock)
    - improved lock-collision error diagnostics (healthy owner vs stale heartbeat vs stale metadata)
  - Added lifecycle safeguards:
    - signal handlers (`SIGINT`, `SIGTERM`, `SIGHUP`) release lock metadata on termination
    - parent-process watchdog exits orphaned `remora-lsp` processes and releases lock
- `src/remora/lsp/nvim/lua/remora/init.lua`
  - Updated lock hint parsing to read owner heartbeat metadata and distinguish:
    - owner alive + fresh heartbeat
    - owner alive + stale heartbeat
    - stale metadata only

## Tests Added
- `tests/unit/test_lsp_lock_owner.py`
  - heartbeat file updates while lock held and cleanup on release
  - stale-owner reclaim path retries acquisition after terminating stale owner
  - fresh-owner path does not reclaim and raises lock-active error

## Validation
- `devenv shell -- pytest tests/unit/test_lsp_lock_owner.py -q` PASS
- `devenv shell -- ruff check src/remora/lsp/__init__.py tests/unit/test_lsp_lock_owner.py --fix` PASS
- `devenv shell -- nvim --headless -u NONE "+lua assert(loadfile('src/remora/lsp/nvim/lua/remora/init.lua'))" +q` PASS
- `devenv shell -- python -m e2e.run --scenario startup --no-record` PASS
- `devenv shell -- python -m e2e.run --scenario chat --no-record` PASS

## Notes
- This step hardens lifecycle and recovery behavior in code.
- A fresh manual real-run should still be executed to confirm behavior against the exact previously failing `pid=250354` pattern.
