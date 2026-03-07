# Progress: Architecture Refactor

- [ ] **Phase 1: Sever Core -> LSP/Companion/Extensions** [ ]
  - [ ] Move `AgentRunner` out of `core/__init__.py`
  - [ ] Decouple `RemoraEvent` from `CompanionEvent` in `core/events.py`
  - [ ] Decouple `NodeProjection` from extensions in `core/projections.py`

- [ ] **Phase 2: Break LSP Circular Dependencies** [ ]
  - [ ] Remove module-level singleton and side effects from `lsp/server.py`
  - [ ] Inject server into handlers via parameter
  - [ ] Extract process lock from `lsp/__init__.py`

- [ ] **Phase 3: Decompose God-Objects & Group Core** [ ]
  - [ ] Split `EventStore` (1193 lines)
  - [ ] Split `AgentRunner` (743 lines)
  - [ ] Clean up `core/tools/`
  - [ ] Restructure `core/` into conceptual subpackages (`store/`, `events/`, `agents/`, `code/`, `tools/`)

- [ ] **Phase 4: Introduce Server Protocol** [ ]
  - [ ] Define `ServerProtocol` / `RunnerServer` protocol
  - [ ] Type `AgentRunner` against the protocol
  - [ ] Consider top-level `remora.runner` package

- [ ] **Phase 5: Cleanup and Polish** [ ]
  - [ ] Consolidate language extension maps into `utils/languages.py`
  - [ ] Rename `queries/` directory to `tree_sitter_queries/`
  - [ ] Clean up `__init__.py` re-exports
  - [ ] Consolidate tool infrastructure
