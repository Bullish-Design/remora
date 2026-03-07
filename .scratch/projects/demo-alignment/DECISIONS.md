# Decisions

## D1: Fix `AgentMessageEvent` at the server level, not panel.lua

**Decision:** The fix for panel.lua's `AgentMessageEvent` rendering bugs should be made in `server.py`'s `emit_agent_message_event()`, not in panel.lua.

**Rationale:** `AgentMessageEvent` is a domain event model that doesn't need modification. The issue is that `server.emit_agent_message_event()` sends `model_dump()` of a model that lacks `event_type`. The server is the right place to wrap or transform before notifying — it's an adapter-layer concern. Panel.lua should receive a consistent wire format, not branch on missing fields.

**Concrete fix:** Change `emit_agent_message_event()` to notify via an `AgentEvent` envelope, OR use `model_dump(mode="json")` with an added `event_type`. See GUIDE_NEOVIM.md.

**Exception:** The `ev.from_agent`/`ev.to_agent` direction fix in panel.lua (Bug 2) IS a panel.lua fix since both live and historical formats have these at top level, not in payload.

## D2: Fix `state.py` schema using SQL aliases, not new model classes

**Decision:** Fix the stale column name queries in `state.py` using SQL column aliases (`id AS event_id`, `from_agent AS agent_id`) so that the rest of `state.py`'s Python code that references `row["event_id"]` and `row["agent_id"]` doesn't need to change.

**Rationale:** Minimizes blast radius. The goal is to unbreak the SQL, not refactor the entire GraphState API.

**Note:** The `nodes.id` → `nodes.node_id` fix must also rename the key in Python code from `n["id"]` to `n["node_id"]`, since the rename target should match production (use `node_id`).

## D3: Don't merge companion events into core

**Decision:** The companion's dataclass event system is kept separate from `remora.core.events.*`.

**Rationale:** Different semantics (`CursorMoved` is high-frequency raw, `CursorFocusEvent` is debounced). Different representation (dataclasses vs Pydantic). The companion is a distinct product that happens to share an LSP server pattern. Merging them would violate YAGNI and pollute the core with companion-specific concerns.
