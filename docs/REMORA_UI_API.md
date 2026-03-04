# Remora UI API

Remora exposes a Starlette-based HTTP service for the Datastar frontend and external consumers. Start with `remora serve`.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | HTML shell (Datastar script + `data-init` pointing at `/subscribe`) |
| `GET` | `/subscribe` | Datastar SSE patches (`patch-elements`) |
| `GET` | `/events` | Raw JSON SSE event stream |
| `GET` | `/replay` | Replay events for a graph run (SSE) |
| `POST` | `/input` | Submit a human response |
| `GET` | `/config` | Sanitized config snapshot |
| `GET` | `/snapshot` | Current UI state snapshot |
| `GET` | `/swarm/agents` | List all agents |
| `GET` | `/swarm/agents/{id}` | Get a specific agent |
| `POST` | `/swarm/events` | Emit an event to the swarm |
| `GET` | `/swarm/subscriptions/{id}` | Get subscriptions for an agent |

## Request/Response Shapes

### `POST /input`

Request:

```json
{
  "request_id": "req-123",
  "response": "yes"
}
```

Response:

```json
{
  "request_id": "req-123",
  "status": "submitted"
}
```

### `POST /swarm/events`

Request:

```json
{
  "event_type": "AgentMessageEvent",
  "data": {
    "from_agent": "api",
    "to_agent": "agent-abc",
    "content": "hello"
  }
}
```

Response:

```json
{
  "event_id": "evt-456",
  "status": "emitted"
}
```

### `GET /replay`

Query parameters:

- `graph_id` (required) — The graph run to replay
- `follow` (optional) — `true` to keep the SSE stream open for live updates

Each SSE message:

```
event: replay
data: { "id": 1, "event_type": "AgentStartEvent", "data": {...}, "timestamp": "..." }
```

### `GET /config`

Response (sanitized):

```json
{
  "discovery": { "paths": ["src/"], "languages": null, "max_workers": 4 },
  "bundles": { "path": "agents/", "mapping": { "function": "lint/bundle.yaml" } },
  "execution": { "max_concurrency": 4, "timeout": 300, "max_turns": 8 },
  "model": { "base_url": "http://localhost:8000/v1", "default_model": "Qwen/Qwen3-4B" }
}
```

### `GET /snapshot`

Returns the current projected UI state:

```json
{
  "events": [
    { "kind": "agent", "type": "AgentStartEvent", "timestamp": 0, "payload": {} }
  ],
  "blocked": [
    { "agent_id": "agent-1", "question": "...", "options": ["yes", "no"], "request_id": "req-1" }
  ],
  "agent_states": {
    "agent-1": { "state": "started", "name": "agent-1" }
  },
  "progress": { "total": 10, "completed": 3, "failed": 1 },
  "results": [
    { "agent_id": "agent-1", "content": "...", "timestamp": 0 }
  ]
}
```

## SSE Event Envelope (`GET /events`)

Each SSE message uses:

```
event: AgentCompleteEvent
data: { ... }
```

Envelope shape:

```json
{
  "kind": "agent",
  "type": "AgentCompleteEvent",
  "agent_id": "agent-abc",
  "timestamp": 1735936486.123,
  "payload": { "agent_id": "agent-abc", "result_summary": "..." }
}
```

`kind` values include: `agent`, `human`, `tool`, `model`, `kernel`, `turn`, `event`.

## Implementation

- **Service layer**: `src/remora/service/api.py` — `RemoraService` class (framework-agnostic)
- **HTTP adapter**: `src/remora/adapters/starlette.py` — Starlette routes wiring
- **Handlers**: `src/remora/service/handlers.py` — Business logic for each endpoint
- **UI projector**: `src/remora/ui/projector.py` — Maintains projected UI state from event stream
