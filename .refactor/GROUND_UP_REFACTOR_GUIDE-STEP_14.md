# Implementation Guide: Step 14 - Cleanup & Documentation

## Target
Replace all legacy modules (hub/, workspace kv, agent_state, etc.) with the new packages, update documentation, and ensure the repo reflects the v0.4.0 layout.

## Overview
- Remove old packages (`hub/`, `workspace.py`’s KV classes, context/ old modules) that were replaced in earlier steps.
- Update README/docs to describe the new architecture and CLI commands, referencing `V040_GROUND_UP_REFACTOR_PLAN.md`.
- Update `pyproject.toml` to point to the new entry points and dependencies; clean up unused imports and directories.

## Steps
1. Delete obsolete directories/files: `src/remora/hub/`, `src/remora/context/`, `src/remora/workspace.py` (old), `src/remora/agent_state.py`.
2. Clean up `pyproject.toml` by removing old scripts, adding dependencies for Starlette/uvicorn if not present, and ensuring extras include Cairn & structured-agents.
3. Update docs/README to mention `remora`, `remora-index`, `remora-dashboard` commands, the new workspace/context/executor structure, and link to the `.refactor` guides for future implementers.
4. Run `ruff`/`black` (if configured) on new modules to ensure formatting, and delete any generated artifacts (old `.grail` caches) from the repo.
