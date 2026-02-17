# DEV GUIDE STEP 8: Accept / Reject / Retry Workflow

## Goal
Expose workspace change control via `RemoraAnalyzer` methods.

## Why This Matters
User-controlled merging is a core principle of the system.

## Implementation Checklist
- Implement `accept`, `reject`, `retry` on `RemoraAnalyzer`.
- Support filtering by node and/or operation.
- Integrate with Cairn workspace merge APIs.

## Suggested File Targets
- `remora/analyzer.py`
- `remora/orchestrator.py`

## Implementation Notes
- `accept` should merge selected workspace changes into stable.
- `reject` should mark operation as rejected and not merge.
- `retry` should re-run the operation with optional config overrides.

## Testing Overview
- **Integration test:** Accept merges lint fixes into stable workspace.
- **Integration test:** Reject leaves stable unchanged.
- **Integration test:** Retry with overrides updates operation output.
