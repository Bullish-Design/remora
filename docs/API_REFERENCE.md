# API Reference

## CLI

### `remora swarm start`

Start the reactive swarm.

Key flags:
- `--config`: path to `remora.yaml`
- `--nvim`: start Neovim JSON-RPC server

### `remora swarm list`

List discovered agents.

### `remora swarm emit`

Emit an event to trigger agents.

```bash
remora swarm emit AgentMessageEvent '{"to_agent": "agent_123", "content": "hello"}'
remora swarm emit ContentChangedEvent '{"path": "src/main.py"}'
```

### `remora serve`

Start the HTTP service (Starlette adapter).

Key flags:
- `--host`, `--port`: bind address
- `--project-root`: override project root
- `--config`: path to `remora.yaml`

## Python Modules

### Core Runtime (`remora.core`)

- `remora.core.config`: `Config`, `load_config()`, `serialize_config()`
- `remora.core.discovery`: `discover()`, `CSTNode`, `TreeSitterDiscoverer`
- `remora.core.event_store`: `EventStore`, `EventSourcedBus`
- `remora.core.event_bus`: `EventBus`
- `remora.core.subscriptions`: `SubscriptionRegistry`, `SubscriptionPattern`
- `remora.core.swarm_state`: `SwarmState`, `AgentMetadata`
- `remora.core.agent_runner`: `AgentRunner`
- `remora.core.swarm_executor`: `SwarmExecutor`
- `remora.core.agent_state`: `AgentState`
- `remora.core.reconciler`: `reconcile_on_startup`, `get_agent_workspace_path`

### Events

- `remora.core.events`: Event classes (`AgentMessageEvent`, `ContentChangedEvent`, `FileSavedEvent`, `ManualTriggerEvent`, etc.)

### Workspaces

- `remora.core.workspace`: `AgentWorkspace`, `CairnDataProvider`
- `remora.core.cairn_bridge`: `CairnWorkspaceService`

### Service Layer

- `remora.service.RemoraService`: API surface with `/swarm/agents`, `/swarm/events`, etc.
- `remora.adapters.starlette.create_app`: Starlette adapter

### Models

- `remora.models.SwarmEmitRequest`, `SwarmEmitResponse`
