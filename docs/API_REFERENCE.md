# API Reference

## CLI

### `remora swarm start`

Start the reactive swarm. Discovers agents, reconciles workspaces, and begins consuming events.

Key flags:
- `--project-root`: Override project root directory
- `--config`: Path to `remora.yaml`
- `--lsp`: Start Neovim LSP JSON-RPC server alongside the swarm

### `remora swarm list`

List all discovered agents and their metadata.

### `remora swarm emit`

Emit an event to trigger agents.

```bash
remora swarm emit AgentMessageEvent '{"to_agent": "agent_123", "content": "hello"}'
remora swarm emit ContentChangedEvent '{"path": "src/main.py"}'
```

### `remora swarm reconcile`

Reconcile agent state: re-discover agents, update workspaces, sync subscriptions.

### `remora serve`

Start the HTTP service (Starlette adapter).

Key flags:
- `--host`, `--port`: Bind address (default: `127.0.0.1:8420`)
- `--project-root`: Override project root
- `--config`: Path to `remora.yaml`

### `remora workspace`

Workspace management subcommands.

## Python Public API

Exports from `remora` (see `src/remora/__init__.py`):

### Core Runtime

- `remora.core.config`: `Config`, `load_config()`, `serialize_config()`
- `remora.core.discovery`: `discover()`, `CSTNode`, `LANGUAGE_EXTENSIONS`, `compute_node_id()`
- `remora.core.event_store`: `EventStore`
- `remora.core.event_bus`: `EventBus`, `EventHandler`
- `remora.core.subscriptions`: `SubscriptionRegistry`, `SubscriptionPattern`, `Subscription`
- `remora.core.agent_node`: `AgentNode` (unified agent model)
- `remora.core.agent_context`: `AgentContext`
- `remora.core.swarm_executor`: `SwarmExecutor`
- `remora.core.reconciler`: `reconcile_on_startup()`, `get_agent_dir()`, `get_agent_workspace_path()`
- `remora.core.errors`: `RemoraError`, `ConfigError`, `DiscoveryError`, `ExecutionError`, `WorkspaceError`

### Events (`remora.core.events`)

All event classes:
- `RemoraEvent` (base)
- `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`
- `AgentMessageEvent`, `ContentChangedEvent`, `FileSavedEvent`
- `ManualTriggerEvent`, `NodeDiscoveredEvent`, `NodeRemovedEvent`
- `HumanInputRequestEvent`, `HumanInputResponseEvent`
- `ModelRequestEvent`, `ModelResponseEvent`
- `ToolCallEvent`, `ToolResultEvent`
- `KernelStartEvent`, `KernelEndEvent`, `TurnCompleteEvent`

### Workspaces

- `remora.core.workspace`: `AgentWorkspace`, `CairnDataProvider`
- `remora.core.cairn_bridge`: `CairnWorkspaceService`
- `remora.core.cairn_externals`: `CairnExternals`

### Tools

- `remora.core.tools`: `RemoraGrailTool`, `build_virtual_fs()`, `discover_grail_tools()`

### LSP

- `remora.lsp.runner`: `AgentRunner` (LSP-integrated agent runner)

### Service Layer

- `remora.service.api`: `RemoraService` (framework-agnostic API)
- `remora.adapters.starlette`: `create_app()` (Starlette HTTP adapter)

### Models (`remora.models`)

- `SwarmEmitRequest`, `SwarmEmitResponse`
- `InputResponse`
- `ConfigSnapshot`

### Utilities

- `remora.utils`: `PathResolver`, `to_project_relative()`
