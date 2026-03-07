# Remora Architecture Refactoring Report

Based on an analysis of the module dependency graph (`tach_module_graph.dot`), several architectural violations and refactoring opportunities have been identified. The most critical issues involve the "core" module depending on outer layers (layer violations) and circular dependencies within the LSP module.

## 1. Domain Layer Violations (Core Dependencies)
The `remora.core` package represents the inner domain logic. It should not have any dependencies on external protocols, UI, or optional feature plugins. However, the graph reveals multiple violations where `core` reaches outwards:

*   **`core` -> `lsp`**: `remora.core` imports `remora.lsp.runner`. The core domain logic must be completely decoupled from the Language Server Protocol transport layer. 
*   **`core` -> `companion`**: `remora.core.events` imports from `remora.companion.events`. The core event system should not be aware of specific downstream features like the companion. The companion should depend on the core to register its events.
*   **`core` -> `extensions`**: `remora.core.projections` depends on `remora.extensions`. Core projections should be generic and not tightly coupled to extensions.

## 2. Circular Dependencies
Circular dependencies make modules difficult to test, reason about, and initialize. The graph highlights some tight coupling within the `remora.lsp` package:

*   **LSP Server & Handlers**: `remora.lsp.server` <-> `remora.lsp.handlers`
*   **LSP Server & Notifications**: `remora.lsp.server` <-> `remora.lsp.notifications`

*Recommendation*: Break these cycles by injecting a server interface/context into handlers and notifications, rather than having them statically import the concrete server implementation.

## 3. Package Entrypoint Leakage
*   **`remora.lsp` -> `remora.lsp.__main__`**: The `__init__.py` for the `lsp` module imports its own executable entrypoint (`__main__`). Entrypoints should import from the package to execute it, but the package itself should remain pure and unaware of its entrypoints to avoid side-effects when imported as a library.

## 4. UI and API Layer Coupling
*   **`remora.service.api` -> `remora.ui.view` / `remora.ui.projector`**: The API service layer directly imports UI rendering components. If this is intended as a strict Backend-For-Frontend (BFF) emitting Datastar HTML, this may be acceptable. However, structurally decoupling the data-serving API from the UI definitions can increase flexibility for potential non-HTML clients or purely headless operation.

## 5. SQL Query Fragmentation
*   **Scattered Queries**: SQL strings are currently scattered across multiple modules (`remora.lsp.db`, `remora.lsp.graph`, `remora.core.subscriptions`, `remora.core.event_store`, `remora.core.projections`). Centralizing all queries into a dedicated queries module (e.g., `remora.core.queries` or `remora.lsp.queries`) will improve maintainability, make schema changes easier to track, and keep the Python logic clean.

## Next Steps
1.  **Untangle Core**: Start by scrubbing `src/remora/core/__init__.py` and other core modules of any imports from `lsp`, `companion`, or `extensions`.
2.  **Refactor LSP Initialization**: Redesign how handlers and notifications are registered with the `remora.lsp.server` to break the import cycles.
3.  **Clean Entrypoints**: Remove `__main__` imports from `__init__.py` files across the codebase.
4.  **Centralize SQL**: Extract scattered SQL queries into an appropriate centralized repository or query module.
