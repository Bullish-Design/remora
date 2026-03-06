# Issue 001 Analysis: Startup Delay & Stall

Based on the audit of the end-to-end startup path, the underlying issues have been identified:

## 1. Multi-second gap in startup ("NO remora clients found")
**Issue:** `vim.lsp.start` asynchronously spawns `remora-lsp`, but the LSP client won't consider the connection "ready" until the server starts reading/writing IO. In `src/remora/lsp/__init__.py`, the `main()` entrypoint runs:
```python
await event_store.initialize()
await subscriptions.initialize()
await event_store.checkpoint_wal("PASSIVE")
```
*Before* calling `_main()` which starts the IO transport. Wait-time for WAL compaction and DB initialization completely blocks the LSP IO loop from starting. This makes Neovim think the client isn't attaching because the server hasn't responded to the `initialize` handshake yet.
**Fix Advice:** Remove `await event_store.checkpoint_wal("PASSIVE")` from `__init__.py`. This is redundant because `__main__.py` already does an opportunistic WAL compaction asynchronously inside the `_on_initialized` handler (lines 111-115). Also consider moving the DB `initialize()` calls to be non-blocking or part of the `INITIALIZED` phase, so that `start_io()` is reached instantly.

## 2. Submit drop point (`buf_notify` sent but no `on_input_submitted`)
**Issue:** In `src/remora/lsp/nvim/lua/remora/init.lua`, the chat submit fallback logic calls:
```lua
vim.lsp.buf_notify(0, "$/remora/submitInput", params)
```
`buf_notify(0, ...)` sends the notification to the LSP client *attached to the current buffer*. If the user submits chat from a `vim.ui.input` prompt or an unattached buffer like the Remora Panel, the buffer is not attached to the `remora` LSP client. Neovim silently drops the notification because no client matches.
**Fix Advice:** Do not use `vim.lsp.buf_notify(0, ...)` for global commands. Instead, manually route the notification to the active Remora client:
```lua
local client = get_client({ silent = true })
if client then
    client.notify("$/remora/submitInput", params)
end
```

## 3. Panel timeout during heavy background scan
**Issue:** In `src/remora/lsp/__main__.py`, the `_background_scan()` loop iterates through the workspace `*.py` files and calls:
```python
text = fpath.read_text(encoding="utf-8", errors="replace")
nodes = server.watcher.parse_and_inject_ids(uri, text, old_nodes)
```
These operations (Disk IO and Tree-sitter parsing) are fully synchronous and run on the main thread. Even though the scan has `await asyncio.sleep(0.1)` yields, processing a large file can block the asyncio event loop for hundreds of milliseconds. During this time, the server cannot process incoming LSP messages (like Panel API calls), causing them to time out.
**Fix Advice:** Offload the synchronous parsing and file reading into a background thread.
```python
text = await asyncio.to_thread(fpath.read_text, encoding="utf-8", errors="replace")
nodes = await asyncio.to_thread(server.watcher.parse_and_inject_ids, uri, text, old_nodes)
```
This ensures the asyncio event loop remains responsive to panel requests and chat submits even when the AST watcher is crunching large files.
