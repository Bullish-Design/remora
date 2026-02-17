# DEV GUIDE STEP 10: Watch Mode

## Goal
Implement reactive analysis for file changes.

## Why This Matters
Watch mode provides continuous feedback for developers.

## Implementation Checklist
- Implement file watcher using `watchfiles` with debounce.
- Re-run analysis only for modified `.py` files.
- Respect ignore patterns from config.

## Suggested File Targets
- `remora/watcher.py`
- `remora/commands/watch.py`

## Implementation Notes
- Debounce defaults and CLI overrides are defined in `SPEC.md`.
- Avoid reprocessing entire project when a single file changes.

## Testing Overview
- **Integration test:** Touch a file and confirm analysis triggers once.
- **Integration test:** Debounce prevents duplicate runs.
- **Integration test:** Ignore patterns skip `.git` and `__pycache__`.
