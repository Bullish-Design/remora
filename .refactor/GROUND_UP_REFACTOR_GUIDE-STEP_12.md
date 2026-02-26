# Implementation Guide: Step 12 - CLI, Services, and Entry Points

## Target
Provide clear CLI entry points for the new architecture: `remora` (core executor), `remora-index` (indexer daemon), and `remora-dashboard` (web UI), ensuring each reads `remora.yaml` and wires the shared EventBus/store.

## Overview
- `remora` CLI loads `RemoraConfig`, runs discovery, builds the graph, and executes via `GraphExecutor` with the unified EventBus for logging.
- `remora-index` CLI (implemented in `indexer/cli.py`) starts the indexer daemon watching configured paths, optionally runs a cold start scan, and exposes status commands.
- `remora-dashboard` CLI (in `dashboard/cli.py`) starts the Starlette app with SSE, event subscriptions, and config-driven host/port settings.

## Steps
1. Update `pyproject.toml` entry points to publish `remora`, `remora-index`, and `remora-dashboard` commands pointing to `remora.cli:main`, `remora.indexer.cli:run`, and `remora.dashboard.cli:run`.
2. Implement `src/remora/cli.py` that loads config, initializes EventBus, discovery, graph, and executor, and provides subcommands for running once (`--run-once`) or continuous (`--watch`).
3. Ensure each CLI uses `RemoraConfig`, prints helpful startup logging (paths, concurrency, base URLs), and handles shutdown (`Ctrl+C`) gracefully while cleaning up announed services.
4. Document CLI usage in README/docs, showing how to run the executor, indexer, and dashboard separately.
