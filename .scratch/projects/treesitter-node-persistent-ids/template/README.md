# Persistent Tree-sitter IDs Template

Template scaffold for durable declaration IDs embedded inline as `graph:id=<id>`.

## Objective
Track stable entity identity across reparses/renames/moves by treating IDs as source-level facts.

## Scope
- Parse Python and Markdown with Tree-sitter
- Extract declaration/section nodes
- Recover `graph:id` from declaration header lines
- Persist entities and anchors in SQLite
- Support future incremental parse updates

## Quickstart
```bash
uv sync --extra dev
uv run persistent-ids init-db --db ./.state/persistent_ids.db
uv run persistent-ids index --db ./.state/persistent_ids.db --root /path/to/repo
```

## Layout
- `src/persistent_ids/`: core package
- `queries/`: language extraction queries
- `tests/`: starter test suite
- `docs/`: architecture and implementation notes

## Status
This is a scaffold template. Some extraction and incremental parsing methods are intentionally stubs.
