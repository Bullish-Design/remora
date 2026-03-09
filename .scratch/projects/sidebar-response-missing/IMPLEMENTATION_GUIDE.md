# Implementation Guide: Event Architecture Fix

## Table of Contents

1. **Overview** — full change set, why each step is needed, flow diagram
2. **Step 1: `AgentTextResponseEvent`** — replace stringly-typed `AgentEvent(event_type="AgentTextResponse")` with a dedicated typed class in `core/events/agent_events.py`
3. **Step 2: Export and register** — add to `CoreEvent` union and `__init__.py` exports
4. **Step 3: Schema** — add `agent_id` column + index to `events` table in `core/store/event_store_schema.py`
5. **Step 4: Store write** — extract and persist `agent_id` in `append()` and `batch_append()` in `core/store/event_store.py`
6. **Step 5: Query layer** — replace `fetch_recent_event_rows` with two intent-specific functions; fix `row_to_event_dict` to include `agent_id` at top level in `core/store/event_store_queries.py`
7. **Step 6: EventStore API** — rename `get_recent_events` → `get_agent_timeline` and add `get_routed_messages` in `core/store/event_store.py`
8. **Step 7: LSP notify** — include persisted `id` in `$/remora/event` notification in `lsp/server.py`
9. **Step 8: RunnerEventEmitter** — add typed `emit_agent_text_response()` method in `runner/event_emitter.py`
10. **Step 9: AgentRunner emit callsite** — replace generic `emit_agent_event("AgentTextResponse")` with new typed method in `runner/agent_runner.py`
11. **Step 10: AgentRunner chat history** — include `AgentTextResponse` events as assistant turns in `runner/agent_runner.py`
12. **Step 11: TurnContext chat history** — use `get_agent_timeline` and include `AgentTextResponse` as assistant turns in `core/agents/turn_context.py`
13. **Step 12: Panel command + hover callsites** — use `get_agent_timeline` in `lsp/handlers/commands.py` and `lsp/handlers/hover.py`
14. **Step 13: Bootstrap bedrock** — add `agent_id` field to `BootstrapEvent`; use `get_agent_timeline` in `bootstrap/bedrock.py`
15. **Step 14: Test updates** — update `test_event_store_queries.py` and `test_bedrock.py` to reflect renamed APIs and corrected semantics
16. **Step 15: New regression tests** — add regression tests covering the exact failure modes: panel-closed replay, live/replay `id` parity, chat history completeness

---

## 1. Overview

### The Problem in One Sentence

`AgentTextResponse` events are invisible to history queries because they identify their subject via `agent_id` in the JSON payload, but the query only looks at `from_agent`/`to_agent` DB columns — both of which are `NULL` for these events.

### What This Guide Fixes

| Problem | Root Cause | Fix |
|---|---|---|
| Panel shows no response after panel-closed run | `agent_id` not a DB column; query misses it | Add `agent_id` column; fix query |
| Replay events missing `agent_id` at top level | `row_to_event_dict` omits it | Include from new DB column |
| Live events missing `id` for deduplication | `emit_event` doesn't return/forward the DB id | Include `id` in LSP notify |
| `AgentTextResponse` not in chat history | Chat history loop never looks for it | Add case in both chat history paths |
| `AgentTextResponse` stringly typed | No dedicated class; `event_type` set as a string | Create `AgentTextResponseEvent` class |
| Bootstrap events invisible in agent timeline | `BootstrapEvent` has no `agent_id` field | Add `agent_id` to `BootstrapEvent` |
| `get_recent_events` overloaded for two intents | One API, two incompatible callers | Split into `get_agent_timeline` + `get_routed_messages` |

### Data Flow (Before and After)

**Before:**
```
AgentRunner
  → emit_agent_event(event_type="AgentTextResponse", agent_id="X")
  → AgentEvent(event_type="AgentTextResponse", agent_id="X")
  → EventStore.append()
       INSERT: from_agent=NULL, to_agent=NULL, payload={"event_type":"AgentTextResponse","agent_id":"X",...}
  → LSP notify: event.model_dump() [no id]
  → Panel history fetch: WHERE from_agent='X' OR to_agent='X' → 0 rows ← BUG
```

**After:**
```
AgentRunner
  → emit_agent_text_response(agent_id="X", content="...")
  → AgentTextResponseEvent(agent_id="X", ...)
  → EventStore.append()
       INSERT: agent_id="X", from_agent=NULL, to_agent=NULL, payload={"content":"..."}
       returns event_id=42
  → LSP notify: {**event.model_dump(), "id": 42}
  → Panel history fetch: WHERE agent_id='X' OR from_agent='X' OR to_agent='X' → correct rows ← FIXED
  → row_to_event_dict: includes agent_id="X" at top level ← FIXED
  → Chat history: AgentTextResponse → role="assistant" ← FIXED
```

### File Map

| File | Change |
|---|---|
| `core/events/agent_events.py` | Add `AgentTextResponseEvent` class |
| `core/events/__init__.py` | Export + add to `CoreEvent` union |
| `core/store/event_store_schema.py` | Add `agent_id` column + index + migration |
| `core/store/event_store.py` | Extract `agent_id` in write; split public API |
| `core/store/event_store_queries.py` | New query functions; fix `row_to_event_dict` |
| `lsp/server.py` | Include `id` in LSP notify |
| `runner/event_emitter.py` | Add `emit_agent_text_response` |
| `runner/agent_runner.py` | Use new emit; fix chat history |
| `core/agents/turn_context.py` | Use `get_agent_timeline`; fix chat history |
| `lsp/handlers/commands.py` | Use `get_agent_timeline` |
| `lsp/handlers/hover.py` | Use `get_agent_timeline` |
| `bootstrap/bedrock.py` | Add `agent_id` to `BootstrapEvent`; use `get_agent_timeline` |
| `tests/unit/test_event_store_queries.py` | Update + extend tests |
| `tests/unit/bootstrap/test_bedrock.py` | Update mock method name |

---

## 2. Step 1: `AgentTextResponseEvent`

**File:** `src/remora/core/events/agent_events.py`

### Why

`AgentEvent(event_type="AgentTextResponse", ...)` is stringly typed. The string `"AgentTextResponse"` is scattered across call sites, the type is invisible to static analysis, and crucially the class has no dedicated structure — making it easy for the DB write path to miss the identity information. A dedicated class makes the intent explicit, enables the `event_type` default to live in one place, and participates naturally in the typed event system.

### Design Decision: Inherit `_FrozenEvent`, Keep `payload` Sub-dict

`AgentTextResponseEvent` uses `payload: dict` (same as `AgentEvent`) to store `content`. This preserves `ev.payload.content` in panel.lua for **both** live and replay paths without any Lua changes:

- Live: `model_dump()` emits `{..., "payload": {"content": "..."}}` — Lua reads `ev.payload.content` ✓
- Replay: `row_to_event_dict` merges `payload` sub-dict into `nested_payload` — Lua reads `ev.payload.content` ✓

Setting `event_type: str = "AgentTextResponse"` (not `"AgentTextResponseEvent"`) preserves the existing panel.lua icon/highlight table keys without any Lua changes.

### The Class

Add after `AgentErrorEvent` and before `AgentEvent` in `agent_events.py`:

```python
class AgentTextResponseEvent(_FrozenEvent):
    """Final text response from an agent turn, displayed in the chat panel."""

    event_type: str = "AgentTextResponse"
    agent_id: str
    correlation_id: str
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
```

Update `__all__` to include `"AgentTextResponseEvent"`.

### Construction Convention

Callers construct this as:
```python
AgentTextResponseEvent(
    agent_id=agent_id,
    correlation_id=correlation_id,
    summary=response_text[:200],
    payload={"content": response_text},
)
```

The `payload` sub-dict is intentional: it mirrors the convention used by other `AgentEvent` subclasses (`HumanChatEvent.message` surfaces to panel via `ev.payload.message` after replay normalization) and avoids any Lua-side changes.

---

## 3. Step 2: Export and Register

**File:** `src/remora/core/events/__init__.py`

Add the import alongside the other `agent_events` imports:

```python
from remora.core.events.agent_events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentEvent,
    AgentStartEvent,
    AgentTextResponseEvent,   # NEW
    HumanChatEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    RewriteAppliedEvent,
    RewriteProposalEvent,
    RewriteRejectedEvent,
)
```

Add to the `CoreEvent` union type:

```python
CoreEvent = (
    AgentStartEvent
    | AgentCompleteEvent
    | AgentErrorEvent
    | AgentEvent
    | AgentTextResponseEvent   # NEW
    | HumanChatEvent
    | ...
)
```

Add `"AgentTextResponseEvent"` to `__all__`.

---

## 4. Step 3: Schema

**File:** `src/remora/core/store/event_store_schema.py`

### `create_tables`

Add `agent_id TEXT` column and its index to the `CREATE TABLE IF NOT EXISTS events` statement:

```sql
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    graph_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    timestamp REAL NOT NULL,
    created_at REAL NOT NULL,
    agent_id TEXT,          -- subject agent; NULL for pure routing events
    from_agent TEXT,
    to_agent TEXT,
    correlation_id TEXT,
    tags TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_agent_id
ON events(agent_id);
```

Place the new column between `created_at` and `from_agent` — order matters for readability but not correctness.

### `migrate`

Add to the `migrate()` function:

```python
if "agent_id" not in columns:
    conn.execute("ALTER TABLE events ADD COLUMN agent_id TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_agent_id ON events(agent_id)")
```

This runs automatically on startup via `EventStore._migrate_routing_fields()` and handles existing databases seamlessly. Existing rows will have `agent_id = NULL`; that's correct — the next append will populate it.

---

## 5. Step 4: Store Write

**File:** `src/remora/core/store/event_store.py`

Two places need updating: `append()` and `batch_append()`. The pattern is identical in both.

### `append()`

After the existing `correlation_id` extraction, add:

```python
agent_id = getattr(event, "agent_id", None)
```

Update the `INSERT` statement to include `agent_id`:

```sql
INSERT INTO events (graph_id, event_type, payload, timestamp, created_at, agent_id, from_agent, to_agent, correlation_id, tags)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

Pass `agent_id` as the sixth bind parameter.

### `batch_append()`

Apply the same extraction in the `prepared` list construction:

```python
agent_id = getattr(event, "agent_id", None)
prepared.append((event_type, payload, timestamp, created_at, agent_id, from_agent, to_agent, correlation_id, tags_json, event))
```

Update the `INSERT` to match, and unpack `agent_id` correctly in `_do_batch_append`.

### What Populates the Column

| Event type | `agent_id` column value |
|---|---|
| `AgentTextResponseEvent` | the responding agent |
| `AgentStartEvent` | the starting agent |
| `AgentCompleteEvent` | the completing agent |
| `AgentErrorEvent` | the failing agent |
| `AgentEvent` (generic) | whatever `agent_id` field is set |
| `AgentMessageEvent` | `None` (uses `from_agent`/`to_agent`) |
| `HumanChatEvent` | the target agent (copied from `to_agent`) |
| `BootstrapEvent` | set in Step 13 below |
| `NodeDiscoveredEvent` | `None` (node lifecycle, not agent) |

`AgentMessageEvent` intentionally leaves `agent_id = NULL`. Its routing is fully captured by `from_agent`/`to_agent`. The timeline query covers it via those columns.

---

## 6. Step 5: Query Layer

**File:** `src/remora/core/store/event_store_queries.py`

Three changes: replace `fetch_recent_event_rows`, add `fetch_routed_message_rows`, fix `row_to_event_dict`.

### Replace `fetch_recent_event_rows` with `fetch_agent_timeline_rows`

Delete `fetch_recent_event_rows` and replace with:

```python
def fetch_agent_timeline_rows(conn: sqlite3.Connection, *, agent_id: str, limit: int = 5) -> list[sqlite3.Row]:
    """All events where this agent is the subject, sender, or recipient."""
    query = """
        SELECT * FROM events
        WHERE agent_id = ? OR from_agent = ? OR to_agent = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
    """
    with contextlib.closing(conn.execute(query, (agent_id, agent_id, agent_id, limit))) as cursor:
        return cursor.fetchall()
```

### Add `fetch_routed_message_rows`

```python
def fetch_routed_message_rows(conn: sqlite3.Connection, *, agent_id: str, limit: int = 5) -> list[sqlite3.Row]:
    """Events where this agent is explicitly the sender or recipient (routing only)."""
    query = """
        SELECT * FROM events
        WHERE from_agent = ? OR to_agent = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
    """
    with contextlib.closing(conn.execute(query, (agent_id, agent_id, limit))) as cursor:
        return cursor.fetchall()
```

This is the old query, renamed and given an explicit intent. Used only by `turn_context` chat history (which only cares about routed message exchanges).

### Fix `row_to_event_dict`

Add `agent_id` to the returned dict, reading from the new DB column:

```python
return {
    "id": row["id"],
    "graph_id": row["graph_id"],
    "event_type": event_type,
    "agent_id": row["agent_id"],   # NEW — from DB column
    "payload": nested_payload,
    "summary": stored.get("summary", ""),
    "timestamp": row["timestamp"],
    "created_at": row["created_at"],
    "from_agent": row["from_agent"],
    "to_agent": row["to_agent"],
    "correlation_id": row["correlation_id"],
    "tags": tags,
}
```

**Why this matters for older rows:** For events written before this migration, `row["agent_id"]` will be `NULL` → `None`. That's correct — those events were routing events and the panel already reads `from_agent`/`to_agent` for them.

---

## 7. Step 6: EventStore API

**File:** `src/remora/core/store/event_store.py`

Rename `get_recent_events` → `get_agent_timeline` and add `get_routed_messages`. Both have identical async plumbing; only the underlying query function differs.

### `get_agent_timeline`

```python
async def get_agent_timeline(
    self,
    agent_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """All events where agent is subject, sender, or recipient. Newest first.

    Used by: panel history, hover, bootstrap event_read.
    """
    if self._read_conn is None:
        await self.initialize()
    if self._read_conn is None:
        raise RuntimeError("EventStore not initialized")

    async with self._read_lock:
        rows = await asyncio.to_thread(
            store_queries.fetch_agent_timeline_rows,
            self._read_conn,
            agent_id=agent_id,
            limit=limit,
        )

    return [self._row_to_dict(row) for row in rows]
```

### `get_routed_messages`

```python
async def get_routed_messages(
    self,
    agent_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Events where agent is explicitly sender or recipient. Newest first.

    Used by: turn_context chat history (routed message exchanges only).
    """
    if self._read_conn is None:
        await self.initialize()
    if self._read_conn is None:
        raise RuntimeError("EventStore not initialized")

    async with self._read_lock:
        rows = await asyncio.to_thread(
            store_queries.fetch_routed_message_rows,
            self._read_conn,
            agent_id=agent_id,
            limit=limit,
        )

    return [self._row_to_dict(row) for row in rows]
```

**Remove** `get_recent_events` entirely. There are no callers left after the steps below update all call sites.

---

## 8. Step 7: LSP Notify

**File:** `src/remora/lsp/server.py`

### Current `emit_event`

```python
async def emit_event(self, event) -> Any:
    if not getattr(event, "timestamp", None):
        ...
    if self.event_store:
        await self.event_store.append("swarm", event)
    self.protocol.notify("$/remora/event", event.model_dump())
    return event
```

### Updated `emit_event`

```python
async def emit_event(self, event) -> Any:
    if not getattr(event, "timestamp", None):
        if hasattr(event, "model_copy"):
            event = event.model_copy(update={"timestamp": time.time()})
        else:
            event.timestamp = time.time()

    event_id: int | None = None
    if self.event_store:
        event_id = await self.event_store.append("swarm", event)

    payload = event.model_dump()
    if event_id is not None:
        payload["id"] = event_id
    self.protocol.notify("$/remora/event", payload)
    return event
```

**Why:** The panel's `on_event` → merge logic deduplicates live events against replayed server events using `ev.id or ev.event_id`. Without `id`, live events cannot be deduplicated, causing the panel to show duplicates when re-fetching history after receiving live events. With `id` present on both sides, the merge in `do_fetch_agent_data` works correctly.

---

## 9. Step 8: RunnerEventEmitter

**File:** `src/remora/runner/event_emitter.py`

Add `AgentTextResponseEvent` import and a new method. No changes to existing methods.

```python
from remora.core.events.agent_events import (
    AgentEvent,
    AgentTextResponseEvent,   # NEW
    HumanChatEvent,
    RewriteProposalEvent,
    RewriteRejectedEvent,
)
```

Add method after `emit_agent_error`:

```python
async def emit_agent_text_response(
    self,
    *,
    agent_id: str,
    correlation_id: str,
    content: str,
    summary: str,
) -> None:
    """Emit a typed AgentTextResponseEvent directly via emit_event."""
    await self._server.emit_event(
        AgentTextResponseEvent(
            agent_id=agent_id,
            correlation_id=correlation_id,
            summary=summary,
            payload={"content": content},
        )
    )
```

**Note:** This method calls `self._server.emit_event()` directly — no `_call_server_method` indirection — because `emit_event` is on all server implementations and no server needs to intercept this at the method level. The `_HeadlessServer.emit_event` no-ops it (returns the event). `RemoraLanguageServer.emit_event` stores + notifies with `id`.

---

## 10. Step 9: AgentRunner Emit Callsite

**File:** `src/remora/runner/agent_runner.py` (around line 483)

### Before

```python
if result.response_text:
    await self._events.emit_agent_event(
        event_type="AgentTextResponse",
        agent_id=agent_id,
        correlation_id=correlation_id,
        summary=result.response_text[:200],
        payload={"content": result.response_text},
    )
```

### After

```python
if result.response_text:
    await self._events.emit_agent_text_response(
        agent_id=agent_id,
        correlation_id=correlation_id,
        content=result.response_text,
        summary=result.response_text[:200],
    )
```

That's the only change to the emit path. The `emit_agent_event` method remains on `RunnerEventEmitter` for the `ToolResultEvent` and `KernelEvent` string-typed calls at lines 404, 432, and 596.

---

## 11. Step 10: AgentRunner Chat History

**File:** `src/remora/runner/agent_runner.py` (around line 377)

The runner builds its turn-level chat history from `get_events_for_correlation`. This already finds `AgentTextResponseEvent` rows (correlation_id is indexed and populated). Only the loop needs a new case.

### Before

```python
for event in events:
    event_type = event["event_type"]
    payload = event.get("payload", {})
    to_agent = event.get("to_agent")
    from_agent = event.get("from_agent", "unknown")

    if event_type == "HumanChatEvent" and to_agent == agent_id:
        chat_history.append({"role": "user", "content": payload.get("message", "")})
    elif event_type == "AgentMessageEvent" and to_agent == agent_id:
        chat_history.append(
            {"role": "user", "content": f"[From {from_agent}]: {payload.get('message', '')}"}
        )
```

### After

```python
for event in events:
    event_type = event["event_type"]
    payload = event.get("payload", {})
    to_agent = event.get("to_agent")
    from_agent = event.get("from_agent", "unknown")

    if event_type == "HumanChatEvent" and to_agent == agent_id:
        chat_history.append({"role": "user", "content": payload.get("message", "")})
    elif event_type == "AgentMessageEvent" and to_agent == agent_id:
        chat_history.append(
            {"role": "user", "content": f"[From {from_agent}]: {payload.get('content', '')}"}
        )
    elif event_type == "AgentTextResponse" and event.get("agent_id") == agent_id:
        chat_history.append({"role": "assistant", "content": payload.get("content", "")})
```

**Note:** The `AgentMessageEvent` case also fixes a bug: the payload field for inter-agent message content is `content` (from `AgentMessageEvent.content`), not `message`. After `row_to_event_dict` processing, `content` lands in `nested_payload`. Using `payload.get("message", "")` would always return empty. This is silently broken today but doesn't matter since those events are in-flight; fixing it here as we touch this code.

---

## 12. Step 11: TurnContext Chat History

**File:** `src/remora/core/agents/turn_context.py`

### Change 1: Use `get_agent_timeline`

```python
# Before
recent_events = await event_store.get_recent_events(node.node_id, limit=config.chat_history_limit)

# After
recent_events = await event_store.get_agent_timeline(node.node_id, limit=config.chat_history_limit)
```

### Change 2: Add `AgentTextResponse` as assistant turn

```python
# Before
for ev in reversed(recent_events):
    payload = ev.get("payload", {})
    if ev.get("event_type") == "AgentMessageEvent":
        if ev.get("to_agent") == node.node_id:
            chat_history.append({"role": "user", "content": payload.get("content", "")})
        elif ev.get("from_agent") == node.node_id:
            chat_history.append({"role": "assistant", "content": payload.get("content", "")})

# After
for ev in reversed(recent_events):
    payload = ev.get("payload", {})
    event_type = ev.get("event_type")
    if event_type == "AgentMessageEvent":
        if ev.get("to_agent") == node.node_id:
            chat_history.append({"role": "user", "content": payload.get("content", "")})
        elif ev.get("from_agent") == node.node_id:
            chat_history.append({"role": "assistant", "content": payload.get("content", "")})
    elif event_type == "AgentTextResponse" and ev.get("agent_id") == node.node_id:
        chat_history.append({"role": "assistant", "content": payload.get("content", "")})
```

**Why `get_agent_timeline` instead of `get_routed_messages` here?** The `turn_context` fallback path (called when no pre-built chat history is provided) needs to reconstruct conversation context. `AgentTextResponse` IS the agent's response text — the assistant side of the conversation. Using `get_agent_timeline` makes this work. The `get_routed_messages` function is reserved for callers that exclusively want routed message exchanges (currently nothing, but available for future use).

---

## 13. Step 12: Panel Command + Hover

**File:** `src/remora/lsp/handlers/commands.py`

```python
# Before
events = await asyncio.wait_for(
    ls.event_store.get_recent_events(agent.node_id, limit=50),
    timeout=GET_PANEL_EVENTS_TIMEOUT_SECONDS,
)

# After
events = await asyncio.wait_for(
    ls.event_store.get_agent_timeline(agent.node_id, limit=50),
    timeout=GET_PANEL_EVENTS_TIMEOUT_SECONDS,
)
```

**File:** `src/remora/lsp/handlers/hover.py`

```python
# Before
events = await ls.event_store.get_recent_events(agent.node_id, limit=5)

# After
events = await ls.event_store.get_agent_timeline(agent.node_id, limit=5)
```

These are mechanical renames. No behavioral change beyond the broadened query semantics.

**Note on `agent_node.py:to_hover`:** The hover method reads `ev.get("payload", {}).get("summary", "")` to show a summary for each event. After this fix, `summary` is a top-level field on replayed events (it's in `row_to_event_dict`'s return dict directly), so `ev.get("payload", {}).get("summary", "")` would fail to find it — `summary` is not in `nested_payload`. But this was already broken before this fix (same issue existed). While not part of the core bug, fix this while touching `hover.py`:

```python
# In to_hover, when building event lines:
summary = ev.get("summary", "") or ev.get("payload", {}).get("summary", "")
```

Actually the fix belongs in `agent_node.py:to_hover`, line 204:
```python
# Before
summary = ev.get("payload", {}).get("summary", "")

# After
summary = ev.get("summary", "") or ev.get("payload", {}).get("summary", "")
```

---

## 14. Step 13: Bootstrap Bedrock

**File:** `src/remora/bootstrap/bedrock.py`

### Change 1: Add `agent_id` to `BootstrapEvent`

```python
class BootstrapEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    agent_id: str | None = None    # NEW: the writing agent's ID
    node_id: str | None = None     # target graph node (separate from agent)
    payload: dict[str, Any] = Field(default_factory=dict)
    from_agent: str | None = None
    to_agent: str | None = None
    correlation_id: str | None = None
    tags: tuple[str, ...] = ()
    timestamp: float = Field(default_factory=time.time)
```

### Change 2: Populate `agent_id` in `_event_write`

```python
async def _event_write(event_type: str, payload: dict[str, Any]) -> str:
    event = BootstrapEvent(
        event_type=event_type,
        agent_id=agent_id,              # NEW: writing agent
        node_id=payload.get("node_id"),
        payload=payload,
        from_agent=agent_id,
        to_agent=payload.get("to_agent"),
        correlation_id=payload.get("correlation_id"),
        tags=tuple(payload.get("tags", ())),
    )
    event_id = await event_store.append(swarm_id, event)
    return json.dumps({"event_id": event_id})
```

### Change 3: Use `get_agent_timeline`

```python
async def _event_read(selector: dict[str, Any]) -> str:
    target_agent = str(selector.get("agent_id") or selector.get("node_id") or agent_id)
    limit = int(selector.get("limit", 10))
    events = await event_store.get_agent_timeline(target_agent, limit=limit)
    return json.dumps(events)
```

**Why `get_agent_timeline` for bootstrap?** Bootstrap agents emit events about themselves and may also receive events from other agents. The full timeline (all events where agent is subject, sender, or recipient) is the correct view for a bootstrap agent querying "what has happened involving me or my targets."

---

## 15. Step 14: Test Updates

### `tests/unit/test_event_store_queries.py`

**Change 1:** Rename `TestGetRecentEvents` → `TestGetAgentTimeline`.

**Change 2:** Update all `get_recent_events(...)` calls → `get_agent_timeline(...)`.

**Change 3:** Reverse the assertion in `test_matches_events_without_routing_fields`. The old test explicitly asserted that `AgentStartEvent` does NOT appear in `get_recent_events`. This was correct for the old routing-only query. For `get_agent_timeline`, it MUST appear:

```python
@pytest.mark.asyncio
async def test_includes_agent_id_only_events(self, store: EventStore):
    """Events with agent_id but no from_agent/to_agent MUST appear in timeline."""
    event = AgentStartEvent(
        graph_id="swarm",
        agent_id="agent_a",
        node_name="test_node",
    )
    await store.append("swarm", event)

    results = await store.get_agent_timeline("agent_a", limit=10)
    assert len(results) == 1
    assert results[0]["event_type"] == "AgentStartEvent"
    assert results[0]["agent_id"] == "agent_a"
```

**Change 4:** Add `TestGetRoutedMessages` class that mirrors the old `TestGetRecentEvents` routing semantics:

```python
class TestGetRoutedMessages:
    @pytest.mark.asyncio
    async def test_excludes_agent_id_only_events(self, store: EventStore):
        """AgentStartEvent (agent_id only) must NOT appear in routed messages."""
        event = AgentStartEvent(graph_id="swarm", agent_id="agent_a", node_name="test_node")
        await store.append("swarm", event)

        results = await store.get_routed_messages("agent_a", limit=10)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_includes_from_agent_events(self, store: EventStore):
        event = AgentMessageEvent(from_agent="agent_a", to_agent="agent_b", content="hi")
        await store.append("swarm", event)

        results = await store.get_routed_messages("agent_a", limit=10)
        assert len(results) == 1
```

### `tests/unit/bootstrap/test_bedrock.py`

**Change 1:** Update the mock to use `get_agent_timeline` instead of `get_recent_events`:

```python
event_store.get_agent_timeline = AsyncMock(return_value=[{"id": 1, "event_type": "X"}])
# Remove: event_store.get_recent_events = AsyncMock(...)
```

**Change 2:** Update `test_event_read_calls_get_recent_events`:

```python
async def test_event_read_calls_get_agent_timeline(bedrock_deps) -> None:
    _, _, event_store = bedrock_deps
    bedrock = build_bedrock(
        agent_id="agent-1",
        cairn_externals=AsyncMock(),
        event_store=event_store,
        swarm_id="swarm",
    )

    payload = json.loads(await bedrock["_event_read"]({"limit": 3}))
    assert payload[0]["id"] == 1
    event_store.get_agent_timeline.assert_awaited_once_with("agent-1", limit=3)
```

**Change 3:** Update `test_event_write_appends_bootstrap_event` to also assert `agent_id` is set:

```python
assert emitted.agent_id == "agent-1"
assert emitted.from_agent == "agent-1"
```

---

## 16. Step 15: New Regression Tests

Add a new file `tests/unit/test_event_store_regression.py` (or extend the queries test file). These tests encode the exact failure modes from the investigation.

```python
"""Regression tests for sidebar-response-missing bug and related invariants."""

from __future__ import annotations

from pathlib import Path
import pytest

from remora.core.store.event_store import EventStore
from remora.core.events.agent_events import AgentTextResponseEvent, AgentStartEvent
from remora.core.events.interaction_events import AgentMessageEvent


@pytest.fixture
async def store(tmp_path: Path) -> EventStore:
    es = EventStore(tmp_path / "events.db")
    await es.initialize()
    yield es
    await es.close()


class TestPanelClosedReplay:
    """Regression: panel closed during run, later open shows AgentTextResponse."""

    @pytest.mark.asyncio
    async def test_agent_text_response_visible_in_timeline(self, store: EventStore):
        """AgentTextResponseEvent must appear in get_agent_timeline for the agent."""
        event = AgentTextResponseEvent(
            agent_id="agent_x",
            correlation_id="corr_1",
            summary="Answer to question",
            payload={"content": "Here is the answer."},
        )
        await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_x", limit=10)
        assert len(results) == 1
        assert results[0]["event_type"] == "AgentTextResponse"
        assert results[0]["agent_id"] == "agent_x"
        assert results[0]["payload"]["content"] == "Here is the answer."

    @pytest.mark.asyncio
    async def test_agent_text_response_not_in_routed_messages(self, store: EventStore):
        """AgentTextResponseEvent must NOT appear in get_routed_messages (no routing fields)."""
        event = AgentTextResponseEvent(
            agent_id="agent_x",
            correlation_id="corr_1",
            summary="Answer",
            payload={"content": "text"},
        )
        await store.append("swarm", event)

        results = await store.get_routed_messages("agent_x", limit=10)
        assert len(results) == 0


class TestLiveReplayEnvelopeParity:
    """Invariant: live and replayed events have the same top-level fields."""

    @pytest.mark.asyncio
    async def test_replayed_event_has_agent_id_at_top_level(self, store: EventStore):
        """row_to_event_dict must include agent_id at top level."""
        event = AgentTextResponseEvent(
            agent_id="agent_y",
            correlation_id="corr_2",
            payload={"content": "response"},
        )
        await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_y", limit=1)
        assert "agent_id" in results[0]
        assert results[0]["agent_id"] == "agent_y"

    @pytest.mark.asyncio
    async def test_replayed_event_has_stable_id(self, store: EventStore):
        """Replayed events must have a non-None integer id."""
        event = AgentMessageEvent(from_agent="a", to_agent="b", content="hi", correlation_id="c1")
        await store.append("swarm", event)

        results = await store.get_agent_timeline("a", limit=1)
        assert results[0]["id"] is not None
        assert isinstance(results[0]["id"], int)


class TestChatHistoryCompleteness:
    """Invariant: agent responses appear in correlation-scoped history."""

    @pytest.mark.asyncio
    async def test_text_response_retrievable_by_correlation(self, store: EventStore):
        """AgentTextResponseEvent must be findable via get_events_for_correlation."""
        event = AgentTextResponseEvent(
            agent_id="agent_z",
            correlation_id="corr_session_1",
            payload={"content": "I can help with that."},
        )
        await store.append("swarm", event)

        results = await store.get_events_for_correlation("corr_session_1")
        assert len(results) == 1
        assert results[0]["event_type"] == "AgentTextResponse"
        assert results[0]["payload"]["content"] == "I can help with that."

    @pytest.mark.asyncio
    async def test_full_conversation_round_trip(self, store: EventStore):
        """Human message + agent response both visible in timeline and correlation history."""
        from remora.core.events.agent_events import HumanChatEvent

        human_msg = HumanChatEvent(
            agent_id="agent_z",
            to_agent="agent_z",
            message="What can you do?",
            correlation_id="corr_rt_1",
        )
        agent_resp = AgentTextResponseEvent(
            agent_id="agent_z",
            correlation_id="corr_rt_1",
            payload={"content": "Many things."},
            summary="Many things.",
        )
        await store.append("swarm", human_msg)
        await store.append("swarm", agent_resp)

        timeline = await store.get_agent_timeline("agent_z", limit=10)
        assert len(timeline) == 2
        event_types = {ev["event_type"] for ev in timeline}
        assert "HumanChatEvent" in event_types
        assert "AgentTextResponse" in event_types

        corr = await store.get_events_for_correlation("corr_rt_1")
        assert len(corr) == 2
```

---

## Execution Order and Dependencies

Implement in this exact order. Each step is independently testable after completion.

```
Step 1  → Step 2  (new class must exist before export)
Step 3  → Step 4  (schema must exist before write path)
Step 5  → Step 6  (query functions must exist before EventStore API)
Step 6  → Steps 12, 13, 14  (EventStore API must exist before callsites)
Step 8  → Step 9  (emitter method must exist before runner callsite)
Step 1  → Step 8  (AgentTextResponseEvent must exist before emitter imports it)
Step 14 → Step 15 (test updates run before regression tests, both in same run)
```

Run tests after each step:
```bash
devenv shell -- pytest tests/unit/test_event_store_queries.py -v   # after steps 3-6
devenv shell -- pytest tests/unit/bootstrap/test_bedrock.py -v     # after step 13
devenv shell -- pytest tests/unit/test_event_store_regression.py -v  # after step 15
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q  # full suite
```

