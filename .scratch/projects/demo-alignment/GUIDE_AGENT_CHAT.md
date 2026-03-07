# Agent Chat Service — Refactoring Guide

**Area:** `src/remora/service/chat_service.py`
**Priority:** 1 (quickest wins, production code)

---

## Overview

`chat_service.py` is a Starlette-based HTTP service that wraps `ChatSession` with a REST API. It is used as the demo's agent chat interface — clients create sessions, send messages, stream tool events via SSE, and get conversation history.

This module lives in production `src/remora/service/` rather than `remora_demo/` — it is demo-oriented but in the production tree.

The event import paths are already correct (using `kernel_events`). The main issues are structural.

---

## Module-Level Singleton Anti-Pattern (High)

### Problem

```python
# chat_service.py
state = ChatServiceState()   # ← module-level singleton
...
app = create_app()           # ← also module-level, wires routes to `state` global
```

This pattern means:
1. Any `import remora.service.chat_service` creates a live `ChatServiceState` object.
2. Tests that import this module share state with each other unless they explicitly reset it.
3. `create_app()` inside the module uses `globals()["state"]` to fall back to the module-level singleton when no explicit state is passed — a hidden coupling.

```python
def create_app(state: ChatServiceState | None = None) -> Starlette:
    chat_state = state if state is not None else globals()["state"]  # ← fragile
```

### Fix

Remove the module-level `state` and `app` singletons. Callers should always provide state:

```python
# Remove:
# state = ChatServiceState()
# app = create_app()

# All callers must do:
state = ChatServiceState()
app = create_app(state)
```

Update `create_app()` to remove the `globals()` fallback:

```python
def create_app(state: ChatServiceState) -> Starlette:
    """Create the chat service app. Caller is responsible for providing state."""
    ...
    # Use `state` directly — no fallback to globals
```

Update `if __name__ == "__main__":` block:

```python
if __name__ == "__main__":
    import uvicorn
    _state = ChatServiceState()
    _app = create_app(_state)
    uvicorn.run(_app, host="127.0.0.1", port=8420)
```

---

## Route Handler Closure Gap (Medium)

### Problem

The route handlers (`create_session`, `send_message`, etc.) are module-level functions that reference the module-level `state` object as a free variable. When `create_app(state)` is called with an explicit state, the route handlers still capture the module-level `state`, not the injected one.

This means the DI pattern in `create_app` is incomplete — the `application.state.chat_state` attribute is set but unused by the handlers.

### Fix

Convert route handlers to closures that capture the provided `state`:

```python
def create_app(state: ChatServiceState) -> Starlette:
    async def create_session(request: Request) -> JSONResponse:
        # Use `state` from closure, not module global
        ...

    async def send_message(request: Request) -> JSONResponse:
        ...

    routes = [
        Route("/sessions", create_session, methods=["POST"]),
        ...
    ]
    return Starlette(routes=routes, lifespan=lifespan)
```

Alternatively, inject state via `request.app.state.chat_state` (Starlette's official pattern):

```python
async def create_session(request: Request) -> JSONResponse:
    chat_state: ChatServiceState = request.app.state.chat_state
    ...
```

The closure approach is simpler for this service's size.

---

## `cairn` Import Coupling in Lifespan (Low)

### Problem

```python
@asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    try:
        import cairn
        logger.info("cairn %s: OK", ...)
    except ImportError as e:
        logger.error(f"cairn not available: {e}")
    yield
```

The lifespan logs whether `cairn` is available but does nothing with the result — it doesn't fail startup or configure the session differently. This is dead diagnostics code that should either:
- Be removed (if cairn is always available in this environment)
- Actually gate `ChatSession.create()` (if cairn is required)

The `ChatSession` likely requires cairn internally. If so, the import error should surface at session creation time, not silently at startup.

### Fix

Remove the cairn import check from lifespan, or replace with a meaningful health-check that actually verifies cairn compatibility.

---

## Session Lifecycle: Missing `close()` on Server Shutdown (Low)

### Problem

`ChatServiceState` holds open `ChatSession` objects. If the server receives SIGTERM during a running demo, those sessions are never closed. `ChatSession.close()` likely does important cleanup (closes LLM connections, etc.).

### Fix

Add a shutdown handler in the lifespan:

```python
@asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    yield
    # Cleanup on shutdown
    for session in list(state.sessions.values()):
        try:
            await session.close()
        except Exception:
            pass
    state.sessions.clear()
    state.event_buses.clear()
```

---

## Event Imports (Already Correct)

```python
from remora.core.events.event_bus import EventBus
from remora.core.events.kernel_events import ToolCallEvent, ToolResultEvent
```

These are correct post-W4 bounded-module imports. No change needed.

---

## `DEFAULT_CHAT_TOOL_NAMES` Alignment

The list of default tool names:
```python
DEFAULT_CHAT_TOOL_NAMES = [
    "read_file", "write_file", "list_dir",
    "file_exists", "search_files", "discover_symbols",
]
```

These are chat-mode tools (file ops), not LSP swarm tools. They are configured via `ChatConfig.tool_presets`. Verify these tool names still match what `ChatSession` exposes. If `ChatSession` was updated to reflect new tool names during the architecture refactor, update this list.

---

## Summary of Changes

| Issue | Priority | Work |
|-------|----------|------|
| Remove module-level `state` and `app` singletons | High | Delete 2 lines, update callers |
| Fix `create_app` globals fallback | High | Remove `globals()` pattern, make `state` required param |
| Convert handlers to closures or use `request.app.state` | Medium | Refactor handler functions |
| Remove/fix cairn lifespan diagnostic | Low | Delete or make meaningful |
| Add session cleanup on server shutdown | Low | Add lifespan teardown |
| Verify `DEFAULT_CHAT_TOOL_NAMES` against `ChatSession` | Low | Cross-check |

---

## Verification

After changes:
```bash
devenv shell -- python -c "from remora.service.chat_service import create_app, ChatServiceState; app = create_app(ChatServiceState()); print('OK')"
devenv shell -- python -m pytest tests/ -k "chat_service" -v
devenv shell -- tach check
```

Ensure that importing `remora.service.chat_service` no longer creates any live objects as a side-effect.
