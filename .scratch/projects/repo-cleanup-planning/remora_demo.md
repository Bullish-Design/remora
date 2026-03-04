# remora_demo/ — Shadow Tree Notes

## Status: KEEP (graph viewer is valuable) + REMOVE .v1/ cruft

### Current (KEEP):
- `graph/` — Graph viewer TUI app (iocraft-based). app.py, shell.py, sidebar.py, state.py.
  Core demo functionality. KEEP.
- `web/` — Web-based graph viewer. app.py, layout.py, render.py, state.py.
  Web demo. KEEP.
- `nvim/` — Neovim demo config (lua/remora_starter.lua, remora.vim). KEEP.
- `__main__.py` — Demo entry point. KEEP.
- `README.md` — Demo docs. KEEP.

### Old demo workspace (.v1/) — REMOVE:
- `.v1/` contains 150+ files including:
  - `demo_workspaces/` — ~50 workspace directories with metadata.json and .py files
  - `one_stop_shop/` — Large demo project with ~60 .db-wal files (!)
  - Old demo scripts (api_demo.py, run_agent.py, setup_demo.py)
  - DEMO_DEVELOPMENT_LOG.md
  This is all old v1 demo cruft. 2.0GB+ of workspace artifacts. REMOVE.
