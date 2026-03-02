# CONTEXT — Demo Rebuild

## Current State
Project planning is complete. T1, T2, T14 are already implemented. Ready to begin the Graph Viewer workstream (T15-T22).

## What Just Happened
- Previous session: Created project directory with all standard files, explored the full codebase
- This session: Reconciled PROGRESS.md with actual codebase state — T1 (configlib project files), T2 (extension configs), and T14 (MockLLMClient) are all implemented and present in the repo
- Confirmed web/graph/ stubs are all empty (just docstrings) — T15-T20 are truly pending
- No archiving of remora_demo/ was needed — the current structure already matches the plan

## What's Next
1. **T15** — Implement ForceLayout in `remora_demo/web/graph/layout.py` (server-side force-directed graph layout)
2. **T16** — SVG element builders in `remora_demo/web/graph/svg.py`
3. **T17** — CSS theme in `remora_demo/web/graph/css.py` (Catppuccin dark + CSS transitions)
4. **T18** — DB->Relay bridge in `remora_demo/web/graph/bridge.py` (polls SQLite, publishes to Relay)
5. **T20** — View functions (shell.py, graph.py, sidebar.py, event_stream.py)
6. **T19** — Stario app factory + route wiring
7. **T21** — Entry points + launcher
8. **T22** — Integration test

## Key Decision Pending
- Need to verify Stario is available as a dependency (check pyproject.toml or devenv.nix)
- Path convention: plan says `remora_demo/graph/` but code uses `remora_demo/web/graph/` — using web/graph/ since that's what exists

## Key Files
- `EVENT_BASED_DEMO_PLAN.md` — Full implementation plan, Sections 7-11 cover graph viewer
- `docs/EventBased_Concept.md` — Authoritative architecture
- `src/remora/core/event_store.py` — EventStore API (get_node_at_position, list_nodes, etc.)
- `src/remora/core/agent_node.py` — AgentNode model
- `remora_demo/neovim/mock_llm.py` — Completed MockLLMClient
- `remora_demo/project/` — Completed configlib demo files
