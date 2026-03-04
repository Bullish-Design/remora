# Neovim Demo V2.4 — Code Review

> **Date:** 2026-03-01  
> **Scope:** All files under `demo/` and `src/remora/lsp/`  
> **Focus:** Correctness, architecture, divergence between demo ↔ src, Neovim integration

---

## Table of Contents

1. [Critical Bug: `remora-lsp` Crash on Startup](#1-critical-bug-remora-lsp-crash-on-startup)
2. [Architecture Overview](#2-architecture-overview)
3. [Demo vs Src Divergence](#3-demo-vs-src-divergence)
4. [File-by-File Analysis: `src/remora/lsp/`](#4-file-by-file-analysis-srcremora-lsp)
5. [File-by-File Analysis: `demo/`](#5-file-by-file-analysis-demo)
6. [Neovim Plugin Review](#6-neovim-plugin-review)
7. [Cross-Cutting Concerns](#7-cross-cutting-concerns)
8. [Refactoring Opportunities](#8-refactoring-opportunities)
9. [Summary of Findings](#9-summary-of-findings)

---

## 1. Critical Bug: `remora-lsp` Crash on Startup

**File:** [\_\_main\_\_.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/__main__.py)

### The Error

```
pygls.exceptions.ThreadDecoratorError: Thread decorator cannot be used with async functions "_start_runner"
```

### Root Cause

`@server.thread()` in pygls dispatches a **synchronous** function onto a background thread. The code applied it to `async def`:

```python
# BROKEN — @server.thread() cannot wrap async functions
@server.thread()
async def _start_runner() -> None:
    await runner.run_forever()
```

pygls explicitly checks for this and raises `ThreadDecoratorError`. An async function on a thread would create a separate event loop or simply fail.

### The Fix (Applied)

Replaced with `@server.feature(lsp.INITIALIZED)` — the correct lifecycle hook that fires after client handshake:

```python
@server.feature(lsp.INITIALIZED)
async def _on_initialized(params: lsp.InitializedParams) -> None:
    asyncio.ensure_future(runner.run_forever())
```

This schedules the runner on pygls's **existing** event loop. No threads needed.

### Why This Happened

Misunderstanding of pygls concurrency. pygls already runs an `asyncio` event loop — `async def` handlers run directly on it. `@server.thread()` is only for offloading CPU-bound *synchronous* work.

---

## 2. Architecture Overview

The codebase has two parallel implementations of the same system:

| Layer | `demo/` (original prototype) | `src/remora/lsp/` (production) |
|---|---|---|
| **Models** | `demo/core/models.py` — Pydantic, `__init__` overrides | `src/remora/lsp/models.py` — Pydantic, `@model_validator` |
| **DB** | `demo/core/db.py` — sync SQLite | `src/remora/lsp/db.py` — async-wrapped SQLite |
| **Graph** | `demo/core/graph.py` — rustworkx, no close() | `src/remora/lsp/graph.py` — rustworkx, has close() |
| **Watcher** | `demo/core/watcher.py` — tree-sitter | `src/remora/lsp/watcher.py` — tree-sitter |
| **Server** | `demo/lsp/server.py` — monolithic 274 lines | `src/remora/lsp/server.py` + `handlers/` — split into 7 files |
| **Runner** | `demo/agent/runner.py` — standalone | `src/remora/lsp/runner.py` — integrates with SwarmExecutor |
| **Entry** | `demo/__main__.py` — asyncio.run() | `src/remora/lsp/__main__.py` — server.start_io() |

### Data flow

```
Neovim → stdio → pygls LanguageServer → handler (didOpen/didSave/hover/etc.)
                                           ↓
                                    ASTWatcher.parse_and_inject_ids()
                                           ↓
                                    RemoraDB.upsert_nodes() → SQLite
                                           ↓
                                    LazyGraph.ensure_loaded() → rustworkx
                                           ↓
                                    AgentRunner.trigger() → queue → execute_turn()
                                           ↓
                                    MockLLMClient.chat() → tool calls → proposals
                                           ↓
                                    workspace/applyEdit → Neovim applies diff
```


---

## 3. Demo vs Src Divergence

The `demo/` directory is a frozen prototype. All its `__init__.py` files re-export from `src/remora/lsp/`, but `demo/lsp/server.py`, `demo/agent/runner.py`, `demo/core/db.py`, etc. are **standalone copies** that import from `demo.core`, not `remora.lsp`. This creates a confusing dual-codebase situation.

### Key Divergences

| Aspect | `demo/` | `src/remora/lsp/` |
|---|---|---|
| **DB operations** | All synchronous (`self.conn.cursor()`) | Wrapped in `asyncio.to_thread` |
| **Event models** | `__init__` override pattern for defaults | `@model_validator(mode="before")` pattern |
| **Event bridging** | No `to_core_event()` method | Bridges LSP events → core Remora events |
| **Server structure** | Single 274-line file with all handlers | Split into `handlers/` package (7 files) |
| **Runner constructor** | `AgentRunner()` — no args, reads `server` global | `AgentRunner(server=server)` — explicit injection |
| **code lens refresh** | Direct `publish_code_lenses(uri, [agent])` | `workspace_code_lens_refresh_async()` |
| **notifications** | `server.protocol.notify(...)` | `server.send_notification(...)` |
| **ID injection on save** | Not implemented | Writes `# rm_xxxx` comments into files |
| **Tool discovery** | Not implemented | `discover_tools_for_agent()` via Grail |
| **`from __future__`** | Missing everywhere | Present in all `src/` files |
| **Filepath comments** | Missing in most files | Present (`# src/remora/lsp/...`) |

### Verdict

> [!WARNING]
> The `demo/` code is **dead code** — every `__init__.py` re-exports from `src/remora/lsp/`, yet the actual `.py` files in `demo/core/`, `demo/lsp/`, and `demo/agent/` are stale copies that nobody imports. They serve only to confuse. The only `demo/` files with unique value are the **Neovim Lua plugins** (`demo/nvim/`).


---

## 4. File-by-File Analysis: `src/remora/lsp/`

### `models.py` (467 lines)

**Quality: Good** — well-structured Pydantic models with proper `@model_validator`, `@computed_field`, and LSP type conversions.

| Issue | Severity | Detail |
|---|---|---|
| `model_rebuild()` calls at module level | Low | 9 explicit `model_rebuild()` calls at bottom. These are needed due to `from __future__ import annotations` but could be consolidated. |
| `hashlib` import unused | Trivial | Imported but not used in this file (used in `watcher.py` instead). |
| `to_hover` truncates prompt | Low | `self.custom_system_prompt[:200]` with hardcoded `...` suffix even if prompt is shorter than 200 chars. |
| `from_agent_state` sets empty `source_code` / `source_hash` | Medium | Creates a node with `source_code=""` and `source_hash=""` — downstream code may not expect this. |

### `server.py` (144 lines)

**Quality: Good** — clean separation of concerns.

| Issue | Severity | Detail |
|---|---|---|
| Module-level `server = RemoraLanguageServer()` singleton | Medium | Instantiates DB/Graph/Watcher on **import**, not on use. Means importing the module has side effects (creates `.remora/indexer.db`). |
| `atexit.register(server.shutdown)` | Low | Runs shutdown on process exit but `atexit` doesn't run on SIGKILL. Fine for normal operation. |
| `register_handlers()` at module level | Low | Forces all handler modules to load on import. This is intentional but means circular imports must be carefully managed (they use deferred imports). |
| `discover_tools_for_agent` catches all exceptions silently | Medium | Blanket `except Exception` hides configuration errors. |

### `runner.py` (311 lines)

**Quality: Good** — clean async architecture with proper queue-based triggering.

| Issue | Severity | Detail |
|---|---|---|
| `MockLLMClient` always returns empty tool_calls | Medium | No actual LLM integration — every agent turn is a no-op. Fine for demo, but not documented. |
| `_load_agent_state` always returns `None` | Low | Placeholder for SwarmExecutor integration. |
| `execute_extension_tool` emits event but does no work | Low | Placeholder — logs that a tool ran without actually running it. |
| `apply_extensions` is synchronous I/O | Medium | `load_extensions_from_disk()` does `Path.glob()` + `importlib` on every agent turn. Should be cached. |

### `db.py` (333 lines)

**Quality: Adequate** — properly wraps sync SQLite in `asyncio.to_thread`.

| Issue | Severity | Detail |
|---|---|---|
| `check_same_thread=False` | Medium | Required for async wrapping, but means raw connection is shared across threads without locking. `asyncio.to_thread` serializes calls via GIL, so it works in practice. |
| No connection pooling | Low | Single connection for all operations. Fine for a local tool. |
| `get_neighborhood` recursive CTE | Low | Could be expensive on large codebases but has depth limit. |
| Missing `hashlib` import | Trivial | Not used in this file. |

### `handlers/documents.py` (97 lines)

**Quality: Good** — proper error handling with try/except around all handlers.

| Issue | Severity | Detail |
|---|---|---|
| `did_save` reads file from disk | Medium | `Path(uri_to_path(uri)).read_text()` — races with the editor buffer. Could use LSP sync or the client's text if available. |
| `inject_ids` writes to disk on save | Medium | Mutates the file that was just saved, causing a re-save loop. Mitigated by `server._injecting` guard, but fragile. |
| `discover_tools_for_agent` called per-node on `didOpen` | Low | Could be slow with many nodes. Results aren't cached. |

### `handlers/commands.py` (74 lines)

**Quality: Good** — clean match/case dispatch.

| Issue | Severity | Detail |
|---|---|---|
| `args[0]` without bounds checking | Medium | Will raise `IndexError` if client sends malformed command. Caught by outer try/except, but produces a confusing log. |
| `workspace_apply_edit` not awaited with `_async` | Low | Uses sync variant `workspace_apply_edit` instead of async. |

### `notifications.py` (43 lines)

**Quality: Good** — clean and concise.

| Issue | Severity | Detail |
|---|---|---|
| `HumanChatEvent` missing `timestamp` | Low | Relies on `emit_event` to set timestamp. Works but fragile. |

### `watcher.py` (183 lines)

**Quality: Good** — dual-mode tree-sitter + regex fallback.

| Issue | Severity | Detail |
|---|---|---|
| Double parse in tree-sitter mode | Bug | Line 27-28: `self.parser.parse(...)` is called twice. First result is discarded. |
| `method_definition` node type | Low | Python tree-sitter grammar uses `function_definition` for methods too (inside class bodies). `method_definition` may never match. |
| Fallback regex is naive | Low | `^(def|class)\s+(\w+)` doesn't handle decorators, nested defs, or multiline signatures well. |
| `inject_ids` writes file without encoding parameter | Low | `file_path.write_text(new_content)` uses system default encoding. |


---

## 5. File-by-File Analysis: `demo/`

### Python Files — Summary

As noted in Section 3, the Python files under `demo/core/`, `demo/lsp/`, and `demo/agent/` are **stale prototypes**. The `__init__.py` re-exports make them appear integrated, but the `.py` implementation files import from `demo.core`, creating a separate, unmaintained code path.

**Notable issues in the stale demo code:**

| File | Issue |
|---|---|
| `demo/core/models.py` | Uses `__init__` override pattern instead of `@model_validator`. No `to_core_event()`. Missing `from __future__` and file path comments. |
| `demo/core/db.py` | Entirely synchronous SQLite. Will block the event loop if used in an async context. |
| `demo/core/graph.py` | Bare `except:` on line 28 swallows all errors including `KeyboardInterrupt`. No `close()` method. |
| `demo/core/watcher.py` | Same double-parse bug as `src/` version (line 27-28). Same `method_definition` issue. |
| `demo/lsp/server.py` | Uses deprecated `server.protocol.notify(...)` instead of `server.send_notification(...)`. Missing `from __future__`. |
| `demo/agent/runner.py` | `AgentRunner.__init__()` takes no args and reads module-level `server` global — tight coupling. Missing import for `publish_code_lenses` at top of file (uses deferred import at bottom). `ExtensionNode` class defined *after* it's referenced by `load_extensions_from_disk`. |
| `demo/__main__.py` | `asyncio.run(main())` creates a *second* event loop — incompatible with pygls which already runs one. Would never work with `server.start_io()`. |

### Unique Demo Files (Worth Keeping)

| File | Value |
|---|---|
| `demo/README.md` | Good high-level docs for the architecture |
| `demo/start.sh` | Useful quickstart script with dependency checking |
| `demo/nvim/` | All Lua code — the actual Neovim integration |

---

## 6. Neovim Plugin Review

### `demo/nvim/lua/remora/init.lua` (147 lines)

**Quality: Good** — clean LSP-native approach.

| Issue | Severity | Detail |
|---|---|---|
| `vim.lsp.config` / `vim.lsp.enable` | Info | Uses Neovim 0.11+ API. Won't work on older Neovim versions. Should be documented. |
| Custom notification handlers | Good | Properly registers `$/remora/event`, `$/remora/requestInput`, `$/remora/agentSelected` via `vim.lsp.handlers`. |
| `vim.ui.input` for chat | Good | Clean UX — uses native Neovim input prompt. |
| Missing `languageId` in `didOpen` | Low | The `textDocument` in `vim.lsp.buf_notify` doesn't include `languageId`, which is required by the LSP spec. |
| No error recovery | Medium | If `vim.lsp.buf_notify` fails (e.g., no client attached), user sees no feedback. |
| `cmd` hardcoded to `python -m demo.lsp.server` | Medium | Should use `remora-lsp` entrypoint instead, which is the production path. |

### `demo/nvim/lua/remora/panel.lua` (204 lines)

**Quality: Adequate** — functional but has a hard dependency.

| Issue | Severity | Detail |
|---|---|---|
| `require("nui.popup")` at module level | **High** | Hard crashes if `nui.nvim` plugin is not installed. Should be wrapped in `pcall`. |
| No `M.popup:mount()` call | Medium | `nui_popup` requires `:mount()` before `:show()`. Code calls `:show()` directly, which may not render. |
| `buf_options` with `readonly` | Low | `readonly` is a window option, not a buffer option in nui.nvim. |
| `M.is_open` is both a field and a function | Bug | `M.state.is_open` (boolean) and `M.is_open()` (function at line 120) — calling `M.is_open` without `()` returns the function, not the boolean. The `init.lua` uses `M.sidepanel.is_open` which gets the *function*, which is always truthy. |
| No auto-refresh | Low | Panel content only updates when `add_event` or `select_agent` is called. Agent list (`M.state.agents`) is never populated from the server. |

### `demo/nvim/lua/remora_starter.lua` (276 lines)

**Quality: Adequate** — comprehensive but duplicates `init.lua`.

| Issue | Severity | Detail |
|---|---|---|
| Duplicates commands from `init.lua` | Medium | Both files define `RemoraChat`, `RemoraRewrite`, `RemoraAccept`, `RemoraReject`. If both are loaded, commands collide. |
| `vim.lsp.start` vs `vim.lsp.enable` | Info | `remora_starter.lua` uses older `vim.lsp.start` API while `init.lua` uses newer `vim.lsp.enable`. They're incompatible approaches. |
| `vim.lsp.buf_notify` for `didOpen` | Medium | Manually sends `didOpen` notification, but Neovim's LSP client already sends this automatically. Results in duplicate processing. |
| `c.rpc.client_id` in status | Low | May not be a valid field on newer lsp client objects. |
| `M.config.demo_path` resolution is fragile | Low | Tries 4 hardcoded relative paths. Should use the `remora-lsp` binary location or a config variable. |

### `demo/nvim/remora.vim` (74 lines)

**Quality: Low** — thin VimL wrapper that just calls Lua. Adds no value if using `init.lua` or `remora_starter.lua` directly.


---

## 7. Cross-Cutting Concerns

### Async/Sync Boundary

The `src/remora/lsp/` code properly wraps synchronous SQLite via `asyncio.to_thread`, but several synchronous operations remain in the async hot path:

- `ASTWatcher.parse_and_inject_ids()` — tree-sitter parsing is synchronous. Fine for small files, but could block the event loop for large files.
- `load_extensions_from_disk()` — does synchronous `Path.glob()` + `importlib.util.spec_from_file_location` on every agent turn.
- `Path(uri_to_path(uri)).read_text()` in `did_save` — synchronous file I/O.
- `inject_ids()` — synchronous file write.

### Error Handling

The `src/` code handles errors well with try/except in all handlers and `logger.exception()`. The `demo/` code has no error handling at all — any exception in a handler will crash the LSP connection.

### Testing

No tests exist for any of this code. The LSP server, runner, handlers, watcher, and DB are all untested. This is the biggest gap.

### Security

- `load_extensions_from_disk()` executes arbitrary Python from `.remora/models/`. This is by design but should be documented as a security consideration.
- The `inject_ids` function writes to user files without confirmation — the Neovim `workspace/applyEdit` flow at least asks for confirmation, but the raw `inject_ids` on save does not.

---

## 8. Refactoring Opportunities

### R1: Delete `demo/` Python Code (Effort: Small, Impact: High)

Remove `demo/core/`, `demo/lsp/`, `demo/agent/`, `demo/__init__.py`, `demo/__main__.py`. Keep `demo/nvim/`, `demo/README.md`, `demo/start.sh`. The Python files are dead code that confuses maintainers and diverges from the real implementation.

### R2: Move Neovim Lua Plugin to `lua/` (Effort: Small, Impact: Medium)

Move `demo/nvim/lua/remora/` → `lua/remora_nvim/` (top-level). This is the standard location for Neovim plugins in a repo and is already partially done (there's a `lua/remora_nvim/bridge.lua` in the repo root).

### R3: Consolidate Lua Entry Points (Effort: Small, Impact: Medium)

Pick one of `init.lua` or `remora_starter.lua` and delete the other. They define conflicting commands and use incompatible Neovim APIs (`vim.lsp.enable` vs `vim.lsp.start`). The `init.lua` approach (Neovim 0.11+ native) is the better path.

### R4: Fix the Double Parse Bug (Effort: Trivial, Impact: Medium)

In both `demo/core/watcher.py` and `src/remora/lsp/watcher.py`, line 27 parses without saving the result. Delete that line.

### R5: Cache Extension Discovery (Effort: Small, Impact: Medium)

`load_extensions_from_disk()` is called on every agent turn. Cache with a file-mtime check to avoid redundant `importlib` loading.

### R6: Wrap `nui.popup` in pcall (Effort: Trivial, Impact: High)

`panel.lua` line 2 will crash Neovim if `nui.nvim` is not installed. Wrap in `pcall` and show a helpful error message.

### R7: Fix `M.is_open` Name Collision (Effort: Trivial, Impact: Medium)

Rename the function `M.is_open()` on line 120 of `panel.lua` to `M.get_is_open()` or remove it entirely (callers can check `M.state.is_open` directly).

### R8: Use `remora-lsp` Entrypoint in Lua Config (Effort: Trivial, Impact: Medium)

Change `cmd = { "python", "-m", "demo.lsp.server" }` to `cmd = { "remora-lsp" }` in both `init.lua` and `remora_starter.lua`. The `remora-lsp` entrypoint is the production path and is already registered in `pyproject.toml`.

---

## 9. Summary of Findings

### By Severity

| Severity | Count | Key Items |
|---|---|---|
| **Critical (Crash)** | 1 | `@server.thread()` on async function — **fixed** |
| **Bug** | 2 | Double parse in watcher; `M.is_open` name collision in panel.lua |
| **High** | 1 | `nui.popup` hard dependency crashes without plugin |
| **Medium** | ~15 | Stale demo code, sync I/O in async path, missing bounds checks, hardcoded paths, duplicate commands |
| **Low** | ~15 | Missing encoding params, unused imports, fragile path resolution |

### Overall Assessment

The **`src/remora/lsp/`** code is well-structured and close to production-ready. The Pydantic models correctly use `@model_validator`, the DB layer properly uses `asyncio.to_thread`, the handler split is clean, and the runner's queue-based architecture is sound. The main issues are the missing LLM integration (expected — it's a mock for now) and the lack of tests.

The **`demo/`** Python code is dead weight that should be deleted. It diverged from `src/` during the V2.2/V2.3 refactoring and now serves only to confuse.

The **Neovim Lua plugin** is functional but needs cleanup: consolidate the two entry points, fix the `nui.popup` crash, and switch to the `remora-lsp` entrypoint.

