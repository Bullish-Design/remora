# DEV GUIDE STEP 9: CLI Analyze + List Agents

## Goal
Deliver the end-to-end CLI experience for analysis.

## Why This Matters
This is the main entrypoint for users and the MVP surface.

## Implementation Checklist
- Implement `remora analyze` to run discovery → orchestration → results.
- Implement `remora list-agents` to show bundled agents.
- Map exit codes for success/partial/failure.

## Suggested File Targets
- `remora/cli.py`
- `remora/commands/analyze.py`
- `remora/commands/list_agents.py`

## Implementation Notes
- Use `SPEC.md` section 1 for CLI options and exit codes.
- JSON output should be machine-readable without extra formatting.
- Interactive output should pass through the formatter.

## Testing Overview
- **Integration test:** `remora analyze` on sample project returns results.
- **Integration test:** Partial failure returns exit code `1`.
- **CLI test:** `remora list-agents -f json` matches schema.
