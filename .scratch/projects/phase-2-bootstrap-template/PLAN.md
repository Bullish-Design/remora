# PLAN

## Objective
Create and evolve bootstrap-native Remora functionality in `bootstrap/`.

## Initial Steps
1. Define bootstrap contracts for tools, agents, templates.
2. Build registry + runtime facade that imports Remora as a library.
3. Add bootstrap tool/agent/template primitives.
4. Add tests for registry integrity and runtime behaviors.
5. Add integration path into Neovim/UI once bootstrap core is stable.

## Acceptance Criteria
- Bootstrap package runs independently from repo-level agent bundles.
- Core tools/agents/templates are discoverable from one registry.
- Runtime can execute tool handlers and render templates.
- Documentation explains Phase 2 boundaries and extension workflow.
