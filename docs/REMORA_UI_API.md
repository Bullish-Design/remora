# Remora UI API

Remora exposes a small, stable service contract intended for Datastar or external frontends.

## Endpoints

- `GET /` — HTML shell (Datastar script + `data-init` pointing at `/subscribe`)
- `GET /subscribe` — Datastar SSE patches (`patch-elements`)
- `GET /events` — raw JSON SSE events (envelopes)
- `POST /run` — start a graph run
- `POST /input` — submit a human response
- `GET /config` — sanitized config snapshot
- `POST /plan` — preview a graph without executing
- `GET /snapshot` — current UI state snapshot

## Request/Response Shapes

### `POST /run`

Request:

```json
{
  "target_path": "src/",
  "bundle": "lint",
  "graph_id": "optional-id"
}
```

Response:

```json
{
  "graph_id": "a1b2c3d4",
  "status": "started",
  "node_count": 14
}
```

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

### `POST /plan`

Request:

```json
{
  "target_path": "src/",
  "bundle": "lint"
}
```

Response:

```json
{
  "nodes": [
    {
      "id": "node-id",
      "name": "function_name",
      "node_type": "function",
      "file_path": "src/module.py",
      "bundle_path": "agents/lint.pym",
      "upstream": [],
      "downstream": [],
      "priority": 0
    }
  ],
  "bundles": {
    "function": "agents/lint.pym"
  }
}
```

### `GET /config`

Response (sanitized):

```json
{
  "discovery": { "paths": ["src/"], "languages": null, "max_workers": 4 },
  "bundles": { "path": "agents/", "mapping": { "function": "lint.pym" } },
  "execution": { "max_concurrency": 4, "timeout": 300, "max_turns": 8 },
  "workspace": { "base_path": ".remora/workspaces", "cleanup_after": "1h" },
  "model": { "base_url": "http://localhost:8000/v1", "default_model": "Qwen/Qwen3-4B" }
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
  "graph_id": "graph-123",
  "agent_id": "agent-abc",
  "timestamp": 1735936486.123,
  "payload": { "agent_id": "agent-abc", "result_summary": "..." }
}
```

`kind` values include: `graph`, `agent`, `human`, `checkpoint`, `tool`, `model`, `kernel`, `turn`, `event`.

## UI Snapshot (`GET /snapshot`)

```json
{
  "events": [
    { "kind": "graph", "type": "GraphStartEvent", "graph_id": "...", "timestamp": 0, "payload": {} }
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
  ],
  "recent_targets": ["src/"]
}
```
