# DEV GUIDE STEP 7: Results Aggregation + Formatting

## Goal
Provide consistent result models and output formats.

## Why This Matters
Users need a reliable summary of what happened and what to do next.

## Implementation Checklist
- Implement `AnalysisResults`, `NodeResult`, and `OperationResult` models.
- Add formatters for table, JSON, and interactive outputs.
- Include failure summaries and next-step hints.

## Suggested File Targets
- `remora/results.py`
- `remora/formatters.py`

## Implementation Notes
- Match models in `SPEC.md` section 4.
- Follow output format examples in `SPEC.md` section 8.
- Keep table rendering in Rich to match CLI output.

## Testing Overview
- **Unit test:** JSON formatting matches schema.
- **Unit test:** Table formatter renders expected columns.
- **Integration test:** Interactive formatter prompts and accepts decisions.
