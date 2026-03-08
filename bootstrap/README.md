# Remora Bootstrap (Phase 2)

This directory is the Phase 2 bootstrap track for Remora.

Goal:
- Build a core set of tools, agents, and templates from scratch.
- Treat `remora` as a library dependency.
- Avoid coupling to repo-level `agents/` bundles and Grail `.pym` scripts.

## Scope Boundaries

The bootstrap runtime should:
- Import Remora Python APIs directly.
- Define its own tool, agent, and template contracts.
- Provide a clean registry and runtime bootstrap path.

The bootstrap runtime should not:
- Reuse existing `agents/*/bundle.yaml` behavior.
- Depend on Grail scripts from `.grail/` or `agents/*/tools`.

## Layout

- `src/remora_bootstrap/contracts.py`: Core data contracts for tools, agents, templates.
- `src/remora_bootstrap/registry.py`: In-memory registry for bootstrap primitives.
- `src/remora_bootstrap/runtime.py`: Runtime that loads Remora config and serves bootstrap primitives.
- `src/remora_bootstrap/tools/`: Bootstrap-native tool definitions.
- `src/remora_bootstrap/agents/`: Bootstrap-native agent definitions.
- `src/remora_bootstrap/templates/`: Bootstrap-native prompt templates.

## Local Development

From this directory, install with local editable sources so `remora` is consumed like a normal library dependency.

Example:
- `uv sync`
- `uv run python -m remora_bootstrap`
