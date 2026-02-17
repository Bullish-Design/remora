# DEV GUIDE STEP 1: Project Skeleton + Dependencies

## Goal
Establish the package structure and a working CLI entrypoint for Remora.

## Why This Matters
Everything else depends on a stable import path and CLI surface (`remora analyze`, `watch`, `config`, `list-agents`).

## Implementation Checklist
- Create `remora/` package with `__init__.py` and core modules.
- Add `remora/cli.py` (Typer app) that wires the command group.
- Ensure `python -m remora` dispatches to the CLI app.
- Expose CLI commands with placeholders if implementations are not ready.

## Suggested File Targets
- `remora/__init__.py`
- `remora/cli.py`
- `remora/__main__.py`
- `pyproject.toml` or `setup.cfg` for console entrypoints

## Implementation Notes
- Follow the CLI layout described in `ARCHITECTURE.md` and `SPEC.md`.
- Keep each CLI command in a separate module if the file grows.
- Use Typer for argument parsing and Rich for output formatting.

## Testing Overview
- **Manual check:** Run `python -m remora --help` and verify commands listed.
- **CLI install check:** After install, run `remora --help` and verify same output.
- **Smoke test:** Each command should exit cleanly (status 0) even if unimplemented.
