# LSP Startup Audit Checklist

Date: 2026-03-05  
Scope: End-to-end startup path from Neovim plugin setup to active Remora server loop.

## 1) Entrypoint Wiring

- [ ] Confirm `remora-lsp` script points to `remora.lsp:main`.
  - File: `pyproject.toml`
  - Lines: `80-83`
  - Expected: `remora-lsp = "remora.lsp:main"`

## 2) Neovim Setup and Spawn Request

- [ ] Confirm plugin setup uses intended `cmd`.
  - File: `src/remora/lsp/nvim/lua/remora/init.lua`
  - Lines: `10-37`
  - Expected: `cmd = opts.cmd or { "remora-lsp" }`

- [ ] Confirm proactive autostart hooks are active.
  - File: `src/remora/lsp/nvim/lua/remora/init.lua`
  - Lines: `824-841`
  - Expected: `setup-autostart`, `vimenter-autostart`, `supported-buffer-autostart`

- [ ] Confirm `vim.lsp.start(...)` path and failure logging.
  - File: `src/remora/lsp/nvim/lua/remora/init.lua`
  - Lines: `156-208`
  - Expected: `kick_lsp_start(...): vim.lsp.start returned <id>`

- [ ] Confirm retry/recycle state machine behavior.
  - File: `src/remora/lsp/nvim/lua/remora/init.lua`
  - Lines: `281-474`
  - Expected: timeout+recycle logs only when no attached client appears

## 3) Process Lock Bootstrap (`remora.lsp.main`)

- [ ] Confirm lock lifecycle logic.
  - File: `src/remora/lsp/__init__.py`
  - Lines: `50-275`
  - Touches: `.remora/lsp.lock`, `.remora/lsp.pid`, heartbeat, stale-owner reclaim

- [ ] Confirm main startup sequence and lock acquire path.
  - File: `src/remora/lsp/__init__.py`
  - Lines: `341-433`
  - Expected stderr markers:
    - `workspace lock acquired ...`
    - or `workspace lock acquire failed ...`

- [ ] Confirm parent watchdog/signal cleanup is installed.
  - File: `src/remora/lsp/__init__.py`
  - Lines: `278-339`, `420-432`

## 4) Event Store / Subscription Preparation

- [ ] Confirm pre-server initialization creates required services.
  - File: `src/remora/lsp/__init__.py`
  - Lines: `353-381`
  - Touches:
    - `EventBus`
    - `EventStore(.remora/events/events.db)`
    - `SubscriptionRegistry(.remora/subscriptions.db)`
    - `NodeProjection`

## 5) Runtime Main (`remora.lsp.__main__.main`)

- [ ] Confirm logging initialization.
  - File: `src/remora/lsp/__main__.py`
  - Lines: `13-51`
  - Touches: `.remora/logs/server-<timestamp>.log`

- [ ] Confirm config load and server module import.
  - File: `src/remora/lsp/__main__.py`
  - Lines: `61-95`
  - Touches:
    - `load_config()`
    - `remora.lsp.server` singleton import
    - `AgentRunner` construction

- [ ] Confirm IO transport start.
  - File: `src/remora/lsp/__main__.py`
  - Lines: `377-395`
  - Expected: `Starting IO transport (waiting for client on stdin) ...`

## 6) Server Singleton + Handler Registration

- [ ] Confirm singleton creation and handler imports occur.
  - File: `src/remora/lsp/server.py`
  - Lines: `237-278`
  - Touches handler modules:
    - `handlers/actions.py`
    - `handlers/capabilities.py`
    - `handlers/commands.py`
    - `handlers/documents.py`
    - `handlers/hover.py`
    - `handlers/lens.py`
    - `notifications.py`

- [ ] Confirm server object construction internals.
  - File: `src/remora/lsp/server.py`
  - Lines: `24-45`
  - Touches:
    - `RemoraDB`
    - `LazyGraph`
    - `ASTWatcher`

## 7) LSP Initialize Handshake and Post-Init

- [ ] Confirm `initialize` handler fires.
  - File: `src/remora/lsp/handlers/capabilities.py`
  - Lines: `8-16`
  - Expected log: `Client connected (initialize received)`

- [ ] Confirm `INITIALIZED` callback starts runtime loops.
  - File: `src/remora/lsp/__main__.py`
  - Lines: `97-120`
  - Expected:
    - `startup took ...ms`
    - `run_forever()` started
    - `run_from_event_store(...)` started
    - `_background_scan()` scheduled

## 8) Background Scan Touch Surface

- [ ] Confirm scan reads/writes expected files.
  - File: `src/remora/lsp/__main__.py`
  - Lines: `121-368`
  - Touches:
    - workspace source files (`.py`, `.md`, `.toml`)
    - `.remora/scan-manifest.json`
    - `EventStore.batch_append(...)`
    - `RemoraDB.update_edges(...)`

## 9) First Interactive Path (Chat/Panel)

- [ ] Confirm notifications path for chat submit.
  - File: `src/remora/lsp/notifications.py`
  - Lines: `41-170`
  - Touches:
    - `emit_event(LspHumanChatEvent)`
    - `runner.trigger(...)`

- [ ] Confirm panel command path.
  - File: `src/remora/lsp/handlers/commands.py`
  - Lines: `68-179`
  - Touches:
    - `event_store.get_node_at_position(...)`
    - `event_store.get_recent_events(...)`

- [ ] Confirm document-open parse path.
  - File: `src/remora/lsp/handlers/documents.py`
  - Lines: `13-89`
  - Touches:
    - `watcher.parse_and_inject_ids(...)`
    - `event_store.append(...)`
    - `db.update_edges(...)`

## 10) Runner Loop and Execution Boundary

- [ ] Confirm run loop and trigger bridge.
  - File: `src/remora/lsp/runner.py`
  - Lines: `161-177`, `258-278`, `354-388`

- [ ] Confirm turn execution entry boundary.
  - File: `src/remora/lsp/runner.py`
  - Lines: `397-430` (continues through execution path)

## 11) Quick Failure Signature Map

- [ ] Symptom: client retries forever, no server log file.
  - Likely before/at process spawn (command resolution or early process death).
  - Check: sections 1-3.

- [ ] Symptom: server log exists, no `initialize`.
  - Likely LSP transport/connectivity issue.
  - Check: sections 5-7.

- [ ] Symptom: initializes, then chat/panel stalls.
  - Likely EventStore/scan contention or runner path issue.
  - Check: sections 8-10.

