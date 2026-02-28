# How to Use Remora

This guide covers the Remora reactive swarm architecture.

## 1. Quick Start

### Requirements

- Python 3.13+
- vLLM-compatible model server
- Cairn AgentFS for workspaces

### Configuration

Create `remora.yaml`:

```yaml
project_path: "."
discovery_paths: ["src/"]
discovery_languages: ["python"]
discovery_max_workers: 4

bundle_root: "agents"
bundle_mapping:
  function: "lint/bundle.yaml"
  class: "docstring/bundle.yaml"
  file: "lint/bundle.yaml"

model_base_url: "http://localhost:8000/v1"
model_api_key: "EMPTY"
model_default: "Qwen/Qwen3-4B"

swarm_root: ".remora"
swarm_id: "swarm"
max_concurrency: 4
max_turns: 8
timeout_s: 300
truncation_limit: 1024
```

### CLI Commands

```bash
# Start the reactive swarm
remora swarm start

# List discovered agents
remora swarm list

# Emit an event to trigger an agent
remora swarm emit AgentMessageEvent '{"to_agent": "<agent_id>", "content": "hello"}'
remora swarm emit ContentChangedEvent '{"path": "src/main.py"}'

# Start the HTTP service
remora serve --host 0.0.0.0 --port 8420
```

---

## 2. Core Concepts

### EventStore

Append-only event log. All events flow through it. Agents consume triggers by matching subscriptions.

```python
from remora.core.event_store import EventStore

event_store = EventStore(path)
await event_store.initialize()

# Append events
event_id = await event_store.append("swarm", AgentMessageEvent(...))

# Consume triggers
async for agent_id, depth, event in event_store.get_triggers():
    # Process trigger
    ...
```

### SubscriptionRegistry

Maps event patterns to agents. Each agent can have multiple subscriptions.

```python
from remora.core.subscriptions import SubscriptionRegistry, SubscriptionPattern

subscriptions = SubscriptionRegistry(path)
await subscriptions.initialize()

# Register a subscription
await subscriptions.register(
    agent_id="agent_123",
    pattern=SubscriptionPattern(
        event_types=["AgentMessageEvent", "ContentChangedEvent"],
        path_glob="src/**/*.py",
    ),
)
```

### SwarmState

Tracks discovered agents and their metadata.

```python
from remora.core.swarm_state import SwarmState, AgentMetadata

swarm_state = SwarmState(path)
swarm_state.initialize()

# List agents
agents = swarm_state.list_agents(status="active")

# Get specific agent
agent = swarm_state.get_agent(agent_id)
```

---

## 3. Service API

Start with `remora serve`. Endpoints:

- `GET /swarm/agents` - List all agents
- `GET /swarm/agents/{id}` - Get agent details
- `POST /swarm/events` - Emit an event
- `GET /swarm/subscriptions/{id}` - Get agent subscriptions

---

## 4. Neovim Integration

Remora provides a JSON-RPC server for Neovim:

```bash
remora swarm start --nvim
```

Connect via `nvim --listen .remora/nvim.sock`.

Commands:
- `swarm.emit` - Emit events
- `agent.select` - Select an agent
- `agent.subscribe` - Manage subscriptions
