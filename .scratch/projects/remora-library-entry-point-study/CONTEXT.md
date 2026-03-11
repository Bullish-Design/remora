# CONTEXT

## Current State
This project was created to give a structured map of Remora's key entry points for codebase study. The overview has been written and saved in `ENTRY_POINTS_OVERVIEW.md`.

## What Was Analyzed
- Console script entry points in `pyproject.toml`
- Primary runtime bootstraps:
  - `src/remora/__main__.py`
  - `src/remora/cli/main.py`
  - `src/remora/lsp/__main__.py`
  - `src/remora/service/api.py` + `src/remora/adapters/starlette.py`
- Core runtime internals:
  - discovery, reconciliation, event store/projection, subscriptions, runner, execution pipeline, bootstrap flow, extensions

## Observed Detail Worth Revisiting
`pyproject.toml` includes `remora-index = "remora.indexer.cli:main"`, but no `src/remora/indexer/` package is present in this tree. This may be stale or externally provided.

## Next Step If Extended
If the user wants a deeper phase-2 guide, add a second document mapping specific tests to each entry point module and include command-driven walk-through exercises.
