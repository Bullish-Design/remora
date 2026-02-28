# Remora Architecture

Remora V2 uses a reactive swarm architecture built around events, subscriptions, and per-agent workspaces.

```
                  ┌────────────┐         ┌────────────┐
                  │   User     │◀───────▶│ Service    │
                  │ Interface  │         │  / CLI     │
                  └────────────┘         └────────────┘
                         │                  ▲
                         ▼                  │
                   ┌──────────────────────────────────────────┐
                   │              EventStore                    │
                   │  (Append-only log, single source of truth) │
                   └─────────────┬──────────────┬──────────────┘
                                 │              │
                    ┌────────────▼───┐  ┌───────▼────────┐
                    │ Subscription   │  │   AgentRunner  │
                    │   Registry     │  │  (reactive loop)│
                    └───────┬────────┘  └───────┬────────┘
                            │                   │
                    ┌───────▼────────┐  ┌───────▼────────┐
                    │  EventBus       │  │  SwarmExecutor │
                    │  (notifications)│  │  (agent turns) │
                    └─────────────────┘  └────────────────┘
```

## Core Components

### EventStore (`remora.core.event_store`)

- Append-only event log, the single source of truth
- All events flow through it (not EventBus alone)
- Provides `append()` to write events and `get_triggers()` to iterate matched subscriptions
- Used by AgentRunner to consume triggers

### SubscriptionRegistry (`remora.core.subscriptions`)

- Maps event patterns to agents
- Each subscription has: event_types, from_agents, to_agent, path_glob, tags
- Supports default subscriptions for newly discovered agents

### SwarmState (`remora.core.swarm_state`)

- Tracks discovered agents and metadata
- Stores agent_id, node_type, name, full_name, file_path, range
- Provides CRUD operations for agents

### AgentRunner (`remora.core.agent_runner`)

- Main reactive loop
- Consumes triggers from EventStore
- Uses SwarmExecutor to run agent turns
- Respects concurrency and cooldown limits

### SwarmExecutor (`remora.core.swarm_executor`)

- Runs single agent turns via structured-agents kernel
- Provisions per-agent Cairn workspaces
- Emits lifecycle events (AgentStart, AgentComplete, AgentError)

### CairnWorkspaceService (`remora.core.cairn_bridge`)

- Manages stable and per-agent workspaces
- Stable workspace: `.remora/stable.db` (synced project files)
- Agent workspaces: `.remora/agents/<id>/workspace.db`

## Data Flow

1. Discovery finds code elements via tree-sitter
2. Reconciliation creates agents in SwarmState with default subscriptions
3. Events are emitted (via CLI, Neovim, or service API)
4. EventStore appends events and matches subscriptions
5. AgentRunner picks up triggers and executes agent turns
6. Agent completes, emits result events
7. Repeat

## Public API (`src/remora/__init__.py`)

- `EventStore`, `EventBus`, `SubscriptionRegistry`, `SubscriptionPattern`
- `SwarmState`, `AgentMetadata`
- `AgentRunner`, `AgentState`
- `AgentMessageEvent`, `ContentChangedEvent`, `FileSavedEvent`, `ManualTriggerEvent`
- `reconcile_on_startup` and path helpers
