# DEV GUIDE STEP 2: Configuration System

## Goal
Define and load all Remora configuration with CLI overrides, including the new FunctionGemma runner settings and subagent path resolution.

## Why This Matters
The configuration system is the single source of truth for every downstream component: which `agents_dir` to use, which subagent YAML to load per operation, how many concurrent runners to allow, and what the per-runner turn limit is. Getting this right early prevents configuration drift across later steps.

## Implementation Checklist
- Implement `RemoraConfig` Pydantic model with all sections: `root_dirs`, `queries`, `agents_dir`, `operations`, `runner`, `cairn`.
- Implement `RunnerConfig` sub-model: `max_turns`, `max_concurrent_runners`, `timeout`.
- Implement `OperationConfig` sub-model: `enabled`, `auto_accept`, `subagent` (path to YAML relative to `agents_dir`), plus operation-specific extras.
- YAML loader: reads `remora.yaml` from project root or path given by `--config` flag.
- CLI override merging: CLI flags take precedence over YAML, which takes precedence over defaults.
- Map `ValidationError` → exit code `3`, error code `CONFIG_003`.
- Map missing `agents_dir` → exit code `3`, error code `CONFIG_004`.

## Suggested File Targets
- `remora/config.py`
- `remora/errors.py` (error code constants)
- `remora/cli.py` (update `config` command to load and display)

## Key Schema

```python
class RunnerConfig(BaseModel):
    max_turns: int = 20
    max_concurrent_runners: int = 4
    timeout: int = 300  # seconds

class OperationConfig(BaseModel):
    enabled: bool = True
    auto_accept: bool = False
    subagent: str  # e.g. "lint/lint_subagent.yaml", relative to agents_dir
    # Operation-specific extras (e.g., docstring style) via extra="allow"

class CairnConfig(BaseModel):
    timeout: int = 120

class RemoraConfig(BaseModel):
    root_dirs: list[Path]
    queries: list[str] = ["function_def", "class_def"]
    agents_dir: Path = Path("agents")
    operations: dict[str, OperationConfig]
    runner: RunnerConfig = RunnerConfig()
    cairn: CairnConfig = CairnConfig()
```

## Default remora.yaml Example

Create a `remora.yaml.example` at project root showing all fields with defaults and comments. This also serves as documentation for new users.

## Implementation Notes
- Use `model_config = ConfigDict(extra="allow")` on `OperationConfig` so domains can add fields (e.g., docstring `style`) without schema changes.
- Resolve `agents_dir` relative to the config file location, not the working directory.
- The `subagent` field in `OperationConfig` is a path relative to `agents_dir`. During validation, warn (don't error) if the file is missing — GGUF models may not be present yet during development.
- Keep `remora/errors.py` as a simple module of string constants (`CONFIG_001`, `CONFIG_002`, etc.) — no need for a class hierarchy at this stage.

## Testing Overview
- **Unit test:** Default config loads without a YAML file and has correct defaults.
- **Unit test:** YAML values override defaults; CLI flags override YAML.
- **Unit test:** Invalid YAML (wrong type for `max_turns`) returns exit code `3` and `CONFIG_003`.
- **Unit test:** `remora config -f yaml` outputs valid YAML matching the merged config.
- **Unit test:** Missing `agents_dir` path returns `CONFIG_004`.
