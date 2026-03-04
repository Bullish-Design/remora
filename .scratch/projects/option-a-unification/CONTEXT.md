# Option A: LSP→EventStore Unification — Context

**Status: COMPLETE** — No further work needed.

## What This Project Did

Migrated the entire LSP subsystem from a parallel node lifecycle (ASTAgentNode + RemoraDB nodes table) to use the core EventStore + AgentNode. Before this project, there were two independent paths for node state:

- **Core path**: CSTNode → NodeDiscoveredEvent → EventStore → NodeProjection → nodes table → AgentNode
- **LSP path**: ASTWatcher → ASTAgentNode objects → RemoraDB.upsert_nodes() → separate SQLite → ASTAgentNode

After unification, there is one path: the core path. The LSP watcher produces dicts, documents.py emits events, and all handlers read AgentNode from EventStore.

## What Was Deleted

- `ASTAgentNode` class (from `lsp/models.py`)
- `ToolSchema` Pydantic model (from `lsp/models.py`) — replaced by dataclass in `core/agent_node.py`
- `lsp/extensions.py` — replaced by `extensions.py` AgentExtension
- RemoraDB `nodes` table + all node query methods

## What Changed

- `LazyGraph` now uses dual DB connections: nodes from EventStore, edges from RemoraDB
- All LSP handlers read from EventStore via AgentNode
- All `remora_id` references removed from `src/remora/`
