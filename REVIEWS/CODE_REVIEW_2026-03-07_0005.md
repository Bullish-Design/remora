# Remora Library — Detailed Code Review

**Scope:** Every module in `src/remora/` — core, lsp, runner, companion, service, workspace, utils, extensions, adapters, ui.

---

## Critical Issues

### 1. `agent_node.py` — `try/except ImportError` on hard dependency `lsprotocol`

> [!CAUTION]
> REPO_RULES explicitly says: *"Import unconditionally (no `try/except ImportError` guards)."* `lsprotocol` is a hard dependency in `pyproject.toml`, yet `AgentNode` wraps 6 methods in `try: from lsprotocol ... except ImportError: return None`.

**Files:** [agent_node.py](file:///home/andrew/Documents/Projects/remora/src/remora/core/agents/agent_node.py#L53-L56), lines 53–56, 135–138, 182–185, 206–209, 236–239, 275–278

**Fix:** Remove the guards; import `lsprotocol.types` at module level. If `AgentNode` is truly meant to be usable without `lsprotocol`, then the LSP conversion methods belong on a separate adapter — not guarded `try/except` blocks on a core model.

---

### 2. `agent_node.py` line 16 — bare `pass` statement

A bare `pass` on [line 16](file:///home/andrew/Documents/Projects/remora/src/remora/core/agents/agent_node.py#L16) between the pydantic import and the `SubscriptionPattern` import. This is dead code, likely a leftover from a deleted import. Delete it.

---

### 3. `discovery.py` — major DRY violation between `_parse_file` and `parse_content`

[_parse_file](file:///home/andrew/Documents/Projects/remora/src/remora/core/code/discovery.py#L132-L206) and [parse_content](file:///home/andrew/Documents/Projects/remora/src/remora/core/code/discovery.py#L517-L605) are near-identical (~70 lines each) with the only difference being where content comes from (disk vs. argument). They should share a common `_parse_nodes(file_path, content, language)` helper.

Similarly, `_create_file_node` / `_create_file_node_from_content` are duplicated — they differ only in whether content is read from disk or passed in. Merge into one function with an optional `content` parameter (which `_create_file_node` already supports).

---

### 4. `CompanionDispatcher.start()` — wrong `EventBus` API

[dispatcher.py:72](file:///home/andrew/Documents/Projects/remora/src/remora/companion/dispatcher.py#L72): calls `self._bus.subscribe(event_type.__name__, handler_callback)`, but `EventBus.subscribe()` takes `(event_type: type, handler)` — a **type**, not a string. This means companion event routing is completely broken.

Similarly, [dispatcher.py:86](file:///home/andrew/Documents/Projects/remora/src/remora/companion/dispatcher.py#L86): calls `self._bus.publish(new_event)`, but `EventBus` has no `publish()` method — it has `emit()`. This will raise `AttributeError` at runtime.

---

### 5. `CompanionDispatcher.start()` — broken closure over `make_on_event`

[dispatcher.py:64-69](file:///home/andrew/Documents/Projects/remora/src/remora/companion/dispatcher.py#L64-L69): `make_on_event` is defined as `async def` but is used to create closures in a loop. The `async` is unnecessary and misleading — it causes `make_on_event(handler_ids)` to return a coroutine object rather than executing the closure factory immediately. The `await` on line 71 resolves this, but the pattern is confusing and fragile. Use a plain `def` instead.

---

### 6. `__main__.py` — broken import path `remora.core.discovery`

[lsp/__main__.py:159](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#L159): `from remora.core.discovery import parse_content`. This works only because a `sys.modules` redirect proxy exists at `core/discovery.py`. The canonical import is `remora.core.code.discovery`. Using the redirect makes code harder to navigate and couples to a deprecated alias.

---

## Architectural Concerns

### 7. 20 `sys.modules` redirect proxies in `core/`

The `core/` directory has **20 one-file proxies** (e.g., `core/discovery.py`, `core/event_bus.py`, `core/agent_node.py`) that do nothing but `sys.modules[__name__] = _target`. These exist for backward compatibility after a restructuring into `core/agents/`, `core/events/`, `core/store/`, `core/code/`.

This is tech debt. Each proxy is a trap — it silently redirects imports, breaking IDE navigation ("go to definition"), confusing `mypy`, and making the codebase harder to audit. These should be deleted and all imports updated to canonical paths. A deprecation cycle via `warnings.warn` would be more explicit if backward compatibility is truly needed.

---

### 8. `EventStore` is a god object

[event_store.py](file:///home/andrew/Documents/Projects/remora/src/remora/core/store/event_store.py) is 849 lines and owns:
- Event append (write path)
- Event replay (read path)
- Node CRUD (`get_node`, `list_nodes`, `set_node_status`, `remove_nodes_for_file`, `get_node_at_position`)
- WAL checkpoint management
- Trigger queue management
- Subscription dispatch

This conflates the event store (write-ahead log) with the node read model (materialized view). `get_node` / `list_nodes` / `set_node_status` should live on a `NodeStore` or `NodeRepository` that reads from the `nodes` table, not on `EventStore`.

---

### 9. `AgentRunner` is also a god object (833 lines)

[agent_runner.py](file:///home/andrew/Documents/Projects/remora/src/remora/runner/agent_runner.py) handles: trigger ingestion, cascade prevention, command queue polling, event emission (7 `_emit_*` helper methods that duplicate `RemoraLanguageServer` methods), workspace lifecycle, proposal creation, extension application, and execution delegation. The event emission helpers especially are pure boilerplate — each one checks `_supports_server_method`, falls back to constructing a model and calling `emit_event`. This is the kind of indirection that a protocol/interface would eliminate.

---

### 10. Dual event models — `CoreEvent` vs `LspAgentEvent`

There are two parallel event hierarchies:
- **Core events** in `core/events/events.py` — frozen Pydantic models, stored in EventStore
- **LSP events** in `runner/events.py` — `LspAgentEvent` subclasses (`LspHumanChatEvent`, `LspAgentMessageEvent`, etc.)

These overlap significantly (e.g., `AgentMessageEvent` vs. `LspAgentMessageEvent`). The LSP events exist to carry `correlation_id` and an `event_type` string, but the core events already have a type via their class. This duplication means event handling code must handle both hierarchies.

---

## Code Quality Issues

### 11. `event_store.py` — excessive diagnostic logging

The `batch_append` method (lines 235–501) has **22 log statements** including per-event timing, per-phase timing, per-chunk timing, slow-threshold warnings, and progress reports. This is instrumentation that belongs in a separate tracing/metrics layer, not inline in business logic. The method is ~270 lines long, of which roughly half is logging.

---

### 12. `__main__.py` — 525-line function with deeply nested closures

`_run_server` + `_background_scan` is a single sprawling function with ~10 nested closures, local class definitions, and manual state management. `_background_scan` alone is ~220 lines nested inside `_run_server`, using `nonlocal` for state. This should be extracted into a `BackgroundScanner` class.

---

### 13. `__main__.py` — duplicated skip-dir list

`_background_scan` hard-codes `_SKIP_DIRS` (line 185–201), which partially duplicates `DEFAULT_IGNORE_PATTERNS` from `config.py` (lines 26–38) and `_walk_directory`'s `ignore_patterns` in `discovery.py` (line 495). These three lists should be unified.

---

### 14. `RemoraLanguageServer` — `timestamp=0.0` sentinel

All `emit_*` methods in [server.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py) and [agent_runner.py](file:///home/andrew/Documents/Projects/remora/src/remora/runner/agent_runner.py) construct event objects with `timestamp=0.0`, then `emit_event` patches it with `time.time()` on line 274. This is a leaky construction pattern — callers must know that `0.0` is a sentinel. Use `Field(default_factory=time.time)` on the model (which `CoreEvent` already does) or a builder function.

---

### 15. `RemoraLanguageServer.__init__` — untyped `event_store` parameter

The constructor takes `event_store=None` with no type annotation. This means consumers can't know what API `event_store` provides without reading implementation code. Same for `subscriptions=None`. Add type hints.

---

### 16. `RemoraLanguageServer` — private attrs set externally

`server._handlers_registered`, `server._remora_initialized_handler_registered`, `server._remora_startup_log`, `server._remora_startup_t0`, `server._remora_background_scan`, `server._notify_agents_updated` are all set by `__main__.py` on the server instance from outside the class. This is fragile — these belong as proper attributes declared in `__init__`.

---

### 17. `extensions.py` — unused `inspect` import

[extensions.py:12](file:///home/andrew/Documents/Projects/remora/src/remora/extensions.py#L12): `import inspect` is never used. Delete it.

---

### 18. `state_manager.py` — no-op `model_post_init`

[AgentTurnState.model_post_init](file:///home/andrew/Documents/Projects/remora/src/remora/core/agents/state_manager.py#L41-L43) overrides the hook with a docstring claiming "Update timestamp on any modification" but the body is just `pass`. Either implement the timestamp update or remove the override.

---

### 19. `EventBus.subscribe` — `isinstance` dispatch leads to O(n) handler lookup

[event_bus.py:48-50](file:///home/andrew/Documents/Projects/remora/src/remora/core/events/event_bus.py#L48-L50): On every `emit()`, the bus iterates **all** registered types checking `isinstance(event, registered_type)`. With many event types, this is O(types × handlers). A `dict[type, list]` with exact-type lookup + MRO cache would be much more efficient.

---

### 20. `projections.py` — f-string SQL construction

[projections.py:195](file:///home/andrew/Documents/Projects/remora/src/remora/core/code/projections.py#L195): `f"INSERT INTO nodes ({cols}) VALUES ({placeholders})"`. While `cols` comes from trusted `row.keys()`, constructing SQL with f-strings is a code smell and makes static analysis harder. Consider using a constant column list.

---

### 21. Inconsistent `__all__` exports

Some modules define comprehensive `__all__` lists (`events.py`, `event_bus.py`), while others omit it entirely (`server.py`, `companion/dispatcher.py`). This inconsistency makes it unclear what the public API of each module is.

---

### 22. `__main__.py` — `asyncio.get_event_loop()` usage

[server.py:79](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py#L79) and [server.py:128](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py#L128): `asyncio.get_event_loop()` is deprecated since Python 3.12 when there's no running loop. Since this code runs inside the pygls event loop, `asyncio.get_running_loop()` is the correct call.
