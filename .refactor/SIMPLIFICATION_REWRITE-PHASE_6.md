# Phase 6 - Neovim Server Integration

## Goal
Add a Neovim-facing JSON-RPC server so the editor can emit events and subscribe to swarm updates in real time.

## Guiding principles
- Neovim is a subscriber and event source, not a special-case UI.
- Use EventBus for pushed UI updates; use EventStore for all persisted events.
- Follow the RPC contract described in `NVIM_DEMO_CONCEPT.md`.

## Definition of done
- `src/remora/nvim/server.py` implements a minimal JSON-RPC server.
- RPC handlers map to swarm actions (`swarm.emit`, `agent.select`, `agent.chat`, `agent.subscribe`).
- Events are forwarded to connected clients as notifications.

## Step-by-step implementation

### 1) Create the Neovim server module
Implementation:
- Create `src/remora/nvim/server.py` and `src/remora/nvim/__init__.py`.
- Implement an asyncio server that listens on `config.nvim_socket`.
- Use newline-delimited JSON messages for simplicity.
- Implement a small JSON-RPC parser that handles:
  - `id`, `method`, `params` for requests
  - Notifications without `id`

Testing:
- Add a unit test that opens a socket connection and sends a basic JSON-RPC request, verifying a response is returned.

### 2) Implement RPC handlers
Implementation:
- Add handler functions (or a method map) for:
  - `swarm.emit(event)` -> call `EventStore.append(...)` with routing fields
  - `agent.select(node_id)` -> load and return `AgentState`
  - `agent.chat(node_id, message)` -> emit `AgentMessageEvent` + trigger turn
  - `agent.subscribe(pattern)` -> call `SubscriptionRegistry.register(...)`
  - `agent.get_subscriptions(node_id)` -> return subscriptions
- Keep payloads JSON-serializable and stable.

Testing:
- Add a test that calls `agent.get_subscriptions` and verifies it returns a list of patterns.

### 3) Forward events to Neovim clients
Implementation:
- Subscribe to `EventBus` in the server and forward all events (or a filtered subset) as JSON-RPC notifications:
  - Example method: `event.subscribed`
- Ensure notifications include `event_type` and `payload` keys.

Testing:
- Add a test that emits an event on EventBus and verifies the client receives a notification.

### 4) Handle multiple clients
Implementation:
- Track connected clients in a set.
- Broadcast notifications to all clients; drop any client that disconnects.
- Keep per-client backpressure simple (skip if the socket is closed).

Testing:
- Add a test that connects two clients and verifies both receive the same notification.

### 5) Wire into startup
Implementation:
- Add a lightweight startup function (e.g., `start_nvim_server`) in `src/remora/cli/main.py` or a new service module.
- It should be optional and controlled by config or a CLI flag.
- Ensure the server uses the same EventStore and SubscriptionRegistry as the runner.

Testing:
- Add a small integration test that starts the server and runner together and sends a `swarm.emit` event from a mock client.

### 6) Update documentation
Implementation:
- Add a short section to `README.md` explaining how Neovim connects.
- Document the socket path and required RPC methods (link to `NVIM_DEMO_CONCEPT.md`).

Testing:
- `rg -n "nvim" README.md docs` to ensure the docs mention the new entry point.

## Testing additions (unit/smoke/examples)
Unit tests to add/update:
- `tests/unit/test_nvim_server.py::test_json_rpc_request_response` (new).
- `tests/unit/test_nvim_server.py::test_invalid_payload_returns_error` (new).
- `tests/unit/test_nvim_server.py::test_notification_does_not_require_id` (new).

Smoke tests to add/update:
- `tests/integration/test_nvim_server_smoke_real.py::test_server_accepts_client_and_replies` (new).
- `tests/integration/test_nvim_server_smoke_real.py::test_event_bus_notification_forwarded` (new).

Example tests to add:
- `tests/integration/test_nvim_server_smoke_real.py::test_agent_chat_emits_message_event` (new).
- `tests/integration/test_nvim_server_smoke_real.py::test_multiple_clients_receive_broadcast` (new).

## Notes
- Keep the server strictly JSON-RPC 2.0 compliant to make Neovim integration straightforward.
- Do not introduce UI-only event paths; everything should go through EventStore/EventBus.
