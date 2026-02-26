# Grail Analysis

## 1. What Grail Is

Grail is a Python library for sandboxed execution of `.pym` scripts via Monty, a Rust-based secure Python interpreter. Scripts cannot access the real filesystem, network, or arbitrary modules. The host application controls all I/O through explicitly declared interfaces (`@external` functions and `Input()` values).

Pipeline: `.pym` file -> Parse -> Check -> Generate stubs -> Generate code -> Execute in Monty sandbox.

## 2. Core API

- **`grail.load(path, limits?, files?, environ?, grail_dir?, dataclass_registry?) -> GrailScript`** -- Parses, validates, and prepares a `.pym` script. Raises `CheckError` on validation failure.
- **`script.run(inputs?, externals?, output_model?, files?, environ?, limits?, print_callback?, on_event?, strict_validation?) -> Any`** -- Async execution. Injects host-provided inputs/externals, returns the script's last expression.
- **`script.run_sync(...)`** -- Sync wrapper around `run()` via `asyncio.run()`. Cannot be used inside an existing event loop.
- **`script.check() -> CheckResult`** -- Re-runs static validation on the cached parse result. Returns `valid`, `errors`, `warnings`, `info`.
- **`grail.run(code, inputs?, limits?, environ?, print_callback?) -> Any`** -- Inline execution without `.pym` pipeline (no `@external`/`Input()` parsing, no source mapping).

## 3. Key Concepts

- **`@external`** -- Decorator declaring a function signature the host must implement. Body must be `...`. All params and return type must be annotated. Supports sync and async.
- **`Input(name, default?)`** -- Declares a named value injected by the host at runtime. Must have a type annotation. Variable name must match the string argument. No default = required.
- **Virtual filesystem** -- `files` dict (`str | bytes` values) provided at `load()` or `run()`. Scripts read these instead of the real FS. Run-time values fully replace load-time values (no merge).
- **Virtual environment** -- `environ` dict accessible via `os.getenv()` inside the sandbox. Same replace-not-merge semantics as files.
- **`Limits`** -- Frozen Pydantic model: `max_memory`, `max_duration`, `max_recursion`, `max_allocations`, `gc_interval`. Presets: `strict()` (8MB/500ms), `default()` (16MB/2s), `permissive()` (64MB/5s). Supports human-readable strings ("16mb", "2s"). Run-time limits merge with load-time limits (non-None fields override).
- **`ScriptEvent`** -- Lifecycle events: `run_start`, `run_complete`, `run_error`, `print`, `check_start`, `check_complete`. Subscribe via `on_event` callback.

## 4. Error Hierarchy

```
GrailError
├── ParseError          -- Syntax errors in .pym (lineno, col_offset)
├── CheckError          -- Malformed declarations, validation codes E001-E012/E100
├── InputError          -- Missing/extra inputs at runtime (input_name)
├── ExternalError       -- Missing/extra externals at runtime (function_name)
├── ExecutionError      -- Monty runtime errors (lineno, source_context, suggestion)
├── LimitError          -- Resource limit exceeded (limit_type: memory/duration/recursion/allocations)
└── OutputError         -- output_model Pydantic validation failed (validation_errors)
```

**Critical:** `LimitError` is NOT a subclass of `ExecutionError`. Catching `ExecutionError` will not catch `LimitError`. They must be caught separately or via `GrailError`.

## 5. What .pym Scripts Can and Cannot Do

**Can:**
- Variables, arithmetic, string ops, f-strings
- `def` functions (non-external), `async`/`await`, `if`/`elif`/`else`, `for`/`while` loops
- `try`/`except`/`finally`, list/dict comprehensions, unpacking, slicing, ternary
- `print()` (captured via callback), `os.getenv()` (virtual only), `isinstance()`
- Read virtual files through Monty's sandboxed file access

**Cannot (errors block loading):**
- `class` definitions (E001)
- `yield`/generators (E002)
- `with` statements (E003)
- `match` statements (E004)
- Imports other than `grail`, `typing`, `__future__` (E005)
- `global`/`nonlocal` (E009/E010), `del` (E011), `lambda` (E012)
- Access real filesystem, network, or arbitrary modules

## 6. How the Host Provides Data

| Mechanism | Provided Via | Timing |
|-----------|-------------|--------|
| **Inputs** | `inputs` dict on `run()` | Required inputs must be present or `InputError` |
| **Externals** | `externals` dict on `run()` | All declared externals must have implementations or `ExternalError` |
| **Files** | `files` dict on `load()` or `run()` | Run-time fully replaces load-time |
| **Environ** | `environ` dict on `load()` or `run()` | Run-time fully replaces load-time |
| **Dataclasses** | `dataclass_registry` on `load()` | Enables `isinstance()` checks in sandbox |

`strict_validation=False` downgrades extra inputs/externals from errors to warnings. Missing items always error.

## 7. Output Validation with Pydantic Models

Pass `output_model=SomeBaseModel` to `run()`. The script's return value is validated against the model. On success, `run()` returns a validated model instance. On failure, raises `OutputError` with the underlying Pydantic `ValidationError` accessible via `e.validation_errors`.

## 8. The .grail/ Artifacts Directory

Default location: `.grail/<script_name>/`. Contains:

| File | Purpose |
|------|---------|
| `stubs.pyi` | Type stubs for Monty's type checker |
| `monty_code.py` | Clean executable code (declarations stripped) |
| `check.json` | Validation results (errors, warnings, info) |
| `externals.json` | External function specs |
| `inputs.json` | Input specs |
| `run.log` | Execution log (status, duration, stdout, stderr) |

Disable with `grail_dir=None`. Clean via `ArtifactsManager.clean()` or `grail clean` CLI. Should be added to `.gitignore`.

## 9. Key Integration Points for Remora's Refactor

1. **Script loading** -- `grail.load()` is the single entry point. Wraps parse + check + codegen. Remora should call this once per script and reuse the `GrailScript` object.
2. **External function wiring** -- Remora's service layer functions (DB queries, API calls, etc.) map directly to `@external` declarations. The `externals` dict at `run()` is the bridge.
3. **Input injection** -- User-provided or system-derived values flow through the `inputs` dict. Type annotations on `Input()` declarations serve as a contract.
4. **Error handling** -- Remora should handle the full error hierarchy. Distinguish between script author errors (`ParseError`, `CheckError`), runtime data errors (`InputError`, `ExternalError`), sandbox execution failures (`ExecutionError`, `LimitError`), and output contract violations (`OutputError`).
5. **Resource limits** -- Set sensible defaults at `load()` time, allow per-execution overrides for different script contexts.
6. **Output contracts** -- Use `output_model` with Pydantic models to enforce return type contracts between scripts and the consuming code.
7. **Event system** -- `on_event` callback enables logging, metrics, and observability without modifying scripts.
8. **Print capture** -- `print_callback` enables capturing script debug output for logging or user-facing display.
9. **Script introspection** -- `script.externals`, `script.inputs`, `script.name`, `script.monty_code` allow programmatic inspection of what a script expects, enabling dynamic UI generation or validation before execution.
10. **Strict vs. non-strict mode** -- `strict_validation=False` allows forward-compatible execution where the host may provide extra inputs/externals not yet consumed by the script.
