# NVIM V2.1 Demo — Code Review

A thorough review of the `demo/` implementation against the
[NEOVIM_DEMO_V21_FINAL_CONCEPT.md](file:///c:/Users/Andrew/Documents/Projects/remora/NEOVIM_DEMO_V21_FINAL_CONCEPT.md)
concept document. Covers concept adherence, code quality, and interaction design.

---

## 1. Executive Summary

The demo successfully scaffolds the LSP-native architecture described in the
concept doc. The file structure, core Pydantic models, SQLite schema, and pygls
server all follow the spec closely. The intern clearly understood the intent
of the design.

That said, the implementation has **significant quality gaps** that would prevent
it from running correctly in practice. The issues fall into three buckets:

| Bucket | Severity | Count |
|--------|----------|-------|
| **Project conventions violated** | Medium | 10 |
| **Correctness / runtime bugs** | High | 8 |
| **Missing or stub implementations** | High | 6 |

---

## 2. Project Convention Violations

Every file violates one or more project-level rules from the global config.

### 2.1 Missing filepath comment

> *"For every file you write, ensure it starts with a single line comment that
> contains the filepath."*

**No Python file in the demo has this.** Every `.py` file should begin with e.g.
`# demo/core/models.py`.

### 2.2 Missing `from __future__ import annotations`

> *"Use `from __future__ import annotations`, and avoid type hints in quotes."*

Not a single file imports it. Forward references like `list["ToolSchema"]` and
`list["AgentEvent"]` in `models.py` use quoted strings instead of relying on
`from __future__ import annotations`.

### 2.3 No Pydantic where it makes sense

- `Trigger` in `runner.py` is a plain class — should be a Pydantic `BaseModel`.
- `ExtensionNode` is a plain class with hand-rolled property stubs — also a
  strong Pydantic candidate.

### 2.4 Lines over 150 chars

Several lines in `runner.py` and `server.py` exceed 150 characters (e.g., the
`rejection_feedback` append at line 99).

---

## 3. Concept Adherence

### 3.1 What is implemented correctly ✅

| Concept Section | Demo File | Notes |
|-----------------|-----------|-------|
| `ASTAgentNode` model | `core/models.py` | Faithful copy of all fields and methods |
| `ToolSchema` model | `core/models.py` | `to_code_action()` and `to_llm_tool()` match |
| `RewriteProposal` model | `core/models.py` | `diff`, `to_workspace_edit()`, `to_diagnostic()`, `to_code_actions()` all present |
| Event models | `core/models.py` | All 6 event types from the concept are defined |
| SQLite schema | `core/db.py` | All 5 tables + 4 indexes match the concept exactly |
| LSP handlers (hover, codeLens, codeAction, executeCommand) | `lsp/server.py` | All implemented and structurally correct |
| Custom notifications (`$/remora/*`) | `lsp/server.py` | `requestInput`, `submitInput`, `event`, `agentSelected` all present |
| ID format (`rm_` + 8 alphanumeric) | `core/models.py` | `generate_id()` matches spec |
| Orphan detection on save | `lsp/server.py` | `did_save()` correctly matches by `(name, node_type)` key |
| Rustworkx lazy graph | `core/graph.py` | Graceful fallback when rustworkx unavailable |
| Tree-sitter parsing + regex fallback | `core/watcher.py` | Both code paths present |
| `AgentRunner` trigger/execute loop | `agent/runner.py` | Queue-based, cycle detection, depth limit all implemented |
| Neovim Lua commands | `nvim/lua/remora_starter.lua` | All user commands from concept (Chat, Rewrite, Accept, Reject) |
| Vim script wrapper | `nvim/remora.vim` | Functional bridge to Lua commands |

### 3.2 What deviates from concept ⚠️

| Concept Feature | What the concept says | What the demo does | Impact |
|-----------------|----------------------|------------------|--------|
| **`$/remora/submitInput` registration** | `@server.feature("$/remora/submitInput")` — custom LSP notification | Registered correctly, but `pygls` may not support `@server.feature()` for custom notification handlers this way. The standard approach is `@server.command()` or registering via `lsp_method()`. | May silently fail — notifications from Neovim would be dropped. |
| **Server `send_notification()`** | Concept uses `await server.send_notification(...)` | Demo uses `server.protocol.notify(...)` | Correct adaptation — `pygls` uses `protocol.notify()`. The intern made a valid API adjustment. |
| **`publish_code_lenses()` is wrong** | Concept publishes code lenses by refreshing the client | Demo calls `server.text_document_publish_diagnostics()` (clears diagnostics) then tries to push a `codeLens` params object via `protocol.notify("textDocument/codeLens", ...)` | Incorrect. You cannot push code lenses via notification. The client *pulls* them via `textDocument/codeLens` request. This function should trigger a `codeLensRefresh` request instead. |
| **`ASTWatcher` parses twice** | N/A | `self.parser.parse(bytes(text, "utf8"))` is called twice on line 27-28 of `watcher.py` — first result is thrown away | Bug — wastes CPU on every parse |
| **Nui-components sidebar** | Concept Appendix A describes a reactive `nui-components` sidebar with Signal, tabs, collapsible states | Demo implements a simpler `nui.popup`-based panel without Signals or reactive state | Acceptable for MVP, but a significant downgrade from concept's UI vision |
| **SSE event stream** | Concept Appendix A5 describes a curl-based SSE subscription from Neovim to `/events/stream` | Not implemented at all in the demo Lua | Missing feature — no real-time event streaming to Neovim outside of LSP notifications |
| **Highlight groups** | Concept Appendix A6 defines `GrailBorder`, `RemoraActive`, etc. | Not implemented in the demo | Missing — agent status colors won't display |
| **`documentSymbol` handler** | Concept architecture includes `textDocument/documentSymbol` | Not implemented | Missing LSP handler |
| **Extension tool execution** | Concept has `execute_extension_tool()` running custom tools | Demo has it as `pass` (empty stub) | Missing functionality |
| **`read_node` tool result** | Concept notes it "would need tool result handling" | Demo reads the node but does nothing with the result | Incomplete — tool call has no return path |
| **File-level IDs** | Concept §6c describes `# remora-file: rm_xyz12345` on first line | Not implemented in watcher or anywhere | Missing feature |

### 3.3 What is entirely missing ❌

| Feature | Concept Section | Notes |
|---------|----------------|-------|
| `.remora/models/` extension discovery loading | §3b, Phase 5 | `load_extensions_from_disk()` exists but `ExtensionNode` has no base class import from anywhere — it's defined at the bottom of `runner.py` after being referenced |
| Graph `get_callees()` | §5b | Only `get_callers()` is implemented; no `get_callees()` |
| `inject_ids()` integration | §6b | The function exists in `watcher.py` but is never called by the LSP server |
| Event timestamp population | Server | `emit_event()` uses `asyncio.get_event_loop().time()` which returns monotonic clock seconds, not Unix epoch — every timestamp in the DB will be wrong |
| `didClose` handler | §2b | Registered but is a bare `pass` — no cleanup |

---

## 4. Code Quality Issues

### 4.1 Critical: Synchronous SQLite on the async event loop

**Every** `RemoraDB` method is synchronous. The `sqlite3` library blocks the
thread. In an `asyncio` server like `pygls`, this means every DB read/write
freezes the entire LSP server.

```python
# Current (blocking)
cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))

# Should be
result = await asyncio.to_thread(self._get_node_sync, node_id)
```

This is the single most impactful performance issue. With a large codebase,
hover requests and code lens refreshes will stall Neovim.

### 4.2 Critical: Bare `except` in graph.py

```python
try:
    self.graph.remove_node(idx)
except:   # ← catches KeyboardInterrupt, SystemExit, everything
    pass
```

Should be `except Exception:` at minimum, or better yet
`except rx.InvalidNode:`.

### 4.3 Critical: Circular import risk

`runner.py` imports from `demo.lsp.server`:
```python
from demo.lsp.server import server, publish_diagnostics, emit_event
```

And `server.py` assigns `server.runner = runner` at runtime. The module-level
import of `server` from `runner.py` creates a hard dependency in the wrong
direction — the agent layer should not know about the LSP layer.

### 4.4 High: `get_activation_chain()` returns `list[str]`, but `trigger()` treats items as objects

```python
chain = self.server.db.get_activation_chain(correlation_id)
# ...
if agent_id in [e.agent_id for e in chain]:  # ← chain items are strings, not objects
```

`chain` is a `list[str]`, so `e.agent_id` will raise `AttributeError`.

### 4.5 High: `did_save()` accesses `old_by_key[key].remora_id` on a dict

```python
old_by_key = {(n["name"], n["node_type"]): n for n in old_nodes}
# ...
node.remora_id = old_by_key[key].remora_id  # ← dict has no .remora_id attribute
```

Should be `old_by_key[key]["id"]` (which is correctly done later for orphan
marking, but not here).

### 4.6 High: `__main__.py` never starts the LSP server

```python
async def main():
    runner = AgentRunner()
    server.runner = runner
    runner_task = asyncio.create_task(runner.run_forever())
    await asyncio.Event().wait()  # Waits forever, but server.start_io() is never called
```

The runner loop starts, but the LSP server itself never starts listening.
`server.start_io()` (or `server.start_tcp()`) is never invoked in the async
main. The `main()` in `server.py` calls `server.start_io()` but that's a
separate entry point.

### 4.7 Medium: `did_open()` publishes all proposals, not just file-specific ones

```python
await publish_diagnostics(uri, list(server.proposals.values()))
```

This publishes **every** in-memory proposal as diagnostics, not just the ones
for the opened file. Should filter by `uri`.

### 4.8 Medium: `method_definition` node type doesn't exist in tree-sitter-python

The watcher checks for `node.type == "method_definition"` (line 69), but
tree-sitter-python uses `"function_definition"` for methods too — methods are
just function definitions nested inside a class body. The `"method_definition"`
branch will never execute.

### 4.9 Low: `watcher.py` fallback parser doesn't handle methods

The regex fallback (`_parse_fallback`) only looks for `^(def|class)` at column
zero. Indented method definitions are ignored, meaning classes will be found
but their methods won't.

### 4.10 Low: `nui.popup` reference may not work

`panel.lua` requires `"nui.popup"` which is from `nui.nvim`, not
`nui-components.nvim`. The concept doc specifies nui-components. These are
different plugins with different APIs.

---

## 5. Interaction Design Evaluation

### 5.1 Strengths

- **LSP-first is correct.** Leveraging standard LSP means Neovim gets hover,
  code lenses, diagnostics, and code actions with minimal custom Lua.
- **The proposal workflow is well-designed.** Agent proposes → diagnostic
  appears → user triggers QuickFix → `WorkspaceEdit` applies. This is a
  natural, idiomatic Neovim interaction.
- **Custom notifications for input.** Using `$/remora/requestInput` to trigger
  `vim.ui.input()` keeps the UX within Neovim's native input paradigm rather
  than building custom UI.

### 5.2 Weaknesses

- **No visual feedback loop.** When an agent is "running," the code lens
  updates, but there's no animation or progress indicator. The user has no idea
  how long to wait.
- **Chat is fire-and-forget.** After sending a chat message, the user gets no
  response back in the UI. The runner processes it with a `MockLLMClient` that
  always returns zero tool calls, so nothing visible happens.
- **Panel is static.** The `nui.popup` panel renders once and only re-renders
  when explicitly called. There's no auto-refresh when events arrive.
- **No keybinding setup.** The concept mentions `<leader>ra` for expanding the
  sidebar, but no keybindings are defined anywhere in the demo.
- **`start.sh` uses bash and won't work on Windows.** The primary development
  platform is Windows per the user's OS.

---

## 6. File-by-File Summary

| File | Lines | Status | Key Issues |
|------|-------|--------|------------|
| [models.py](file:///c:/Users/Andrew/Documents/Projects/remora/demo/core/models.py) | 351 | Good | Missing filepath comment, `__future__` import. Event `__init__` overrides are non-idiomatic for Pydantic — use `model_validator` or `Field(default=...)` instead |
| [db.py](file:///c:/Users/Andrew/Documents/Projects/remora/demo/core/db.py) | 325 | Needs work | All sync I/O, missing filepath comment, no connection pooling or WAL mode |
| [graph.py](file:///c:/Users/Andrew/Documents/Projects/remora/demo/core/graph.py) | 91 | Needs work | Bare except, missing filepath comment, no `get_callees()` |
| [watcher.py](file:///c:/Users/Andrew/Documents/Projects/remora/demo/core/watcher.py) | 165 | Needs work | Double parse bug, phantom `method_definition` check, fallback misses methods |
| [server.py](file:///c:/Users/Andrew/Documents/Projects/remora/demo/lsp/server.py) | 274 | Needs work | `publish_code_lenses()` broken, dict-attribute mismatch in `did_save()`, missing `documentSymbol` handler |
| [runner.py](file:///c:/Users/Andrew/Documents/Projects/remora/demo/agent/runner.py) | 291 | Needs work | Chain check bug, circular import, `ExtensionNode` defined after use, stub `execute_extension_tool()` |
| [__main__.py](file:///c:/Users/Andrew/Documents/Projects/remora/demo/__main__.py) | 46 | Needs work | LSP server never actually starts |
| [panel.lua](file:///c:/Users/Andrew/Documents/Projects/remora/demo/nvim/lua/remora/panel.lua) | 204 | Acceptable | Static rendering, uses `nui.popup` not `nui-components`, no reactive state |
| [remora_starter.lua](file:///c:/Users/Andrew/Documents/Projects/remora/demo/nvim/lua/remora_starter.lua) | 276 | Good | Solid command registration, path discovery, dependency checks |
| [__init__.lua](file:///c:/Users/Andrew/Documents/Projects/remora/demo/nvim/lua/remora/__init__.lua) | 3 | Issue | Circular — `__init__.lua` returns `require("remora")` which would load itself |
| [remora.vim](file:///c:/Users/Andrew/Documents/Projects/remora/demo/nvim/remora.vim) | 74 | Acceptable | Functional but redundant with `remora_starter.lua`; vimscript wraps lua wraps vimscript commands |
| [start.sh](file:///c:/Users/Andrew/Documents/Projects/remora/demo/start.sh) | 79 | Issue | Bash-only, Windows-incompatible, references `remora.vim` options that don't align exactly |
| [README.md](file:///c:/Users/Andrew/Documents/Projects/remora/demo/README.md) | 132 | Good | Well-structured, accurate feature list, clear quick-start |

---

## 7. Prioritised Fix List

### P0 — Must fix (broken at runtime)

1. **`did_save()` attribute error** — `old_by_key[key].remora_id` → `old_by_key[key]["id"]`
2. **`trigger()` chain check** — `e.agent_id for e in chain` → `e for e in chain` (chain items are strings)
3. **`publish_code_lenses()` rewrite** — Remove the broken notify, trigger `codeLensRefresh()` instead
4. **`__main__.py` must start LSP server** — Call `server.start_io()` or integrate runner into `server.py`'s `main()`
5. **Event timestamps** — Use `time.time()` (Unix epoch), not `asyncio.get_event_loop().time()` (monotonic)

### P1 — Should fix (correctness / quality)

6. **Wrap all `RemoraDB` calls in `asyncio.to_thread()`** — Prevents blocking the event loop
7. **Remove double parse in `watcher.py`** — Delete line 27
8. **Fix `did_open()` diagnostics filtering** — Only publish proposals matching `uri`
9. **Fix `__init__.lua` circular require** — Should `return require("remora.init")` or be the actual init module
10. **Add `from __future__ import annotations`** to all Python files
11. **Add filepath comments** to all files

### P2 — Nice to have (completeness)

12. Implement `execute_extension_tool()` stub
13. Implement `documentSymbol` handler
14. Add `get_callees()` to `LazyGraph`
15. Wire `inject_ids()` into the save flow
16. Replace bare `except` with `except Exception`
17. Convert `Trigger` and `ExtensionNode` to Pydantic models
18. Add highlight groups to Lua setup
19. Add a Windows-compatible start script (PowerShell)

---

## Appendix A: Agent Integration Opportunities

The concept doc describes a parallel universe to the existing Remora agent
system documented in
[HOW_TO_CREATE_AN_AGENT.md](file:///c:/Users/Andrew/Documents/Projects/remora/docs/HOW_TO_CREATE_AN_AGENT.md).
Here are ideas to make these two worlds converge cleanly.

### A.1 Unify `ASTAgentNode` with `AgentState`

The concept's `ASTAgentNode` and the existing Remora `AgentState` serve the
same purpose — they are the identity card for a code-level agent. Currently
they are completely separate models.

**Proposal:** Make `ASTAgentNode` a subclass (or extension) of `AgentState`.
Add the LSP conversion methods (`to_hover()`, `to_code_lens()`, etc.) as a
mixin or protocol that `AgentState` can opt into when the LSP layer is
active. This avoids duplicating identity fields (`agent_id`, `node_type`,
`name`, `file_path`, `parent_id`, `range`).

```python
class LSPBridgeMixin:
    """Adds LSP conversion methods to any agent state object."""
    def to_code_lens(self) -> lsp.CodeLens: ...
    def to_hover(self, ...) -> lsp.Hover: ...
    def to_code_actions(self) -> list[lsp.CodeAction]: ...

class AgentState(LSPBridgeMixin, BaseModel):
    ...  # existing fields
```

### A.2 Bridge `RemoraGrailTool` → LSP `CodeAction`

The existing agent system uses `.pym` Grail scripts discovered via
`discover_grail_tools()`. The concept's `ToolSchema.to_code_action()` already
converts tool schemas to LSP code actions.

**Proposal:** When the LSP server starts, discover Grail tools for each
agent's bundle and convert their `ToolSchema` to `extra_tools` on the
`ASTAgentNode`. This means `.pym` tools automatically appear in Neovim's
code action menu — users can invoke agent tools directly from their editor.

```python
grail_tools = discover_grail_tools(bundle.agents_dir, externals, files_provider)
agent.extra_tools = [
    ToolSchema(
        name=t.schema.name,
        description=t.schema.description,
        parameters=t.schema.parameters,
    )
    for t in grail_tools
]
```

### A.3 Use Existing `EventStore` as the Backend

The concept's `RemoraDB.store_event()` and the existing Remora `EventStore`
both store events in SQLite. Rather than maintaining two separate event
stores, the LSP server should use the existing `EventStore` directly.

**Proposal:** Inject the Remora `EventStore` into `RemoraLanguageServer` and
use `event_store.append(swarm_id, event)` instead of the custom
`db.store_event()`. This makes LSP events visible to the swarm and vice
versa — the real-time event stream in Neovim would surface all swarm
activity.

### A.4 Use `SubscriptionPattern` for LSP Event Routing

The concept routes events manually. The existing `SubscriptionRegistry` +
`SubscriptionPattern` already handles event→agent routing with support for
`event_types`, `from_agents`, `to_agent`, `path_glob`, and `tags`.

**Proposal:** When the LSP server receives a `$/remora/submitInput`
notification, wrap it as a `HumanInputResponseEvent` and route it through
the `SubscriptionRegistry`. This gives agents the ability to subscribe to
human input events with patterns (e.g., only listen for messages tagged
`"review"`).

### A.5 Replace `MockLLMClient` with Actual `AgentKernel`

The demo's `AgentRunner` uses a `MockLLMClient`. The existing Remora stack
already has the full execution chain:
`AgentRunner` → `SwarmExecutor` → `AgentKernel` → `ModelAdapter` → vLLM.

**Proposal:** Instead of rebuilding the LLM integration from scratch, the
concept's `AgentRunner.execute_turn()` should delegate to the existing
`SwarmExecutor.run_agent()`. This gives the LSP demo access to the full
Grail sandbox, workspace service, and model adapter — not just a mock.

### A.6 Make `ExtensionNode` a Pydantic `BaseModel` That Mirrors `bundle.yaml`

The concept's `ExtensionNode` from `.remora/models/` is a custom-class-based
extension system. The existing agent system uses `bundle.yaml` manifests.

**Proposal:** Replace the `ExtensionNode` class hierarchy with a Pydantic
model that mirrors `bundle.yaml`:

```python
class ExtensionManifest(BaseModel):
    """Loaded from .remora/extensions/*.yaml"""
    match_node_type: str | None = None
    match_name_pattern: str | None = None
    system_prompt_append: str = ""
    extra_tools_dir: str | None = None
    mounted_workspaces: list[str] = Field(default_factory=list)
```

This is declarative (YAML, not Python code), safer (no `exec_module()`),
and consistent with the existing `bundle.yaml` pattern.

### A.7 Expose `SwarmState` via `documentSymbol`

The concept mentions `textDocument/documentSymbol` but it's not implemented.
The existing `SwarmState` registry already knows about all agents.

**Proposal:** Implement `documentSymbol` by querying `SwarmState` for all
agents in the current file and returning them as `DocumentSymbol` objects.
This gives users Neovim's built-in outline view (`Telescope lsp_document_symbols`,
breadcrumbs) populated with agent nodes — a zero-effort integration.

### A.8 Use `correlation_id` from `EventStore` for LSP Diagnostic Grouping

The existing `EventStore` uses `correlation_id` to track activation chains.
The LSP diagnostic system can group related diagnostics by
`DiagnosticRelatedInformation`.

**Proposal:** When publishing proposal diagnostics, include the
`correlation_id` as related information. This lets users trace a proposal
back through the chain of events that led to it — useful for understanding
*why* an agent proposed a change.
