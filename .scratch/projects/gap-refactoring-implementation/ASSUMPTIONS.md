# Gap Refactoring Implementation — ASSUMPTIONS

## Project Context
- This implements the 5 workstreams from the gap analysis refactoring plan
- The codebase uses devenv.sh — all commands via `devenv shell --`
- TDD: write failing tests first, then implement
- All packages in pyproject.toml are hard dependencies (no try/except guards)

## Key Constraints
- Must not break existing tests (except known pre-existing failures)
- AgentNode: single Pydantic BaseModel, no subclasses
- EventStore is the source of truth
- Must preserve backward compatibility for CLI path while fixing LSP path

## Architecture Decisions (from GAP_REFACTORING_PLAN.md)
- LSP path delegates to core, not the other way around
- `execute_agent_turn()` is a function, not a class
- LSP tools (rewrite_self, message_node, read_node) become proper tool classes
- Discovery unification: `ASTWatcher` delegates to `core.discovery.parse_content()`
- Deterministic node IDs (SHA256) adopted everywhere
