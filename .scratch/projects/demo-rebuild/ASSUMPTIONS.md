# ASSUMPTIONS — Demo Rebuild

## Audience
- Single developer running locally. The demo is for showing one person how the EventBased architecture works.
- Not production. No multi-user, no auth, no error recovery.

## Environment Split
- **`remora_demo/neovim/`** — Neovim + LSP + Remora demo. Python 3.13 (vllm needs it).
- **`remora_demo/web/`** — Stario web graph viewer. Python 3.14 (Stario requires it).
- Each has its own `devenv.nix` with independent Python environments.
- Wire the two together at the end — don't worry about cross-env communication until then.
- Both connect to the same SQLite database (the EventLog/projected tables).

## Shared Assets
- `remora_demo/project/` — configlib demo project files. Both environments reference this.
- `remora_demo/mock_llm.py` — Enhanced MockLLMClient. Used by the neovim side.

## Architecture
- `docs/EventBased_Concept.md` is authoritative for architecture.
- EventStore (SQLite, WAL mode) is the single source of truth.
- AgentNode (Pydantic BaseModel) — single model, no subclasses.
- Graph viewer uses Stario + Relay + Datastar. Server-rendered everything. No d3-force on client.
- Two processes: LSP server (stdio, Neovim) + Graph viewer (HTTP, Stario). Shared SQLite DB.
- MockLLMClient provides deterministic scripted responses for the golden path.

## Core Migration Status
- Option A unification is COMPLETE (commit 7f90eaf). 205 tests pass.
- ASTAgentNode fully removed from `src/remora/lsp/`.
- AgentRunner exists in `src/remora/lsp/runner.py` and is functional.
- Tasks T3-T13 from the demo plan may partially overlap with Option A work. Evaluate each individually.

## devenv Status
- Remora's devenv is broken (iocraft hash mismatch). Use `uv pip install -e ".[dev]"` as fallback.
- The web/ subdirectory will have its own devenv.nix (Python 3.14 for Stario).
- The neovim/ subdirectory either uses the parent devenv or has its own.

## Plan Source
- Full plan in `EVENT_BASED_DEMO_PLAN.md` (3800+ lines, 14 sections, 22 tasks).
- Demo brainstorming in `EventBased_Demo.md` (743 lines).
