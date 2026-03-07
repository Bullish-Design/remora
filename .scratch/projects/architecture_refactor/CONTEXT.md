# Context: Architecture Refactor

## Current State
Starting the `architecture_refactor` project. The `ARCH_REFACTOR_PLAN.md` has been established based on the `ARCH_REFACTOR_REPORT.md` findings and dependency graph analysis. No implementation work has started yet.

The primary goal is to resolve layer violations from `core` outwards, untangle the LSP circular dependencies, and decompose God-objects (`EventStore`, `AgentRunner`, `lsp/__init__.py`) into focused modules.

## Next Steps
- Begin Phase 1: Sever `core` -> `lsp`/`companion`/`extensions` dependencies.
- Fix `core/__init__.py` to stop re-exporting `AgentRunner`.
- Fix `core/events.py` `RemoraEvent` union and decouple from `CompanionEvent`.
- Update `NodeProjection` to use an injected matcher instead of importing extensions.
