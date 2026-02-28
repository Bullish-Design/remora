# Remora — Reactive Swarm Agent Framework

Remora V2 is an event-driven framework for running reactive agent swarms. Agents respond to events from a subscription registry, execute in isolated Cairn workspaces, and emit lifecycle events through an EventStore.

## Quick Start

1. Start a vLLM-compatible server (default: `http://localhost:8000/v1`).
2. Copy `remora.yaml.example` → `remora.yaml` and configure your model and bundles.
3. Start the reactive swarm:

```bash
remora swarm start
```

4. Emit events to trigger agents:

```bash
remora swarm emit AgentMessageEvent '{"to_agent": "<agent_id>", "content": "hello"}'
```

## Swarm Model

Remora uses an event-driven architecture:

- **EventStore**: Append-only log of all events, the single source of truth
- **SubscriptionRegistry**: Maps events to agents via pattern matching
- **SwarmState**: Tracks active agents and their metadata
- **AgentRunner**: Consumes triggers from EventStore and executes agent turns

Agents are discovered from code via tree-sitter, given persistent workspaces in `.remora/agents/<id>/`, and triggered by events matching their subscriptions.

## CLI Commands

```bash
remora swarm start          # Start the reactive swarm
remora swarm list          # List discovered agents
remora swarm emit          # Emit an event to trigger agents
remora serve               # Start the HTTP service
```

## Configuration

See `remora.yaml.example` for the flat configuration format. Key options:

- `model_base_url`: vLLM endpoint
- `model_default`: Default model name
- `bundle_root`: Directory containing agent bundles
- `swarm_root`: Directory for swarm state (default: `.remora`)

## Installation

```bash
pip install remora
pip install "remora[backend]"   # With structured-agents and vLLM support
pip install "remora[full]"      # Everything included
```

## Documentation

- `docs/ARCHITECTURE.md` — Swarm architecture and data flow
- `docs/CONFIGURATION.md` — Configuration reference
- `HOW_TO_USE_REMORA.md` — Detailed usage guide
