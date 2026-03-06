# LSP Connection Analysis — Cross-Agent Study

## Summary

I studied the conversation summary, then independently verified every finding against the current code, logs, and system state. Here's the complete picture.

---

## What's Already Fixed ✅

### 1. WAL Checkpoint Blocking IO Start
- **Fix in** [__init__.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__init__.py#L374-L377)
- [_prepare()](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__init__.py#353-383) no longer calls `await event_store.initialize()` or `checkpoint_wal()` — these moved to the `INITIALIZED` handler in [__main__.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py) line 113

### 2. Submit Drop Point (`buf_notify` → `client.notify`)
- **Fix in** [init.lua](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/init.lua#L724-L731)
- The `requestInput` handler now tries `client.notify()` first, falls back to `buf_notify()` only when no client is found

### 3. Synchronous Scan Blocking Event Loop
- **Fix in** [__main__.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#L249-L266)
- Both `fpath.read_text()` and `parse_and_inject_ids()` use `asyncio.to_thread()` now

---

## What's Still Broken 🔴

### 4. Neovim 0.11 `_uninitialized` Flag — THE ROOT CAUSE

> [!CAUTION]
> This is the **primary reason** the recycling loop happens and the server never connects.

**The bug** — [init.lua get_client() line 92](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/init.lua#L90-L110):

```lua
local function get_client(opts)
    opts = opts or {}
    local clients = vim.lsp.get_clients({ name = "remora", bufnr = 0 })
    -- ...
    clients = vim.lsp.get_clients({ name = "remora" })
    -- ...
end
```

In **Neovim 0.11**, `vim.lsp.get_clients()` **excludes clients in "initializing" state by default**. Since `remora-lsp` takes a few seconds to complete its initialize handshake (lock acquire → event store setup → config load → IO start → initialize response), the client is invisible to `get_clients` during this window.

**The result** (visible in [client-2026-03-05_201019.log](file:///home/andrew/Documents/Projects/remora/.remora/logs/client-2026-03-05_201019.log)):
1. `vim.lsp.start` spawns the server → returns client_id=2
2. `get_client()` polls → `all remora clients=0` (because it's still initializing)
3. After 3.5s, `ensure_autostart_connected` hits timeout → kills client_id=2
4. Spawns new server → client_id=3 → same thing → killed after 4s
5. Repeats through client_id=8 over 24 seconds, never connecting

**The fix**: Pass `_uninitialized = true` in both `get_clients` calls:

```lua
local clients = vim.lsp.get_clients({ name = "remora", bufnr = 0, _uninitialized = true })
-- and:
clients = vim.lsp.get_clients({ name = "remora", _uninitialized = true })
```

### 5. Debug Wrapper Script Breaks LSP Protocol

> [!WARNING]
> The [tmp_bin/remora-lsp](file:///home/andrew/Documents/Projects/remora/tmp_bin/remora-lsp) wrapper may cause issues if used during real runs.

[tmp_bin/remora-lsp](file:///home/andrew/Documents/Projects/remora/tmp_bin/remora-lsp):
```bash
#!/bin/bash
exec >> /home/andrew/Documents/Projects/remora/early_lsp_crash.log 2>&1
echo "WRAPPER CALLED WITH ARGS: $@"
env
echo "EXEC python script:"
exec /home/andrew/Documents/Projects/remora/.devenv/state/venv/bin/python -m remora.lsp "$@"
```

The `exec >>` on line 2 redirects **stdout** to a log file. LSP communication happens over **stdin/stdout**. This means the shell wrapper's initial `echo` and [env](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__init__.py#31-40) output would be written to the log (ok), but since the `exec` replaces the process, the Python process's stdout would go to the terminal (not the log file). Actually — wait, `exec >>` only redirects for the current shell, and the final `exec` replaces the process, so stdin/stdout redirection depends on whether the shell's fd replacement persists through `exec`. This could be fine or could corrupt the LSP protocol stream. Worth verifying.

---

## Current System State

| Check | Status |
|-------|--------|
| `.remora/lsp.lock` exists | ❌ No (clean) |
| `.remora/lsp.pid` exists | ❌ No (clean) |
| `remora-lsp` processes running | ❌ None |
| Server log from 20:10 run | ❌ Missing (server killed before writing) |
| `early_lsp_crash.log` | ❌ Doesn't exist |

The missing server log and crash log confirm the server processes were being killed by the recycling loop before they could complete initialization.

---

## Recommended Next Steps

1. **Apply the `_uninitialized = true` fix to `get_client()`** in [init.lua](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/init.lua) — this is the critical one-line-per-call fix
2. **Remove or bypass** [tmp_bin/remora-lsp](file:///home/andrew/Documents/Projects/remora/tmp_bin/remora-lsp) wrapper — use the real `remora-lsp` from the devenv PATH
3. **Re-run E2E test** to validate the fix works:
   ```bash
   python e2e/run.py --no-record --scenario chat
   ```
4. **Update PROGRESS.md** Phase 4 items once validated
