# structured-agents v0.3.0 — Refactor Concept

## Executive Summary

v0.3.0 is a ground-up refactor of structured-agents' grail integration layer. The current implementation underutilizes grail's capabilities: it passes raw dicts instead of `Limits` objects, reads hand-written JSON files instead of using grail's parsed metadata, wraps execution in unnecessary subprocess isolation, and ignores grail's event system, output validation, and virtual filesystem entirely.

The refactor treats .pym scripts as **pure functions** — data flows in via grail's virtual filesystem (populated eagerly from a database), scripts compute and return validated results, and the host persists mutations after execution. No side effects during script execution.

---

## Table of Contents

1. [Problems with v0.2](#1-problems-with-v02)
2. [Design Principles](#2-design-principles)
3. [Architecture Overview](#3-architecture-overview)
4. [Component Design](#4-component-design)
   - [ToolRegistry](#41-toolregistry)
   - [ToolExecutor](#42-toolexecutor)
   - [DataProvider](#43-dataprovider)
   - [ResultHandler](#44-resulthandler)
   - [Event Bridge](#45-event-bridge)
   - [Limits Integration](#46-limits-integration)
   - [Error Handling](#47-error-handling)
   - [Externals (Typed Factory)](#48-externals-typed-factory)
5. [Script Authoring Changes](#5-script-authoring-changes)
6. [Bundle Configuration Changes](#6-bundle-configuration-changes)
7. [Migration Path](#7-migration-path)
8. [Testing Strategy](#8-testing-strategy)

---

## 1. Problems with v0.2

### 1.1 Broken Limits Integration

`GrailBackendConfig.limits` is `dict[str, Any]` with keys like `max_memory_mb` — but grail 3.0.0's `script.run()` expects a `Limits` object (a frozen Pydantic model). The dict is passed directly as `limits=limits`, which either causes a validation error or is silently ignored. The grail `Limits` class provides:

- Human-readable strings (`"16mb"`, `"2s"`)
- Presets (`Limits.strict()`, `.default()`, `.permissive()`)
- Immutable merge semantics (`base.merge(override)`)
- Validation that rejects typos (`max_mmeory` → error)

None of these are used.

### 1.2 Registry Reads Stale JSON Instead of Grail Metadata

`GrailRegistry` reads `.grail/<tool>/inputs.json` for tool schemas. There are **two incompatible formats** in the codebase:

- **Hand-written (dict format):** `{"code": {"type": "str", "required": true}}`
- **Grail-generated (list format):** `{"inputs": [{"name": "code", "type": "str", "required": true}]}`

The registry only parses the dict format. Meanwhile, grail 3.0.0 exposes authoritative metadata via `GrailScript.inputs` (dict of `InputSpec`) and `GrailScript.externals` (dict of `ExternalSpec`) after `load()` — typed dataclasses with `name`, `type_annotation`, `required`, `default`, `lineno`, etc.

### 1.3 Dead Code

`_schema_from_grail_check()` in `GrailRegistry` always returns `None`. It was intended to run `grail check --json` as a subprocess and parse the output, but was never implemented.

### 1.4 Redundant Process Isolation

`_run_grail_script()` runs in a `ProcessPoolExecutor` subprocess with `asyncio.run()` inside it. Grail's Monty sandbox already provides memory, duration, and recursion isolation at the interpreter level. The subprocess adds:

- ~50-100ms startup latency per invocation
- A requirement that all parameters be picklable (forcing the 10-parameter top-level function pattern)
- Inability to use direct async externals (must create a new event loop per invocation)
- Complexity in passing context through process boundaries

### 1.5 No Event Integration

Grail 3.0.0 provides `ScriptEvent` with types: `run_start`, `run_complete`, `run_error`, `print`, `check_start`, `check_complete`. structured-agents has its own `Observer` system emitting events like `ToolCallEvent`, `ToolResultEvent`, etc. These two systems are completely disconnected — script-level telemetry (execution duration, print output, errors) never reaches the observer.

### 1.6 No Output Validation

Grail's `script.run(output_model=MyModel)` validates return values against a Pydantic model and raises `OutputError` on mismatch. All current scripts return raw dicts with no validation.

### 1.7 Coarse Error Handling

The backend only catches `LimitError`, `ExecutionError`, and generic `GrailError`. Grail provides fine-grained error types that are ignored:

| Error Type | Meaning | Currently Caught? |
|---|---|---|
| `ParseError` | .pym has Python syntax errors | No (caught as `GrailError`) |
| `CheckError` | @external/Input declarations are malformed | No (caught as `GrailError`) |
| `InputError` | Missing/extra runtime inputs | No (caught as `GrailError`) |
| `ExternalError` | Missing/extra runtime externals | No (caught as `GrailError`) |
| `ExecutionError` | Monty runtime error (TypeError, etc.) | Yes |
| `LimitError` | Resource limit exceeded | Yes |
| `OutputError` | output_model validation failed | No (feature not used) |

### 1.8 No Virtual Filesystem Usage

Grail provides `files={}` (virtual filesystem) and `environ={}` (sandboxed env vars) for data injection. These are never used. Instead, workspace scripts declare `@external` functions for every file read — adding boilerplate to every script.

---

## 2. Design Principles

### 2.1 Scripts as Pure Functions

.pym scripts are pure functions: data in, result out, no side effects.

```
DB Query → files dict → script.run() → Validated Result → DB Persist
```

- **Input:** Data is loaded eagerly from a database into grail's virtual filesystem (`files={}`) before execution.
- **Processing:** Scripts access data through Monty's sandboxed file access. No @external calls for data retrieval.
- **Output:** Scripts return structured results describing desired mutations. The host validates the result against a Pydantic model and persists changes to the database after execution.

This eliminates the need for most @external declarations. @external is reserved for cases where a script genuinely needs to call an external service during execution (rare for typical tool scripts).

### 2.2 Single Source of Truth

Tool schemas come from `grail.load()` introspection, not from hand-written JSON files. `GrailScript.inputs` and `GrailScript.externals` are the authoritative source of what a script expects.

### 2.3 Use Grail's Types, Not Raw Dicts

`Limits` objects, not dicts. `ScriptEvent` objects, not ignored. `OutputError` exceptions, not unchecked returns.

### 2.4 In-Process Execution

Trust Monty's sandboxing. Remove the ProcessPoolExecutor. Run `grail.load()` and `script.run()` directly in-process with full async support.

### 2.5 Minimal Change Surface Area

Despite being a "ground-up refactor" of the grail integration layer, the rest of the architecture (kernel, plugins, client, grammar, observers) remains unchanged. The refactor is scoped to:

- `backends/grail.py` → `executor.py` (ToolExecutor)
- `registries/grail.py` → `registry.py` (ToolRegistry)
- `bundles/` (config schema updates)
- New: `data_provider.py`, `result_handler.py`, `event_bridge.py`

---

## 3. Architecture Overview

### 3.1 Layer Stack

```
┌──────────────────────────────────────────────────────┐
│  AgentBundle                                          │
│  bundle.yaml: tools, prompts, limits, output models   │
├──────────────────────────────────────────────────────┤
│  ToolRegistry                                         │
│  grail.load() → GrailScript.inputs/.externals         │
│  → ToolSchema (JSON Schema from InputSpec)            │
├──────────────────────────────────────────────────────┤
│  ToolExecutor                                         │
│  In-process async script.run()                        │
│  Virtual FS populated by DataProvider                 │
│  Output validated by output_model                     │
│  Events bridged to Observer                           │
├──────────────────────────────────────────────────────┤
│  DataProvider (protocol)                              │
│  load_files(tool_name, inputs) → dict[str, str|bytes] │
│  Pluggable: DatabaseProvider, StaticProvider, etc.    │
├──────────────────────────────────────────────────────┤
│  ResultHandler (protocol)                             │
│  handle(tool_name, validated_result) → None           │
│  Pluggable: DatabaseHandler, LogHandler, etc.         │
├──────────────────────────────────────────────────────┤
│  Observer                                             │
│  Receives bridged ScriptEvents as structured events   │
└──────────────────────────────────────────────────────┘
```

### 3.2 Execution Flow

```
1. Kernel receives tool call from model
2. ToolSource routes to ToolExecutor
3. ToolExecutor:
   a. Calls DataProvider.load_files(tool_name, inputs) → files dict
   b. Loads script: grail.load(path, limits=..., files=files)
   c. Runs script: await script.run(
        inputs=inputs,
        externals=externals,  # only if factory configured
        output_model=output_model,
        on_event=event_bridge,
        print_callback=print_bridge,
      )
   d. Calls ResultHandler.handle(tool_name, result)
   e. Returns ToolResult
4. Kernel receives ToolResult, adds to history
```

### 3.3 What Changes, What Stays

| Component | v0.2 | v0.3 | Change Type |
|---|---|---|---|
| `GrailBackend` | ProcessPoolExecutor, raw dict limits, no events | `ToolExecutor`: in-process async, `Limits` objects, event bridge | **Rewrite** |
| `GrailRegistry` | JSON file parsing, two formats, dead code | `ToolRegistry`: `grail.load()` introspection | **Rewrite** |
| `bundle.yaml` schema | `limits` as nested dict, no output models | `limits` as preset name or structured config, `output_model` per tool | **Extend** |
| `externals_factory` | `(agent_id, context_dict) → dict` | Typed `ExternalsFactory` protocol, receives `ExecutionContext` | **Refine** |
| Kernel | Unchanged | Unchanged | None |
| Plugins | Unchanged | Unchanged | None |
| Client | Unchanged | Unchanged | None |
| Grammar | Unchanged | Unchanged | None |
| Observer | Unchanged (receives new event types) | Unchanged (receives new event types) | **Extend** |
| .pym scripts | @external for I/O, unvalidated returns | Virtual FS for reads, validated returns | **Rewrite** |

---

## 4. Component Design

### 4.1 ToolRegistry

**Replaces:** `GrailRegistry` (`src/structured_agents/registries/grail.py`)

**Purpose:** Discover .pym tools and derive JSON Schemas from grail metadata.

**Current problems:**
- Reads hand-written `inputs.json` files with inconsistent formats
- `_schema_from_grail_check()` is dead code
- Manual `_grail_type_to_json()` type mapping that can drift from grail's actual types

**New approach:**

```python
from grail import load, GrailScript

class ToolRegistry:
    """Discovers .pym tools and derives schemas from grail metadata."""

    def __init__(self, config: ToolRegistryConfig):
        self.agents_dir = config.agents_dir
        self._scripts: dict[str, GrailScript] = {}  # cache loaded scripts

    def scan(self) -> list[ToolSchema]:
        """Scan agents_dir for .pym files, load each, derive schemas."""
        schemas = []
        for pym_path in self.agents_dir.rglob("*.pym"):
            script = load(str(pym_path), grail_dir=None)  # no artifacts needed
            self._scripts[script.name] = script
            schemas.append(self._schema_from_script(script))
        return schemas

    def get_script(self, tool_name: str) -> GrailScript:
        """Return cached GrailScript for a tool name."""
        return self._scripts[tool_name]

    def _schema_from_script(self, script: GrailScript) -> ToolSchema:
        """Derive JSON Schema from GrailScript.inputs."""
        properties = {}
        required = []

        for name, spec in script.inputs.items():
            properties[name] = {
                "type": _grail_type_to_json_type(spec.type_annotation),
                "description": f"Input '{name}' ({spec.type_annotation})",
            }
            if spec.required:
                required.append(name)

        return ToolSchema(
            name=script.name,
            description=_extract_description(script),
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
        )
```

**Key changes:**
- `grail.load()` at scan time — single source of truth
- `GrailScript` objects are cached and reused for execution (no re-loading)
- Schema derived from `InputSpec.type_annotation` and `InputSpec.required`
- No JSON file reading, no hand-written artifacts
- Dead code (`_schema_from_grail_check`) eliminated
- The `_grail_type_to_json_type()` mapping becomes simpler since it works from the authoritative `type_annotation` string

**Type mapping from grail annotations to JSON Schema:**

| Grail `type_annotation` | JSON Schema `type` |
|---|---|
| `"str"` | `"string"` |
| `"int"` | `"integer"` |
| `"float"` | `"number"` |
| `"bool"` | `"boolean"` |
| `"list[...]"` / `"List[...]"` | `"array"` |
| `"dict[...]"` / `"Dict[...]"` | `"object"` |
| `"Any"` | `"string"` (fallback) |
| `"Optional[X]"` / `"X | None"` | type of X (not required) |

### 4.2 ToolExecutor

**Replaces:** `GrailBackend` (`src/structured_agents/backends/grail.py`)

**Purpose:** Execute .pym tools in-process with full grail integration.

**Current problems:**
- ProcessPoolExecutor with 10-parameter picklable function
- `asyncio.run()` inside subprocess (creates new event loop per invocation)
- Raw dict limits
- No event integration
- No output validation
- Coarse error handling

**New approach:**

```python
from grail import (
    GrailScript, Limits, ScriptEvent,
    GrailError, ParseError, CheckError, InputError,
    ExternalError, ExecutionError, LimitError, OutputError,
)

class ToolExecutor:
    """Executes .pym scripts in-process with full grail integration."""

    def __init__(self, config: ToolExecutorConfig):
        self.limits = config.limits          # Limits object (not dict)
        self.data_provider = config.data_provider
        self.result_handler = config.result_handler
        self.externals_factory = config.externals_factory
        self.observer = config.observer
        self.output_models = config.output_models  # dict[str, type[BaseModel]]

    async def execute(
        self,
        script: GrailScript,
        tool_name: str,
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Execute a tool script and return a ToolResult."""

        # 1. Load virtual filesystem from data provider
        files = await self.data_provider.load_files(tool_name, inputs, context)

        # 2. Build externals if factory configured
        externals = None
        if self.externals_factory:
            externals = self.externals_factory.build(tool_name, context)

        # 3. Build event bridge
        on_event = _make_event_bridge(self.observer, tool_name, context.agent_id)

        # 4. Get output model if configured
        output_model = self.output_models.get(tool_name)

        # 5. Execute with full grail integration
        try:
            result = await script.run(
                inputs=inputs,
                externals=externals,
                files=files,
                limits=self.limits,
                output_model=output_model,
                on_event=on_event,
                print_callback=_make_print_bridge(self.observer, tool_name),
            )

            # 6. Handle result (persist to DB, etc.)
            if self.result_handler:
                await self.result_handler.handle(tool_name, result, context)

            return ToolResult(
                tool_call_id=context.call_id,
                output=json.dumps(result) if not isinstance(result, str) else result,
                is_error=False,
            )

        except LimitError as e:
            return ToolResult(
                tool_call_id=context.call_id,
                output=f"Resource limit exceeded ({e.limit_type}): {e}",
                is_error=True,
            )
        except InputError as e:
            return ToolResult(
                tool_call_id=context.call_id,
                output=f"Input error ({e.input_name}): {e.message}",
                is_error=True,
            )
        except ExternalError as e:
            return ToolResult(
                tool_call_id=context.call_id,
                output=f"External function error ({e.function_name}): {e.message}",
                is_error=True,
            )
        except OutputError as e:
            return ToolResult(
                tool_call_id=context.call_id,
                output=f"Output validation failed: {e.message}",
                is_error=True,
            )
        except ExecutionError as e:
            return ToolResult(
                tool_call_id=context.call_id,
                output=f"Script error at line {e.lineno}: {e.message}",
                is_error=True,
            )
        except ParseError as e:
            return ToolResult(
                tool_call_id=context.call_id,
                output=f"Script syntax error at line {e.lineno}: {e.message}",
                is_error=True,
            )
        except CheckError as e:
            return ToolResult(
                tool_call_id=context.call_id,
                output=f"Script validation error: {e.message}",
                is_error=True,
            )
        except GrailError as e:
            return ToolResult(
                tool_call_id=context.call_id,
                output=f"Grail error: {e}",
                is_error=True,
            )
```

**Key changes:**
- **In-process async execution** — no subprocess, no `asyncio.run()`, no pickling
- **`Limits` objects** — proper grail `Limits` with presets and merge semantics
- **Output validation** — `output_model` per tool, `OutputError` caught
- **Event bridge** — `on_event` and `print_callback` connected to Observer
- **Fine-grained error handling** — each grail error type produces a distinct, informative `ToolResult`
- **DataProvider integration** — virtual FS populated before execution
- **ResultHandler integration** — validated results persisted after execution

### 4.3 DataProvider

**New component.** Provides a protocol for loading data into grail's virtual filesystem before script execution.

**Purpose:** Decouple data sourcing from script execution. The `DataProvider` knows how to query a database (or other source) and return a `files` dict that grail can inject into the sandbox.

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class DataProvider(Protocol):
    """Loads data into grail's virtual filesystem for script execution."""

    async def load_files(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, str | bytes]:
        """
        Return a dict of virtual file paths to their content.

        The tool_name and inputs allow the provider to load only
        the data relevant to this specific tool invocation.

        Returns:
            A dict mapping virtual file paths (e.g., "/data/config.json")
            to their string or bytes content. These become accessible
            inside the Monty sandbox via standard file access patterns.
        """
        ...
```

**Built-in implementations:**

```python
class NullDataProvider:
    """No-op provider. Returns empty files dict."""

    async def load_files(self, tool_name, inputs, context):
        return {}


class StaticDataProvider:
    """Provides a fixed set of files for all tool invocations."""

    def __init__(self, files: dict[str, str | bytes]):
        self.files = files

    async def load_files(self, tool_name, inputs, context):
        return self.files


class DatabaseDataProvider:
    """Loads file content from a database.

    The database query is determined by the tool_name and inputs.
    This is the primary provider for production use.
    """

    def __init__(self, db_connection, file_mapping: dict[str, str] | None = None):
        self.db = db_connection
        self.file_mapping = file_mapping or {}

    async def load_files(self, tool_name, inputs, context):
        files = {}
        # Query database for files relevant to this tool/context
        records = await self.db.query_files(
            agent_id=context.agent_id,
            tool_name=tool_name,
        )
        for record in records:
            virtual_path = f"/data/{record.name}"
            files[virtual_path] = record.content
        return files
```

**Design rationale:**

The DataProvider is a protocol (not a base class) to allow any object with a `load_files` method to serve as a provider. The built-in implementations cover common cases:

- `NullDataProvider` for tools that don't need data injection
- `StaticDataProvider` for testing and simple cases
- `DatabaseDataProvider` for production use with a real database

The `load_files` method receives the full `ExecutionContext` so the provider can make context-aware decisions about what data to load (e.g., loading only files belonging to a specific agent's workspace).

### 4.4 ResultHandler

**New component.** Provides a protocol for persisting validated script results.

**Purpose:** After a script returns a validated result (checked against `output_model`), the ResultHandler persists the desired mutations to the database.

```python
@runtime_checkable
class ResultHandler(Protocol):
    """Handles validated script results after execution."""

    async def handle(
        self,
        tool_name: str,
        result: Any,
        context: ExecutionContext,
    ) -> None:
        """
        Persist the validated result.

        The result has already been validated against the tool's
        output_model (if configured). The handler interprets the
        result and performs any necessary side effects (database
        writes, file creation, notifications, etc.).
        """
        ...
```

**Built-in implementations:**

```python
class NullResultHandler:
    """No-op handler. Result is returned to the kernel but not persisted."""

    async def handle(self, tool_name, result, context):
        pass


class DatabaseResultHandler:
    """Persists results to a database.

    Interprets the result dict and performs appropriate database
    operations (insert, update, delete) based on the result structure.
    """

    def __init__(self, db_connection):
        self.db = db_connection

    async def handle(self, tool_name, result, context):
        if isinstance(result, dict):
            # Convention: result may contain "writes" key with file mutations
            writes = result.get("writes", [])
            for write in writes:
                await self.db.write_file(
                    agent_id=context.agent_id,
                    path=write["path"],
                    content=write["content"],
                )
```

**Design rationale:**

The return-based mutation model means scripts never perform side effects directly. Instead, they return structured descriptions of desired changes. This makes scripts:

- **Testable** — assert on the return value, no mocking needed
- **Auditable** — every mutation is visible in the result before it happens
- **Recoverable** — if persistence fails, the script didn't partially mutate state
- **Replayable** — same inputs produce same outputs (pure function)

The ResultHandler interprets the result and performs the actual persistence. Different handlers can implement different persistence strategies (database, filesystem, event stream, etc.).

### 4.5 Event Bridge

**New component.** Bridges grail's `ScriptEvent` into structured-agents' Observer system.

```python
from grail import ScriptEvent

def make_event_bridge(
    observer: Observer,
    tool_name: str,
    agent_id: str,
) -> Callable[[ScriptEvent], None]:
    """Create a callback that bridges ScriptEvent to Observer events."""

    def on_event(event: ScriptEvent):
        if event.type == "run_start":
            observer.emit("tool.script.start", {
                "agent_id": agent_id,
                "tool_name": tool_name,
                "script_name": event.script_name,
                "input_count": event.input_count,
                "external_count": event.external_count,
            })
        elif event.type == "run_complete":
            observer.emit("tool.script.complete", {
                "agent_id": agent_id,
                "tool_name": tool_name,
                "script_name": event.script_name,
                "duration_ms": event.duration_ms,
                "result_summary": event.result_summary,
            })
        elif event.type == "run_error":
            observer.emit("tool.script.error", {
                "agent_id": agent_id,
                "tool_name": tool_name,
                "script_name": event.script_name,
                "duration_ms": event.duration_ms,
                "error": event.error,
            })
        elif event.type == "print":
            observer.emit("tool.script.print", {
                "agent_id": agent_id,
                "tool_name": tool_name,
                "script_name": event.script_name,
                "text": event.text,
            })

    return on_event


def make_print_bridge(
    observer: Observer,
    tool_name: str,
) -> Callable[[str, str], None]:
    """Create a print_callback that forwards to Observer."""

    def on_print(stream: str, text: str):
        observer.emit("tool.script.stdout", {
            "tool_name": tool_name,
            "stream": stream,
            "text": text,
        })

    return on_print
```

**New observer event types introduced:**

| Event | When | Fields |
|---|---|---|
| `tool.script.start` | Script execution begins | `agent_id`, `tool_name`, `input_count`, `external_count` |
| `tool.script.complete` | Script execution succeeds | `agent_id`, `tool_name`, `duration_ms`, `result_summary` |
| `tool.script.error` | Script execution fails | `agent_id`, `tool_name`, `duration_ms`, `error` |
| `tool.script.print` | Script calls `print()` | `agent_id`, `tool_name`, `text` |
| `tool.script.stdout` | Raw stdout capture | `tool_name`, `stream`, `text` |

These are additive — existing observer events (`ToolCallEvent`, `ToolResultEvent`, etc.) are unchanged.

### 4.6 Limits Integration

**Current state:** `dict[str, Any]` with non-standard keys.

**New approach:** Use grail's `Limits` class throughout.

```python
from grail import Limits

class ToolExecutorConfig:
    """Configuration for the ToolExecutor."""

    # Accept Limits object directly
    limits: Limits = Limits.default()

    # Or configure via bundle.yaml with preset names:
    # limits: "strict"    → Limits.strict()
    # limits: "default"   → Limits.default()
    # limits: "permissive" → Limits.permissive()
    # limits:              → custom Limits(...)
    #   max_memory: "32mb"
    #   max_duration: "5s"
    #   max_recursion: 300
```

**Bundle.yaml example:**

```yaml
tools:
  - name: analyze_data
    path: agents/analyze_data.pym
    limits: strict                    # preset name

  - name: generate_report
    path: agents/generate_report.pym
    limits:                           # custom limits
      max_memory: "32mb"
      max_duration: "10s"
      max_recursion: 300

  - name: simple_calc
    path: agents/simple_calc.pym
    # no limits → uses executor's default (Limits.default())
```

**Per-tool limit override:** Limits configured at the tool level in `bundle.yaml` are merged with the executor's base limits at execution time using `Limits.merge()`:

```python
# In ToolExecutor.execute():
effective_limits = self.limits  # base from config
if tool_limits := self.tool_limits.get(tool_name):
    effective_limits = self.limits.merge(tool_limits)
```

### 4.7 Error Handling

**Current state:** Only catches `LimitError`, `ExecutionError`, and generic `GrailError`.

**New approach:** Catch all seven grail error types with specific, actionable error messages in ToolResult.

```
GrailError
├── ParseError      → "Script syntax error at line {lineno}: {message}"
├── CheckError      → "Script validation error: {message}"
├── InputError      → "Input error ({input_name}): {message}"
├── ExternalError   → "External function error ({function_name}): {message}"
├── ExecutionError  → "Script error at line {lineno}: {message}"
├── LimitError      → "Resource limit exceeded ({limit_type}): {message}"
└── OutputError     → "Output validation failed: {message}"
```

Each error type produces a `ToolResult(is_error=True)` with a human-readable message that helps the model (or developer) understand what went wrong and how to fix it.

**Error-to-observer mapping:**

All script errors are also emitted as observer events via the event bridge (`tool.script.error`), providing unified error telemetry regardless of error type.

### 4.8 Externals (Typed Factory)

**Current state:** `externals_factory` is `Callable[[str, dict], dict[str, Callable]]` — loosely typed with a raw context dict.

**New approach:** Typed `ExternalsFactory` protocol with a structured `ExecutionContext`.

```python
@dataclass(frozen=True)
class ExecutionContext:
    """Structured context for tool execution."""
    agent_id: str
    call_id: str
    workspace_path: Path | None = None
    metadata: dict[str, Any] | None = None


class ExternalsFactory(Protocol):
    """Builds externals dict for a tool invocation."""

    def build(
        self,
        tool_name: str,
        context: ExecutionContext,
    ) -> dict[str, Callable]:
        """
        Return a dict mapping external function names to implementations.

        Only needed for tools that declare @external functions in their
        .pym scripts. Most tools in v0.3.0 use the virtual filesystem
        instead of externals for data access.
        """
        ...
```

**Design note:** With the virtual FS handling data access, `@external` usage becomes rare. The factory is only needed for tools that call out to external services (APIs, specialized computations, etc.) during execution. Most tools will have `externals=None`.

---

## 5. Script Authoring Changes

### 5.1 Before (v0.2): Data via @external

```python
# agents/workspace/list_entries.pym (v0.2)
from grail import external, Input
from typing import Any

workspace_path: str = Input("workspace_path")

@external
async def list_dir(path: str) -> list[dict[str, Any]]:
    """List files in a directory."""
    ...

@external
async def read_file(path: str) -> str:
    """Read file contents."""
    ...

entries = await list_dir(workspace_path)
results = []
for entry in entries:
    if entry["name"].endswith(".txt"):
        content = await read_file(entry["path"])
        results.append({"name": entry["name"], "content": content})

result = {"entries": results}
result
```

### 5.2 After (v0.3.0): Data via Virtual FS, Mutations via Return

```python
# agents/workspace/list_entries.pym (v0.3.0)
from grail import Input
import os

workspace_path: str = Input("workspace_path")

# Data is already available via virtual filesystem
# DataProvider loaded relevant files before execution
entries = []
data_dir = f"/data/{workspace_path}"

# Access virtual files through Monty's sandboxed file access
for name in os.listdir(data_dir):
    if name.endswith(".txt"):
        with open(f"{data_dir}/{name}") as f:
            content = f.read()
        entries.append({"name": name, "content": content})

result = {"entries": entries}
result
```

**Key differences:**
- No `@external` declarations
- No `await` calls
- Data accessed through standard Python file operations (sandboxed by Monty)
- Script is simpler, more readable, easier to test
- DataProvider eagerly loaded workspace files into `/data/` before execution

### 5.3 Scripts That Need Mutations

```python
# agents/workspace/add_entry.pym (v0.3.0)
from grail import Input

title: str = Input("title")
content: str = Input("content")
workspace_path: str = Input("workspace_path")

# Read existing entries to check for duplicates
import os
data_dir = f"/data/{workspace_path}"
existing = os.listdir(data_dir) if os.path.exists(data_dir) else []

filename = f"{title.lower().replace(' ', '_')}.txt"
if filename in existing:
    result = {"error": f"Entry '{title}' already exists"}
else:
    # Return desired mutation — host will persist
    result = {
        "writes": [
            {
                "path": f"{workspace_path}/{filename}",
                "content": content,
            }
        ],
        "message": f"Created entry '{title}'",
    }

result
```

### 5.4 Output Models for Validation

```python
# In the host/bundle configuration:
from pydantic import BaseModel

class AddEntryResult(BaseModel):
    writes: list[dict[str, str]] = []
    message: str
    error: str | None = None

# Configured in bundle.yaml:
# tools:
#   - name: add_entry
#     path: agents/workspace/add_entry.pym
#     output_model: AddEntryResult
```

The script's return value is validated against `AddEntryResult`. If the script returns `{"writes": 123}` instead of a list, grail raises `OutputError` and the ToolExecutor returns `ToolResult(is_error=True)` with a clear validation error message.

---

## 6. Bundle Configuration Changes

### 6.1 Before (v0.2)

```yaml
# bundle.yaml (v0.2)
name: workspace_agent
system_prompt: "You are a workspace assistant."
tools:
  - name: list_entries
    path: agents/workspace/list_entries.pym
registry:
  type: grail
  agents_dir: agents/workspace
  use_grail_check: false
backend:
  type: grail
  grail_dir: .grail
  max_workers: 2
  timeout: 30
  limits:
    max_memory_mb: 16
    max_duration_s: 2
    max_recursion: 200
```

### 6.2 After (v0.3.0)

```yaml
# bundle.yaml (v0.3.0)
name: workspace_agent
system_prompt: "You are a workspace assistant."

# Global defaults
limits: default                    # preset name, or inline config
data_provider: database            # provider type (resolved by bundle loader)

tools:
  - name: list_entries
    path: agents/workspace/list_entries.pym
    # inherits global limits

  - name: add_entry
    path: agents/workspace/add_entry.pym
    output_model: AddEntryResult   # Pydantic model for output validation
    limits:                        # per-tool override
      max_duration: "5s"

  - name: analyze_data
    path: agents/workspace/analyze_data.pym
    limits: strict                 # preset override
    output_model: AnalysisResult

registry:
  agents_dir: agents/workspace    # type is always "grail" now
```

**Changes:**
- `limits` at top level and per-tool (preset names or inline config)
- `output_model` per tool (references a Pydantic model class)
- `data_provider` configuration
- `registry.type` and `backend.type` removed (always grail)
- `backend.max_workers` removed (no subprocess pool)
- `backend.timeout` replaced by `limits.max_duration`
- `registry.use_grail_check` removed (load-time introspection always)

---

## 7. Migration Path

### 7.1 Script Migration

Existing .pym scripts that use `@external` for data access need to be rewritten to use the virtual filesystem pattern. Scripts that use `@external` for genuinely external services (API calls, specialized computation) can keep their externals.

**Migration checklist per script:**
1. Remove `@external` declarations for file read operations
2. Replace `await external_function()` calls with standard file access
3. For mutations: return structured result dicts instead of calling write externals
4. Add output model if desired

### 7.2 Backend/Registry Migration

The `GrailBackend` and `GrailRegistry` classes are replaced entirely. Code that references them directly needs to update imports:

```python
# v0.2
from structured_agents.backends.grail import GrailBackend, GrailBackendConfig
from structured_agents.registries.grail import GrailRegistry, GrailRegistryConfig

# v0.3.0
from structured_agents.executor import ToolExecutor, ToolExecutorConfig
from structured_agents.registry import ToolRegistry, ToolRegistryConfig
```

### 7.3 Bundle Migration

Bundle.yaml files need to update their `limits` format and remove backend/registry type declarations. See section 6 for before/after examples.

### 7.4 Externals Factory Migration

```python
# v0.2
def my_factory(agent_id: str, context: dict) -> dict[str, Callable]:
    workspace = context.get("workspace_path", ".")
    return {"read_file": make_reader(workspace), ...}

# v0.3.0
class MyExternalsFactory:
    def build(self, tool_name: str, context: ExecutionContext) -> dict[str, Callable]:
        # Only for tools that genuinely need external service calls
        return {"call_api": make_api_caller(context.metadata)}
```

---

## 8. Testing Strategy

### 8.1 Unit Tests

| Component | Test Focus |
|---|---|
| `ToolRegistry` | Schema derivation from `GrailScript.inputs`, type mapping, scan behavior |
| `ToolExecutor` | Execution flow, error handling (all 7 error types), limits application, event emission |
| `DataProvider` | `NullDataProvider`, `StaticDataProvider`, `DatabaseDataProvider` (with mock DB) |
| `ResultHandler` | `NullResultHandler`, `DatabaseResultHandler` (with mock DB) |
| Event bridge | ScriptEvent → Observer event mapping |

### 8.2 Integration Tests

| Scenario | What It Tests |
|---|---|
| Load + execute a .pym tool | Full pipeline: registry scan → executor run → result |
| Virtual FS data injection | DataProvider populates files, script reads them |
| Return-based mutations | Script returns writes, ResultHandler persists them |
| Output validation | `output_model` catches invalid returns |
| Limits enforcement | `Limits.strict()` prevents runaway scripts |
| Error propagation | Each grail error type produces correct ToolResult |
| Event telemetry | Observer receives all script lifecycle events |

### 8.3 Migration Tests

Ensure all existing .pym scripts in `agents/` continue to work after migration (rewritten to use virtual FS pattern).

---

## Appendix: Grail 3.0.0 API Surface Used

| Feature | Where Used in v0.3.0 |
|---|---|
| `grail.load()` | ToolRegistry (scan), ToolExecutor (if script not cached) |
| `GrailScript.inputs` | ToolRegistry (schema derivation) |
| `GrailScript.externals` | ToolRegistry (schema enrichment) |
| `GrailScript.name` | ToolRegistry, ToolExecutor |
| `script.run()` | ToolExecutor |
| `script.check()` | ToolRegistry (optional validation at scan) |
| `Limits` class | ToolExecutorConfig, bundle.yaml, per-tool overrides |
| `Limits.strict/default/permissive()` | Bundle preset names |
| `Limits.merge()` | Per-tool override application |
| `output_model` parameter | ToolExecutor (per-tool Pydantic models) |
| `on_event` callback | Event bridge → Observer |
| `print_callback` | Print bridge → Observer |
| `files` parameter | DataProvider → virtual FS |
| `environ` parameter | Context injection |
| `strict_validation` | ToolExecutor configuration |
| `ScriptEvent` | Event bridge |
| `InputSpec` / `ExternalSpec` | ToolRegistry (schema derivation) |
| All 7 error types | ToolExecutor (fine-grained error handling) |
| `CheckResult` | ToolRegistry (optional validation reporting) |
| `grail_dir=None` | ToolRegistry (no artifacts during scan) |
