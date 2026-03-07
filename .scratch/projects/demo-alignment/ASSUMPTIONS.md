# Assumptions

## Project Audience

These guides are for developers working on the Remora project — specifically:
- Making the Neovim agent panel fully functional for real-world use
- Making the web graph viewer production-ready
- Making the agent chat service properly testable
- Understanding the companion as a standalone product demo

## What "Demo" Means

The user clarified: these are NOT "demo harnesses" but **demonstrations of actual functionality** — standalone applications that integrate with the real remora library. They must be:
- Fully functional (work in a live session with the LSP server running)
- Fully aligned with the latest architecture refactors (bounded events, runner.models, etc.)
- Using remora's provided functionality, not reimplementing their own versions

## Architecture Contract (Post-Refactor)

These are invariants confirmed from reading the production code:

### Event Wire Protocol

**Live events** (`$/remora/event`):
- Events that extend `AgentEvent` (HumanChatEvent, RewriteProposalEvent, etc.) have: `event_type`, `agent_id`, `summary`, `payload={...}`, `timestamp` at top level
- Events that extend `_FrozenEvent` directly (AgentMessageEvent) have their own fields at top level with NO `event_type`, `agent_id`, or `payload` wrapper

**Historical events** (via `remora.getAgentPanel` → `row_to_event_dict()`):
- Always have: `id` (INTEGER), `event_type`, `from_agent`, `to_agent`, `summary`, `payload={nested model fields}`, `timestamp`
- `from_agent`/`to_agent` are at top level (not in payload)
- Non-meta model fields (like `content`, `message`, `diff`) are in `payload`

### Event Store Schema (Current)

```sql
events: id INTEGER PK, graph_id, event_type, payload TEXT, timestamp, created_at, from_agent, to_agent, correlation_id, tags
nodes:  node_id TEXT PK, node_type, name, full_name, file_path, start_line, end_line, source_code, source_hash, parent_id, status DEFAULT 'idle', ...
```

NOT `event_id`, NOT `agent_id`, NOT `nodes.id` (all these are OLD schema).

### `AgentMessageEvent` Has No `event_type` Field

`AgentMessageEvent` extends `_FrozenEvent` (not `AgentEvent`). Its `model_dump()` produces `{from_agent, to_agent, content, tags, correlation_id, timestamp}` — no `event_type` field and no `payload` dict.

### `_emit_tool_event` Adds `result_summary` to Payload

In `agent_runner.py`, the `_emit_tool_event` callback does:
```python
payload["result_summary"] = result_summary
await self._events.emit_agent_event(event_type="ToolResultEvent", ..., payload=payload)
```
So `ev.payload.result_summary` in panel.lua IS correctly populated. This is not a bug.

### Layer Rule

`core → runner → adapters (lsp, service, companion, ui, cli) → utils`
Dependencies must flow inward only. tach check enforces this.

## Companion Separation

The companion is intentionally a separate product with its own event system, workspace abstraction, and LSP server. The event separation (dataclasses vs Pydantic, raw cursor events vs debounced focus events) is not a bug — it's a deliberate design choice. Guides should document WHY, not try to merge them.
