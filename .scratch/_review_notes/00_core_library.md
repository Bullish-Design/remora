# Core Library Analysis Notes

## Scope

All files under `src/remora/core/` and `src/remora/utils/`. This is the
framework-agnostic runtime that underpins both the LSP server and the
demo/service layers.

---

## Module Inventory

| Module | Lines | Purpose |
|---|---|---|
| `__init__.py` | 111 | Public re-exports; barrel file |
| `config.py` | 165 | YAML-based `Config` dataclass, load/serialize |
| `events.py` | 187 | Frozen dataclass events + `RemoraEvent` union |
| `event_bus.py` | 135 | In-process pub/sub with async streaming |
| `event_store.py` | 354 | SQLite-backed event sourcing + trigger queue |
| `errors.py` | 60 | Clean error hierarchy (7 types) |
| `discovery.py` | 374 | Tree-sitter CST scanning, `CSTNode` model |
| `agent_state.py` | 84 | Per-agent JSONL state persistence |
| `agent_runner.py` | 288 | Reactive trigger consumer with cascade prevention |
| `swarm_executor.py` | 375 | Single-turn agent execution (kernel, prompt, tools) |
| `subscriptions.py` | 287 | SQLite-backed subscription registry + pattern matching |
| `swarm_state.py` | 197 | SQLite-backed agent metadata registry |
| `reconciler.py` | 183 | Startup diff: discover → swarm state → subscriptions |
| `workspace.py` | 191 | Cairn workspace wrapper + `CairnDataProvider` |
| `cairn_bridge.py` | 183 | Cairn workspace lifecycle (stable + per-agent) |
| `cairn_externals.py` | 71 | Path-normalizing Grail external functions |
| `vcs.py` | 35 | Jujutsu commit adapter (minimal) |
| `chat.py` | 259 | Standalone chat session (separate from swarm) |
| `tools/__init__.py` | 7 | Re-exports |
| `tools/grail.py` | 145 | `.pym` script tool adapter for structured-agents |
| `tools/swarm.py` | 324 | 5 swarm tools (send_message, subscribe, unsubscribe, broadcast, query_agents) |
| **Utils:** | | |
| `utils/__init__.py` | 15 | Re-exports |
| `utils/types.py` | 17 | `PathLike` alias, `normalize_path` |
| `utils/path_resolver.py` | 74 | `PathResolver` dataclass, `to_project_relative` |
| `utils/text.py` | 19 | `truncate` / `summarize` |
| `utils/fs.py` | 25 | `managed_workspace` async context manager |

**Total core lines:** ~3,900+

---

## Architecture Overview

```
                  ┌─────────────┐
                  │  Config      │ YAML → frozen dataclass
                  └──────┬──────┘
                         │
   ┌─────────────────────┼─────────────────────┐
   │                     │                     │
   ▼                     ▼                     ▼
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│ Discovery │     │  Reconciler  │     │  EventBus    │
│ tree-sitter    │  startup diff │     │  pub/sub     │
└──────┬───┘     └──────┬───────┘     └──────┬───────┘
       │                │                     │
       ▼                ▼                     ▼
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│ CSTNode   │     │ SwarmState   │     │  EventStore  │
│ frozen DC │     │ SQLite agents│     │ SQLite events│
└───────────┘     └──────┬───────┘     └──────┬───────┘
                         │                     │
                         ▼                     ▼
                  ┌──────────────┐     ┌──────────────┐
                  │ AgentRunner  │◄────│ Subscriptions│
                  │ trigger loop │     │ SQLite subs  │
                  └──────┬───────┘     └──────────────┘
                         │
                         ▼
                  ┌──────────────┐
                  │SwarmExecutor │
                  │ kernel + tools│
                  └──────┬───────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
        ┌─────────┐ ┌────────┐ ┌────────────┐
        │ Grail   │ │ Swarm  │ │ Cairn      │
        │ tools   │ │ tools  │ │ workspace  │
        └─────────┘ └────────┘ └────────────┘
```

The data flow is:

1. **Discovery** scans source → CSTNodes (deterministic IDs)
2. **Reconciler** diffs discovered nodes vs SwarmState → creates/orphans agents
3. **EventStore** persists events → matches against **Subscriptions** → queues triggers
4. **AgentRunner** consumes triggers → dispatches to **SwarmExecutor**
5. **SwarmExecutor** loads bundle manifest → builds prompt from workspace files → runs kernel
6. Kernel uses **Grail tools** (`.pym` scripts) + **Swarm tools** (messaging/subscriptions)
7. Workspace access goes through **Cairn bridge** (stable + per-agent CoW isolation)

---

## Detailed Findings

### F-01: Config uses stdlib dataclass, not Pydantic

`config.py:37` — `Config` is a `@dataclass(slots=True)`. The V2.1 concept says
"Pydantic models are the bridge". The LSP layer uses Pydantic exclusively
(`lsp/models.py`), but the core Config does not. This creates an inconsistency:
the LSP layer validates with Pydantic, the core layer doesn't validate at all.

`_build_config` at line 106 does `Config(**data)` — no validation. Unknown keys
are silently passed and would raise `TypeError`. Missing required keys get
defaults. There's no schema validation, no environment variable override support,
no `.env` file loading.

**Severity:** Medium. The Config works but lacks the rigor Pydantic would provide
(validation, env override, schema generation for docs).

### F-02: serialize_config is hand-rolled instead of using dataclass machinery

`config.py:117-153` — `serialize_config` manually enumerates every field. This
means adding a field to `Config` requires updating `serialize_config` too. With
`dataclasses.asdict()` or Pydantic `model_dump()` this would be automatic.

The `normalize` helper recursively converts tuples to lists, which is needed for
YAML output. But this could be a single `dataclasses.asdict()` call with a
custom dict factory.

**Severity:** Low. Maintenance burden but not a bug.

### F-03: Duplicate ignore pattern definitions

`config.py:22-34` defines `DEFAULT_IGNORE_PATTERNS`. `discovery.py:307` has a
separate hardcoded `ignore_patterns` set inside `_walk_directory`. These are
different lists — config has `.agentfs`, `.jj`, `.mypy_cache`, `.remora` that
discovery's hardcoded set doesn't have. And discovery always skips dotfiles
(`.startswith(".")`) while config has a `workspace_ignore_dotfiles` toggle.

The discovery module ignores the config entirely — it uses its own hardcoded set.
This means `workspace_ignore_patterns` in config only affects workspace syncing,
not discovery. This is confusing.

**Severity:** Medium. Two independent ignore systems that users would expect to
be one.

### F-04: Events are frozen but AgentMessageEvent has mutable `list[str]` field

`events.py:103` — `AgentMessageEvent` has `tags: list[str]`. A frozen dataclass
doesn't freeze the contents of mutable fields. You can still `event.tags.append("x")`.
This violates the promise of immutability stated in the module docstring.

Should be `tuple[str, ...]` (like `HumanInputRequestEvent.options`).

**Severity:** Low. Unlikely to cause bugs in practice but inconsistent.

### F-05: RemoraEvent union type is a plain `|` union, not discriminated

`events.py:138-162` — `RemoraEvent` is a `Union` of 14 types. This works for
`isinstance()` checks but doesn't support pattern matching as cleanly as a
tagged union. The module docstring says events "can be pattern-matched" but
Python `match` requires individual `case AgentStartEvent():` arms — the union
type itself doesn't help.

Also: `FileSavedEvent` and `ManualTriggerEvent` are defined but NOT exported in
`core/__init__.py` (line 28-44). They're in `__all__` of `events.py` but not
re-exported at the package level. This suggests they may be unused or were
intended for future use.

**Severity:** Low. Design choice, but the missing re-exports are an oversight.

### F-06: EventBus handler error suppression

`event_bus.py:56-57` — When a handler throws, the error is logged as a warning
and silently swallowed. This is intentional for resilience but means event
handling failures are invisible. There's no mechanism for dead-letter queues,
retry, or error propagation.

Also: `subscribe` at line 62 does identity comparison (`handler not in handlers`)
which relies on function identity. Lambda subscribers can't be deduplicated.

**Severity:** Low. Pragmatic for now but will need error escalation paths.

### F-07: EventStore uses `asyncio.to_thread` for ALL SQLite operations

`event_store.py` — Every database operation goes through `asyncio.to_thread()`.
This is correct (SQLite is blocking) but creates per-call thread overhead. The
`asyncio.Lock` at line 37 serializes access, so there's never concurrent DB
access anyway — the threading is purely to avoid blocking the event loop.

The same pattern is used in `subscriptions.py` and `swarm_state.py`. Three
modules each with their own SQLite connection + asyncio.Lock + to_thread wrapper.

**Alternative:** aiosqlite would be cleaner and is well-tested. Or a shared
connection pool / single DB service.

**Severity:** Medium. Works but creates unnecessary complexity and potential for
subtle issues (three separate connections to potentially different DBs).

### F-08: Three separate SQLite databases

The core layer uses three separate SQLite DBs:
1. `EventStore` — events DB (path from constructor)
2. `SubscriptionRegistry` — subscriptions DB (path from constructor)
3. `SwarmState` — agents DB (path from constructor)

Plus the LSP layer has its own `RemoraDB` (fourth DB), and per-agent Cairn
workspaces add more.

These could be consolidated. The separation means cross-table queries are
impossible (e.g., "which agents have events pending?") and there's no
transaction coordination. The reconciler at startup has to coordinate across
all three manually.

**Severity:** Medium. Architectural complexity without clear benefit. A single
DB with multiple tables would be simpler and more performant.

### F-09: AgentState JSONL append-only persistence

`agent_state.py:69-80` — `save()` appends state as a new JSONL line. `load()`
reads the last line. This is append-only event sourcing in miniature. But:

- Files grow unbounded. No compaction.
- `load()` reads the ENTIRE file to get the last line (line 59).
- No concurrent access protection (no file locking).
- The `last_updated` field is mutated before save (line 77), even though
  `AgentState` is a regular (non-frozen) dataclass.

The JSONL format is fine for debugging (you can see history) but inefficient for
production. A single JSON file with `write` instead of `append` would be simpler
for the "only care about latest state" access pattern.

**Severity:** Medium. Will cause slow reads and disk bloat over long-running
swarms.

### F-10: AgentRunner cascade prevention is correlation-based but fragile

`agent_runner.py:80-82` — Cascade prevention tracks `(agent_id, correlation_id)`
pairs with depth counts. But:

- `_normalize_correlation_id` (line 149) falls back to `"base"` when there's no
  correlation_id. This means ALL uncorrelated events share the same depth counter
  per agent. If two unrelated events trigger the same agent, the second one might
  be rejected due to the first's depth accumulation.

- The depth counter is **decremented** in the finally block (line 183-188).
  This means concurrent triggers for the same agent+correlation could have
  interleaving depth updates. The semaphore prevents concurrent execution but
  the depth tracking is not atomic with execution.

- The cleanup loop (line 121) uses a 300-second TTL. This is hardcoded and not
  configurable.

**Severity:** Medium. The cascade prevention works for simple cases but has edge
cases that could cause either over-blocking or under-blocking.

### F-11: SwarmExecutor._run_kernel creates a new client per execution

`swarm_executor.py:273-280` — Every `_run_kernel` call creates a new
`build_client(...)` with a new HTTP client. This means no connection pooling
across agent turns. For a local vLLM server this is acceptable but for remote
APIs it's wasteful.

Also: `_EventStoreObserver` (line 281-288) is a nested class defined inside the
method. This is fine functionally but unusual — it could be a top-level class.

**Severity:** Low. Performance consideration for high-throughput scenarios.

### F-12: SwarmExecutor hardcodes `manifest.model` for parser selection

`swarm_executor.py:270` — `get_response_parser(manifest.model)` uses the
manifest's model name. But `_resolve_model_name` (line 247) may override the
actual model used. So the parser might be selected for model A while the actual
request goes to model B. This could cause parsing failures with different model
response formats.

**Severity:** High. Potential for silent parsing errors when model names differ
between manifest and runtime override.

### F-13: SwarmExecutor chat history is truncated to last 10 entries

`swarm_executor.py:229` — `state.chat_history = state.chat_history[-10:]`. This
is a hard limit with no configuration. For complex multi-turn conversations,
losing history could degrade agent performance. The truncation is also applied
unconditionally, even if the history is within limits.

Combined with F-09 (JSONL append), every turn appends the full (truncated)
history as a new line to the JSONL file.

**Severity:** Low. Reasonable default but should be configurable.

### F-14: SwarmExecutor._build_prompt duplicates history

`swarm_executor.py:344-353` — The prompt builder appends the last 5 chat history
entries as "Recent Chat History". But `_run_kernel` at line 298-302 ALSO appends
the full chat history as messages to the kernel. So the LLM sees history both
in the system-level message context AND in the user prompt text. This is
redundant and could confuse the model.

**Severity:** Medium. The model sees duplicate context which wastes tokens and
could cause confusion.

### F-15: Subscriptions pattern matching loads ALL subscriptions every time

`subscriptions.py:243-277` — `get_matching_agents` loads every subscription row
from SQLite and does in-memory pattern matching. For large swarms (hundreds of
agents with multiple subscriptions each), this is O(n) per event. No indexing
on event_type, no caching of active subscriptions.

Also: local `logger = logging.getLogger(__name__)` at line 246 is re-created
inside the method instead of using the module-level logger. This is a minor
code smell.

**Severity:** Medium for large swarms. Fine for current scale but doesn't scale
to thousands of agents.

### F-16: SubscriptionPattern.matches uses `normalize_path` on event path

`subscriptions.py:60` — `normalize_path(path)` converts a string to `Path`.
This means path matching is platform-dependent. On Windows, `PurePath.match()`
would behave differently than on Linux. For a tool meant to run in containers
this is fine, but it's not explicit.

**Severity:** Low. Only matters for cross-platform usage.

### F-17: Reconciler doesn't update SwarmState metadata for existing agents

`reconciler.py:130-161` — For common IDs (agents that exist in both discovery
and swarm state), the reconciler only checks if the file was modified and emits
ContentChangedEvent. It does NOT update the metadata (name, line range, etc.)
if the code changed. If a function moves from line 10 to line 50, the SwarmState
still has the old line numbers.

This means CodeLens positions could drift from reality over time without a
full re-reconciliation.

**Severity:** High. Stale metadata will cause incorrect CodeLens positioning
and hover information.

### F-18: Workspace sync reads entire project into SQLite

`cairn_bridge.py:138-162` — `_sync_project_to_workspace` uses `rglob("*")` to
walk the entire project tree and writes every file into the stable workspace DB.
For large projects, this could be very slow at startup and create large SQLite
databases.

There's no incremental sync — every startup does a full sync. No mtime
comparison, no content hashing, no skip-if-unchanged.

**Severity:** Medium. Startup performance scales linearly with project size.

### F-19: CairnWorkspaceService.ensure_file_synced is a stub

`cairn_bridge.py:164-166` — `ensure_file_synced` always returns `True` without
doing anything. It's referenced as a callback in `AgentWorkspace.__init__`
(workspace.py:36) and called when a file isn't found in either agent or stable
workspace (workspace.py:71-74). The callback is supposed to sync the file but
doesn't.

**Severity:** Medium. File-not-found errors will be raised instead of syncing
on demand.

### F-20: AgentWorkspace.read has unreachable code after fallback

`workspace.py:55-75` — The read method tries agent workspace, then stable
workspace, then `ensure_file_synced` + stable workspace again. But if the
stable workspace read at line 66 raises a non-missing-file error, it propagates
immediately. The `ensure_file_synced` path at line 71 is only reached if the
stable workspace read raised a FileNotFoundError-like error. This is correct
but the flow is hard to follow.

More concerning: after the `async with self._stable_lock` block at line 64-69,
if `_is_missing_file_error(exc)` is True, the function falls through to line 71
WITHOUT returning. But if the `async with self._stable_lock` block at line 64
SUCCEEDS, it returns. The two `async with self._stable_lock` blocks could
deadlock if `_stable_lock` is a regular Lock (not reentrant). However, the
second one at line 73 is only reached after the first one at line 64 has
released the lock, so it's fine. Still, the control flow is convoluted.

**Severity:** Low (no bug, but poor readability).

### F-21: chat.py duplicates SwarmExecutor's kernel setup

`chat.py:135-177` — The `ChatSession.send` method builds its own client,
adapter, kernel — duplicating the setup in `SwarmExecutor._run_kernel`. These
two code paths will inevitably drift. chat.py also hardcodes model-specific
defaults:
- `model_name: str = "Qwen/Qwen3-4B-Instruct-2507-FP8"` (line 60)
- `model_base_url: str = "http://remora-server:8000/v1"` (line 61)

And calls `self._workspace.cleanup()` (line 209) which doesn't exist on
`CairnWorkspaceService` (it has `close()`).

**Severity:** High. Method name mismatch will cause AttributeError at runtime.
Code duplication will cause drift.

### F-22: chat.py build_chat_tools uses Tool.from_function

`chat.py:212-258` — `build_chat_tools` creates tools using
`structured_agents.Tool.from_function`. This is a different tool interface from
`RemoraGrailTool` (which uses `ToolSchema` + `execute`). Two different ways to
create tools in the same codebase.

Also `discover_symbols` (line 238) calls `discover([target])` synchronously in
an async function. Discovery uses ThreadPoolExecutor internally so this is safe,
but mixing sync/async call patterns is confusing.

**Severity:** Low. Two tool creation patterns is slightly confusing but both work.

### F-23: VCSAdapter only supports Jujutsu

`vcs.py:22` — Only checks for `.jj` directory. No git support despite git being
far more common. The entire module is 35 lines and currently commented out in
SwarmExecutor (line 234). Effectively dead code.

**Severity:** Low. It's not used, but if it were, it would only work with jj.

### F-24: Discovery TreeSitterDiscoverer is a legacy wrapper

`discovery.py:338-362` — `TreeSitterDiscoverer` is described as a "compatibility
wrapper that exposes the old API". It wraps the `discover()` function. This
should be deprecated/removed once all callers use `discover()` directly.

The class also accepts a `query_pack` parameter that is **never used** — the
underlying `discover()` function doesn't accept it. Dead parameter.

**Severity:** Low. Legacy code that should be removed.

### F-25: discovery._extract_name parent matching is fragile

`discovery.py:202-214` — `_extract_name` looks for `.name` captures where
`n.parent == node`. This works for simple cases but fails when the name node
is deeper in the tree (e.g., `node > wrapper > identifier`). Falls back to
looking for `identifier`/`name`/`function_name` child types.

For a Python `class Foo(Bar):`, tree-sitter's `class_definition` node has the
name as a direct child, so this works. But for languages with more complex ASTs
(TypeScript generics, Rust lifetimes), the fallback may not find names.

**Severity:** Low. Works for Python, may need extension for other languages.

### F-26: SwarmExecutor._build_prompt includes code in fenced block without language tag

`swarm_executor.py:333-335` — The prompt uses bare ` ``` ` fences without a
language identifier. For Python files, adding ` ```python ` would help LLMs
understand the code better.

**Severity:** Low. Minor prompt quality improvement.

### F-27: Config.model_base_url and model_default are duplicated with chat.py

`config.py:50-51` defaults: `model_base_url = "http://localhost:8000/v1"` and
`model_default = "Qwen/Qwen3-4B"`.
`chat.py:60-61` defaults: `model_name = "Qwen/Qwen3-4B-Instruct-2507-FP8"` and
`model_base_url = "http://remora-server:8000/v1"`.
`lsp/__main__.py` hardcodes yet another: `model = "Qwen/Qwen3-4B-Instruct-2507-FP8"`.

Three different default model configs in three places.

**Severity:** High. Inconsistent defaults will cause confusion and runtime
failures when moving between contexts.

### F-28: _find_config_file stops at pyproject.toml boundary

`config.py:92-103` — Config search walks up directories but stops when it finds
a `pyproject.toml`. This is reasonable for monorepos but means nested projects
can't inherit parent configs. Also, the return value when no config is found
(line 103) returns `current / "remora.yaml"` which doesn't exist — then
`load_config` at line 77 returns defaults. This is a valid sentinel pattern but
not obvious.

**Severity:** Low. Works correctly, just not obvious.

### F-29: Config._build_config doesn't handle `ConfigError` import correctly

`config.py:85-87` — Inside `load_config`, `ConfigError` is imported locally
with `from remora.core.errors import ConfigError`. But then at line 156,
there's a MODULE-LEVEL `from remora.core.errors import ConfigError`. The local
import is unnecessary — the module-level one is always available. The local
import was probably added to avoid circular import, but the module-level one
proves there's no circular issue.

**Severity:** Low. Unnecessary duplicate import.

### F-30: build_virtual_fs creates duplicate path entries

`tools/grail.py:98-105` — For each file, both `normalized` and
`/normalized` are added. This doubles the memory usage of the virtual FS.
It's done to handle both absolute and relative path lookups, but it's a
workaround rather than a proper path normalization strategy.

**Severity:** Low. Memory waste but functionally correct.

### F-31: Swarm tools use externals dict as a poor man's dependency injection

`tools/swarm.py` — All five tool classes receive `externals: dict[str, Any]`
in their constructor and look up specific keys at runtime. If a key is missing,
the tool returns an error string. This is fragile — there's no type checking,
no interface contract, no way to know what externals a tool needs without
reading its `execute()` method.

`SwarmExecutor.run_agent` (lines 101-171) builds the externals dict with
specific key names that must match what the tools expect. This is a coupling
that's invisible at the type level.

**Severity:** Medium. Works but violates the "Pydantic models as bridge" concept.
A proper protocol or typed config would be much cleaner.

### F-32: SwarmExecutor references `emit_event` before assignment

`swarm_executor.py:116` — `_broadcast` references `emit_event` (without `self.`
prefix) which is the local variable that hasn't been assigned yet at that point
in the code flow. Actually, looking more carefully, `_broadcast` is defined as a
closure and `emit_event = _emit_event` doesn't exist — the variable is directly
assigned as `externals["emit_event"] = _emit_event` at line 167. The `_broadcast`
function at line 116 checks `if not emit_event:` but `emit_event` is not in
scope — it references the EXTERNALS key `emit_event` via... no, it's a free
variable. This is `_emit_event` (the local async function defined at line 101).

Wait — re-reading: line 116 says `if not emit_event:`. But `emit_event` is not
a local variable at that point. `_emit_event` is defined at line 101, and
`emit_event` is set as `externals["emit_event"] = _emit_event` at line 167. The
closure captures `emit_event` which... doesn't exist as a variable name. This
references the name from `externals` dict? No — Python closures capture by name,
and `emit_event` is never assigned as a bare name. This would be a NameError
at runtime.

**Actually:** Looking again, this appears to be a latent bug. The variable name
`emit_event` in the `_broadcast` closure doesn't match any local variable. It
should be `_emit_event` (the locally-defined async function). This would cause
a `NameError` the first time `_broadcast` is actually called.

**Severity:** High. Latent NameError bug in broadcast path. Untested code path.

---

## V2.1 Alignment Assessment (Core Layer)

### ALIGNED:

1. **Event sourcing with SQLite** — EventStore implements the "reactive swarm"
   concept with persistent events, subscription matching, and trigger queues. ✓
2. **Deterministic agent IDs from code** — `compute_node_id` creates SHA256-based
   IDs from file path + name + line range. ✓
3. **Tree-sitter discovery** — Proper language-aware AST scanning. ✓
4. **Subscription-based routing** — Agents subscribe to event patterns, events
   are matched and routed. ✓
5. **Cascade prevention** — Depth limits and cooldowns prevent infinite loops. ✓
6. **Agent isolation via workspaces** — Each agent gets a Cairn workspace with
   CoW semantics. ✓
7. **Grail tool integration** — `.pym` scripts as agent tools. ✓
8. **Swarm tools** — Agents can message, broadcast, subscribe, query other agents. ✓

### NOT ALIGNED:

1. **Config not Pydantic** — V2.1 says Pydantic everywhere. Config uses stdlib
   dataclass. (F-01)
2. **Three separate SQLite DBs** — V2.1 implies a unified data layer. Core has
   fragmented storage. (F-08)
3. **No Pydantic validation on agent state** — AgentState is a plain dataclass
   with manual serialization. (F-09)
4. **No structured error propagation** — EventBus swallows errors. No dead-letter
   pattern. (F-06)
5. **Workspace sync is full-copy** — No incremental sync, no content addressing.
   This doesn't match a "reactive" architecture. (F-18)

### PARTIALLY ALIGNED:

1. **Model configuration** — Config exists but defaults are inconsistent across
   modules. Three different default model configs. (F-27)
2. **Reconciler updates** — Creates new agents and orphans deleted ones, but
   doesn't update metadata for existing agents. (F-17)

---

## Code Quality Assessment

### Strengths:

- **Clean module boundaries** — Each module has a clear single responsibility.
- **Consistent `__all__` exports** — Every module defines `__all__`.
- **Type annotations throughout** — Good use of `TYPE_CHECKING`, `Any`, unions.
- **Frozen dataclasses for events** — Immutability is the right choice.
- **`slots=True` on data classes** — Memory efficient.
- **Async-first** — Everything that could block uses `asyncio.to_thread`.
- **Error hierarchy** — Clean base exception with typed subclasses.
- **PathResolver** — Elegant frozen dataclass for path normalization.
- **CairnExternals** — Clean delegation pattern with path normalization.

### Weaknesses:

- **Three SQLite DBs** — Should be one.
- **Manual serialization** — Config, AgentState both hand-roll ser/deser.
- **Externals dict** — Stringly-typed dependency injection.
- **Duplicate code** — chat.py vs SwarmExecutor kernel setup.
- **Hardcoded values** — Model names, URLs, timeouts scattered across modules.
- **Missing tests for code paths** — Broadcast has a latent NameError (F-32).
- **JSONL unbounded growth** — AgentState files grow forever.
- **Convoluted control flow** — workspace.py read method.

---

## Ideas for Improvement

### I-01: Unified Pydantic Config
Replace `Config` dataclass with Pydantic `BaseSettings`. Get env var override,
validation, `.env` file loading for free. Define model config as a nested model.

### I-02: Single SQLite Database
Merge EventStore, SubscriptionRegistry, and SwarmState into one database with
separate tables. Add a shared connection pool. Cross-table queries become
possible.

### I-03: Typed Externals Protocol
Replace `dict[str, Any]` externals with a `Protocol` or Pydantic model. Tools
declare their dependencies as typed fields. SwarmExecutor constructs the typed
object.

### I-04: Incremental Workspace Sync
Use file mtime or content hash to skip unchanged files during workspace sync.
Watch for filesystem events instead of full-scan on startup.

### I-05: AgentState Compaction
Either switch to single-JSON-file persistence, or add a compaction routine that
rewrites the JSONL file with only the latest state entry.

### I-06: Kernel Factory
Extract the client/adapter/kernel creation logic from both `SwarmExecutor` and
`ChatSession` into a factory function or class. Single source of truth for
kernel configuration.

### I-07: Discovery Config Unification
Pass ignore patterns from Config into discovery's `_walk_directory`. Remove the
hardcoded ignore set.

### I-08: Event Bus Error Handling
Add configurable error handlers to EventBus. Options: log, dead-letter queue,
propagate. Default to log (current behavior) but allow upgrading.

### I-09: Subscription Caching
Cache loaded subscriptions in memory with invalidation on register/unregister.
Avoid loading all rows from SQLite on every event.

### I-10: Connection Pooling for LLM Client
Create the LLM client once per SwarmExecutor lifecycle and reuse across agent
turns. The HTTP client can maintain a connection pool to the model server.
