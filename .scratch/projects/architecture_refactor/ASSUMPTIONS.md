# Assumptions: Architecture Refactor

## Project Audience & Goals
- The purpose of this refactor is solely internal code health, testability, and architectural integrity.
- Expected outcome is an easier-to-maintain codebase that allows isolated components to be independently tested and developed.

## Technical Constraints & Invariants
- **Testing Must Pass**: Existing tests (excluding known skipped/failing ones noted in `REPO_RULES.md`) must pass after each phase. We cannot break current features.
- `devenv shell -- uv sync --extra dev` must be used before testing.
- Hard dependencies in `pyproject.toml` should not be conditionally imported.
- The `AgentNode` must remain a single Pydantic BaseModel (no subclasses).
- **Tool usage**: No raw `try/except ImportError` for hard dependencies.

## Architecture Guidelines
- EventStore routing relies on event types and `.model_dump()`; explicit union types are not required for serialization/deserialization.
- The `pygls` handler implementations support dependency injection via the `LanguageServer` parameter, which is reliable and the preferred method over module-level singletons.
