# DEV GUIDE STEP 1: Project Skeleton + Dependencies

## Goal
Establish the package structure, a working CLI entrypoint, and the full dependency manifest including llama-cpp-python for local model inference.

## Why This Matters
Everything else in the project depends on a stable import path, a working CLI surface, and confirmed availability of llama-cpp-python. If the model inference dependency is broken at the start, the runner layer cannot be built.

## Implementation Checklist
- Create `remora/` package with `__init__.py` and placeholder modules: `cli`, `config`, `discovery`, `orchestrator`, `runner`, `results`.
- Add `remora/cli.py` (Typer app) with four commands: `analyze`, `watch`, `config`, `list-agents`.
- Ensure `python -m remora` dispatches to the CLI via `remora/__main__.py`.
- Create `pyproject.toml` with all required dependencies.
- Add `agents/` directory with placeholder subdirectories: `lint/`, `test/`, `docstring/`, `sample_data/`.
- Add `training/` directory with placeholder subdirectories per domain.

## Suggested File Targets
- `remora/__init__.py`
- `remora/__main__.py`
- `remora/cli.py`
- `pyproject.toml`
- `agents/.gitkeep` (or scaffold subdirectory structure)
- `training/.gitkeep`

## Dependencies to Add (pyproject.toml)
```toml
[project]
dependencies = [
    "typer[all]>=0.12",
    "rich>=13",
    "pydantic>=2",
    "pyyaml>=6",
    "jinja2>=3",
    "watchfiles>=0.21",
    "llama-cpp-python>=0.2",
    # pydantree and cairn added as local or VCS dependencies
]
```

## Implementation Notes
- Keep each CLI command as a stub that prints "Not yet implemented" and exits 0.
- Use Typer for argument parsing and Rich for output formatting throughout.
- The `agents/` directory is where all subagent definitions, tool scripts, and GGUF model files will live. Scaffold it now so later steps have a home.
- `llama-cpp-python` may require CMake and a C++ compiler. Document build requirements in a `CONTRIBUTING.md` note or `README.md`.

## Testing Overview
- **Manual check:** `python -m remora --help` lists `analyze`, `watch`, `config`, `list-agents`.
- **Install check:** After `pip install -e .`, `remora --help` shows the same output.
- **Dependency check:** `python -c "from llama_cpp import Llama; print('ok')"` exits cleanly.
- **Smoke test:** Each command stub exits with code 0.
