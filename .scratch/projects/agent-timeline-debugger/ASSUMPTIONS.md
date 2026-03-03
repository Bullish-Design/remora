# Assumptions — Agent Timeline Debugger

## Audience
- Remora developers who need to debug multi-agent event flows
- Users monitoring real-time agent activity in Neovim

## Constraints
- All timeline-specific code in `timeline/` at repo root (same as `browser_demo/`)
- LSP command handler stays in `src/remora/lsp/handlers/commands.py` (needs server access)
- Lua UI stays in `src/remora/lsp/nvim/lua/remora/timeline.lua` (needs Neovim plugin path)
- TDD mandatory: failing test first, then implement
- No isinstance in business logic
- AgentNode is a single Pydantic BaseModel, no subclasses

## Key Invariants
- EventStore is the single source of truth for all events
- Timeline query returns data atomically (single SQLite transaction)
- Timeline buffer is read-only (like panel chat buffer)
- All UI interaction through keybindings

## Dependencies
- EventStore (exists): SQLite-backed, WAL mode, has events/nodes/activation_chain tables
- Panel.lua (exists): Pattern for NuiLine rendering, highlight groups, buffer management
- LSP commands (exists): Pattern for `@server.command()` handlers
- NuiLine (exists): Rendering primitive for Neovim buffers

## Structural Decision
- `timeline/src/timeline_debugger/` — Python package with models and query logic
- `timeline/tests/` — Tests for the Python package
- Query functions take a raw SQLite connection, making them testable with in-memory SQLite
- EventStore.get_timeline_data() delegates to query module functions
