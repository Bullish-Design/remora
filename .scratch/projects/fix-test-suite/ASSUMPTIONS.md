# ASSUMPTIONS — Fix Test Suite

## Scope
- Fix all failing tests EXCEPT `tests/companion/*` (under active development).
- Companion tests are documented but not touched.
- Cairn integration tests are already excluded via `--ignore`.

## Environment
- vLLM server IS running and available for integration tests.
- All commands run via `devenv shell -- <command>`.
- Dependencies managed via `uv sync --extra dev` only.

## Constraints
- No changes to production logic unless a test reveals a genuine bug.
- Test fixes should correct test expectations to match current APIs, not change APIs to match old tests.
- `ConstraintPipeline.no_constraints()` was removed from `structured_agents` — production code already uses `None` instead.

## Quality Bar
- All non-companion, non-cairn tests must pass (target: 0 failures).
- Hypothesis tests must not be flaky (no deadline failures on subprocess tests).
- Coverage analysis is informational — we don't need to hit a specific number, but we should identify and prioritize gaps.
