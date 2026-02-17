# DEV GUIDE STEP 11: MVP Acceptance Tests

## Goal
Validate the MVP end-to-end against acceptance criteria.

## Why This Matters
Acceptance tests confirm that the system delivers the promised behavior.

## Implementation Checklist
- Add tests for each acceptance criterion in `SPEC.md` section 10.3.
- Ensure tests run against a small fixture project.
- Document how to run the acceptance suite.

## Suggested File Targets
- `tests/acceptance/`
- `tests/fixtures/sample_project/`

## Implementation Notes
- Keep fixture projects minimal but realistic.
- Use deterministic assertions for output files and results.
- Prefer black-box tests that call the CLI.

## Testing Overview
- **Acceptance test 1:** Lint suggestions accepted → files updated.
- **Acceptance test 2:** Test generation → test file created.
- **Acceptance test 3:** Docstrings added to class.
- **Acceptance test 4:** Multiple nodes → all results returned.
- **Acceptance test 5:** Agent failure → others continue.
- **Acceptance test 6:** Watch mode triggers on change.
