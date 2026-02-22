# Developer Guide

This guide is for contributors working on the `structured-agents` codebase itself. It complements `ARCHITECTURE.md` with deeper implementation details, design philosophy, and coding patterns.

## Purpose

`structured-agents` is intentionally small and composable. The goal is to provide a reliable, typed core for agent loops without forcing decisions about UI, workspace management, or multi-agent coordination.

If you are integrating the library into an application, start with `README.md`. If you are modifying the library, start here and in `ARCHITECTURE.md`.

## Design Philosophy

- **Small surface area**: each module handles one responsibility.
- **Deterministic behavior**: predictable output, explicit configuration.
- **Typed interfaces**: protocols for extensibility and strict type checking.
- **Minimal side effects**: most components are pure or isolated.
- **Tool safety**: Grail `.pym` scripts execute in isolated processes.

## Architectural Reference

Read `ARCHITECTURE.md` first to understand how components fit together. This guide focuses on implementation specifics.

## Core Concepts

### Agent Kernel

The `AgentKernel` owns the turn-by-turn loop. It does not manage workspace state or orchestration. Key responsibilities:

- Prepare model input via `ModelPlugin`.
- Make API calls via `OpenAICompatibleClient` (constructed by `build_client`).
- Parse tool calls and execute them via `ToolSource`.
- Trim history using `HistoryStrategy`.
- Emit observer events at each stage.
- Execute tools concurrently based on `ToolExecutionStrategy`.

### Model Plugins

Plugins are composed from protocol-defined components:

- `MessageFormatter`
- `ToolFormatter`
- `ResponseParser`
- `GrammarProvider`

`ComposedModelPlugin` wires these together and derives capability flags from the grammar provider.

### Tool Sources

`ToolSource` unifies tool discovery and execution. The default bridge (`RegistryBackendToolSource`) ties a registry and backend together.

### Tool Backends and Registries

Backends execute tool calls. `GrailBackend` is the default production implementation. `PythonBackend` exists for tests and simple local tooling. Registries provide tool schemas (`GrailRegistry`, `PythonRegistry`).

### Bundles

Bundles provide a deployable configuration format. The loader converts bundle definitions into `ToolSchema` objects, builds registries, and uses Jinja2 templates for prompt rendering.

### Observers

Observers allow external integrations to observe the kernel lifecycle. Observers must be async and non-blocking. Use `CompositeObserver` to multiplex events.

## Coding Patterns

### Immutability and Data Classes

Core types like `ToolCall`, `ToolResult`, and `RunResult` are immutable dataclasses. They should remain lightweight, serializable, and value-oriented.

### Protocol-Driven Extensibility

Every major integration point is a protocol. This ensures third parties can implement custom plugins/backends without modifying the kernel.

### Error Handling

- Throw `StructuredAgentsError` subclasses for systemic failures.
- Tool failures should return `ToolResult(is_error=True)` instead of raising.
- The kernel surfaces errors to observers via `on_error`.

### Logging

Modules should use `logging.getLogger(__name__)` and avoid `print()`. Observers provide a better channel for user-facing output.

### Grammar Constraints

Only grammar providers may generate constraints via `build_grammar` and `to_extra_body`. This keeps model-specific grammar logic isolated.

## Testing Strategy

- **Unit tests**: cover core types, plugins, backends, tool sources, and bundle loading.
- **Integration tests**: exercise a full agent loop with mocked model outputs.
- **Concurrency tests**: validate ordering and semaphore limits.
- Prefer deterministic behavior and avoid network calls.
- Use `PythonBackend` in tests unless `.pym` execution is required.

## Adding a New Plugin

1. Implement `MessageFormatter`, `ToolFormatter`, `ResponseParser`, and `GrammarProvider` components.
2. Compose them using `ComposedModelPlugin`.
3. Add tests for component behavior and plugin capabilities.
4. Export the plugin in `structured_agents/plugins/__init__.py`.

## Adding a New Tool Source

1. Implement the `ToolSource` protocol.
2. Add tests covering tool resolution and execution.
3. Export it in `structured_agents/tool_sources/__init__.py` if public.

## Adding a New Backend

1. Implement the `ToolBackend` protocol.
2. Add tests for execution and error handling.
3. Export it in `structured_agents/backends/__init__.py`.

## Adding a New Bundle Field

1. Extend the schema in `structured_agents/bundles/schema.py`.
2. Update the loader to interpret the new field.
3. Add tests covering the new behavior.

## Release Checklist

- Run full test suite: `uv run pytest -v --tb=short`.
- Update `__version__` in `structured_agents/__init__.py` when releasing.
- Verify `pyproject.toml` dependencies are up to date.

## Helpful References

- `ARCHITECTURE.md` for system overview.
- `tests/` for usage examples.
