# Remora Architecture DOT Graphs

- `remora_architecture_layers.dot`: layered system context (interfaces, entrypoints, runtime, data).
- `remora_reactive_event_loop.dot`: event-driven runtime loop from event append to agent execution.
- `remora_package_dependencies.dot`: top-level package dependency map aggregated from `tach_module_graph.dot`.
- `remora_core_subsystems.dot`: dependency view inside `remora.core`.
- `remora_lsp_subsystems.dot`: dependency view inside the LSP subsystem and its cross-package links.

Regenerate the package dependency graph from the latest Tach graph:

```bash
just gen-package-graph
```

Equivalent direct command:

```bash
devenv shell -- python scripts/generate_package_dependency_graph.py
```

Render any graph with:

```bash
dot -Tsvg docs/graphs/remora_reactive_event_loop.dot -o /tmp/remora_reactive_event_loop.svg
```
