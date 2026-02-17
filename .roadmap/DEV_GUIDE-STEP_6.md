# DEV GUIDE STEP 6: Specialized Agents MVP

## Goal
Implement lint, test, docstring, and optional sample data agents.

## Why This Matters
These agents deliver the actual code improvements for the MVP.

## Implementation Checklist
- Implement `lint_agent.pym` (ruff/pylint) with fix support.
- Implement `test_generator_agent.pym` for pytest/unittest.
- Implement `docstring_agent.pym` with style options.
- Implement `sample_data_agent.pym` if enabled in config.
- Ensure output `details` match spec schemas.

## Suggested File Targets
- `agents/lint_agent.pym`
- `agents/test_generator_agent.pym`
- `agents/docstring_agent.pym`
- `agents/sample_data_agent.pym`

## Implementation Notes
- Follow input/output contracts in `SPEC.md` sections 6.2–6.6.
- Use Cairn `write_file`, `read_file`, and `run_command` helpers.
- Return `status=skipped` when operation is not applicable.

## Testing Overview
- **Unit test:** Each agent returns valid schema for success.
- **Unit test:** `details` keys match expected schema.
- **Integration test:** Run agents on fixture code and verify outputs.
