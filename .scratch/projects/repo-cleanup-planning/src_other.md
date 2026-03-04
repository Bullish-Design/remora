# src/remora/ (non-core, non-lsp) — Shadow Tree Notes

## Top-level files:
- `__init__.py` — Public API surface. KEEP, update after cleanup.
- `__main__.py` — CLI entry. KEEP.
- `extensions.py` — AgentExtension base class. NEW (Phase 1). KEEP.

## Subdirectories:

### adapters/ — KEEP
- `starlette.py` — Starlette adapter for ASGI. Web integration. KEEP.

### cli/ — KEEP
- `main.py` — CLI commands. KEEP.

### models/ — KEEP
- `__init__.py` — Service API models (ConfigSnapshot, InputResponse, etc.). KEEP.

### nvim/ — KEEP
- `server.py` — Neovim JSON-RPC server. Uses EventStore. KEEP.

### service/ — KEEP
- `api.py` — Service entry point. Uses EventStore + EventBus. KEEP.
- `chat_service.py` — Chat service. KEEP.
- `datastar.py` — Datastar SSE rendering. KEEP.
- `handlers.py` — Service request handlers. KEEP.

### testing/ — KEEP
- `fakes.py` — Test fakes/mocks. KEEP.

### ui/ — KEEP
- `projector.py` — Event→UI projector. KEEP.
- `view.py` — UI view models. KEEP.
- `components/` — iocraft UI components. KEEP but iocraft dependency broken.

### utils/ — KEEP
- `fs.py`, `path_resolver.py`, `text.py`, `types.py` — Utility modules. KEEP.

### queries/ — KEEP
- Tree-sitter query files (.scm) for Python, TOML, Markdown. KEEP.

### fixtures/ — KEEP
- `multilang_project/` — Test fixture for multi-language discovery. KEEP.
