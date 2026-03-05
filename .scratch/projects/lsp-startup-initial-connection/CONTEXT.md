# CONTEXT — LSP Startup Initial Connection

## Start-Here Summary
This project is split out from `lsp-chat-delivery-recovery` to focus on one unresolved class of failures:
1. startup attach is delayed/not reliable from Neovim launch, and
2. interactive paths (chat submit/panel updates) still stall during heavy background scan.

## Latest Confirmed Evidence (Manual Run)
Date: **2026-03-05**

- Client log: `/home/andrew/Documents/Projects/remora/.remora/logs/client-2026-03-05_143359.log`
- Server log: `/home/andrew/Documents/Projects/remora/.remora/logs/server-2026-03-05_143406.log`
- LSP transport log: `/home/andrew/.local/state/nvim/lsp.log`

### What happened
- `M.setup` and proactive startup fired immediately at `14:33:59`.
- Client repeatedly logged `get_client: NO remora clients found!` and ran autostart retries.
- Server process only started at `14:34:06` (`pid=506539`), initialized by `14:34:07`.
- Client finally connected at `14:34:07` (`connected after 13 startup retries`).
- `cmd_chat: requestInput sent` happened, but no server `on_input_submitted` marker appeared.
- Panel requests timed out repeatedly while scan workload was active.
- `_background_scan` logged a slow append: `duration_ms=8663.8`.

## Known Relevant Code Hotspots
- Startup/autostart state machine:
  - `src/remora/lsp/nvim/lua/remora/init.lua` (see `kick_lsp_start`, `ensure_autostart_connected`, `autostart_lsp`)
- Input submit routing from Neovim:
  - `src/remora/lsp/nvim/lua/remora/init.lua` (`$/remora/requestInput` handler, fallback `vim.lsp.buf_notify`)
- Submit handler on server:
  - `src/remora/lsp/notifications.py` (`on_input_submitted`)
- Panel request path:
  - `src/remora/lsp/nvim/lua/remora/panel.lua` (`do_fetch_agent_data` timeout logic)
  - `src/remora/lsp/handlers/commands.py` (`cmd_get_agent_panel`)
- Background scan writer behavior:
  - `src/remora/lsp/__main__.py` (`_background_scan` chunked `batch_append`)
- Lock-owner lifecycle hardening (already implemented):
  - `src/remora/lsp/__init__.py`

## Prior Work Already in Tree
- proactive startup and autostart retry loop in `init.lua`
- lock-owner heartbeat/reclaim/parent-watchdog in `__init__.py`
- submit and panel timeout instrumentation in LSP handlers
- background scan preemption-yield changes in `__main__.py`

## Open Questions
1. Why is there a multi-second gap between first `vim.lsp.start` and actual server process start?
2. In latest manual run, why does client log `$/remora/submitInput` send but server never logs `on_input_submitted`?
3. Are panel timeouts secondary to scan lock contention only, or also request-routing issues?

## First Actions For New Session
1. Read this file + `PROGRESS.md` + issue artifact docs in `issues/2026-03-05-latest-manual-run/`.
2. Run a fresh startup probe and capture new logs.
3. Compare new run markers against issue `LOG_ANALYSIS.md` baselines.
4. Implement one minimal fix, then immediately re-run manual + headless validation.
