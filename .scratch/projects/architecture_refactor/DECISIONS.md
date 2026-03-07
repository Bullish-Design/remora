# Decisions: Architecture Refactor

## Decision Log

- **Target Architecture Strictness**: We are explicitly enforcing a unidirectional dependency graph: `Runner`/`LSP`/`Companion` -> `Core` -> `Utils`. Upward references are banned.
- **Event Composition**: `RemoraEvent` logic is changing from an overly broad union type to isolated definitions. `core` will define `CoreEvent`, and `companion` will define its own `CompanionEvent`. Event storage uses the generic `_FrozenEvent` base.
- **Dependency Injection**: Hard-coded dependencies in `NodeProjection` and LSP handlers will be shifted to dependency injection (e.g., passing callables, parameter injection in `pygls`).
- **Idempotency Over Caching**: We will break singletons and global state initialization (like `get_server()` at module level) in favor of controlled, explicit instantiations.
