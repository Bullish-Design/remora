# FINAL_UPDATES — Root Cause Analysis & Fixes

## Executive Summary

Three acceptance tests fail (scenarios 1, 2, 4) with **zero operations** in their results, despite 19 nodes being discovered. The vLLM logs confirm that subagent definitions load successfully (`grail_check` events fire), but **no `model_request` events appear** — meaning `runner.run()` is never reached or its errors are silently swallowed. Additionally, the codebase has **zero LLM input/output logging** despite importing a logger.

---

## Issue 1: Silent Error Swallowing in `orchestrator.py`

### Symptom

All `NodeResult` objects come back with `operations={}` and `errors=[]` — both empty. This is paradoxical: if the runner succeeded, `operations` should be populated; if it failed, `errors` should contain error info.

### Root Cause

In [`orchestrator.py` lines 327-330](file:///c:/Users/Andrew/Documents/Projects/remora/remora/orchestrator.py#L327-L330):

```python
for item in raw:
    if isinstance(item, BaseException):
        # Task-level exception (e.g. CancelledError from shutdown)
        continue
    operation, outcome = item
```

When `asyncio.gather(*tasks, return_exceptions=True)` catches an exception, it returns it as a bare item in the list. The check `isinstance(item, BaseException)` is intended to catch only `CancelledError` from shutdowns, but **`Exception` is a subclass of `BaseException`**, so ALL exceptions hit this branch — including `ConnectionError`, `OSError` from `Fsdantic.open()`, `TypeError`, `AttributeError`, etc.

Meanwhile, the inner `run_with_limit` function (lines 258-313) only catches `AgentError`:

```python
try:
    result = await runner.run()
    ctx.transition(RemoraAgentState.COMPLETED)
    return operation, result
except AgentError as exc:
    # ... wraps and returns (operation, exc)
    return operation, exc
```

Any non-`AgentError` exception (e.g., from workspace setup on lines 268-281, or from the HTTP client) **propagates out of `run_with_limit`**, becomes a bare exception in `asyncio.gather`, and is **silently discarded** by the `isinstance(item, BaseException): continue` check.

The result: `operations` is empty, `errors` is empty, and there is no indication anything went wrong.

### Fix

```diff
 for item in raw:
-    if isinstance(item, BaseException):
-        # Task-level exception (e.g. CancelledError from shutdown)
-        continue
+    if isinstance(item, BaseException):
+        if isinstance(item, asyncio.CancelledError):
+            # Genuine shutdown cancellation — skip silently
+            continue
+        # Unexpected exception that escaped run_with_limit
+        logger.error(
+            "Unhandled exception in run_with_limit: %s",
+            item,
+            exc_info=item,
+        )
+        errors.append({
+            "operation": "unknown",
+            "phase": "run",
+            "error": str(item),
+        })
+        continue
     operation, outcome = item
```

Additionally, broaden the catch in `run_with_limit` to catch `Exception` (not just `AgentError`):

```diff
-            except AgentError as exc:
+            except Exception as exc:
                 ctx.transition(RemoraAgentState.ERRORED)
-                raw_phase = exc.phase if isinstance(exc, AgentError) else "run"
+                raw_phase = getattr(exc, "phase", "run")
                 phase, step = _normalize_phase(raw_phase)
-                error_code = exc.error_code if isinstance(exc, AgentError) else None
+                error_code = getattr(exc, "error_code", None)
```

---

## Issue 2: What Exception Is Being Swallowed?

### Most Likely: Workspace Setup Failure

Inside `run_with_limit` (lines 267-281), before `runner.run()` is ever called:

```python
async with self._queue.acquire(priority=priority):
    cache_root = self.config.cairn.home or (Path.home() / ".cache" / "remora")
    workspace_path = cache_root / "workspaces" / ctx.agent_id
    workspace_path.mkdir(parents=True, exist_ok=True)

    runner.workspace_root = workspace_path
    runner.stable_root = Path.cwd()

    cache_key = ctx.agent_id
    ws = self._workspace_cache.get(cache_key)
    if ws is None:
        ws = await Fsdantic.open(str(workspace_path))
        self._workspace_cache.put(cache_key, ws)
```

`Fsdantic.open()` or `WorkspaceCache.put()` could throw if:

- The filesystem path has permission issues
- `Fsdantic` has initialization requirements not met
- `WorkspaceCache` is full or encounters a key conflict

### Second Possibility: `TaskQueue.acquire()` Error

If `cairn.orchestrator.queue.TaskQueue` requires initialization that hasn't happened (e.g., `max_queue_size=100` might need async setup), then `self._queue.acquire(priority=priority)` could throw before any runner work begins.

### How To Diagnose

**Immediately actionable**: Add `except Exception` around the workspace setup before `runner.run()`:

```python
async def run_with_limit(...):
    try:
        async with self._queue.acquire(priority=priority):
            # ... workspace setup ...
            ctx.transition(RemoraAgentState.EXECUTING)
            try:
                result = await runner.run()
                ...
            except Exception as exc:
                ...
    except Exception as setup_exc:
        logger.error("Workspace setup failed for %s: %s", ctx.agent_id, setup_exc, exc_info=True)
        ctx.transition(RemoraAgentState.ERRORED)
        return operation, setup_exc
```

### Temporary Debugging

To immediately surface the swallowed error, add this to the gather result processing:

```python
for item in raw:
    if isinstance(item, BaseException):
        print(f"!!! SWALLOWED EXCEPTION: {type(item).__name__}: {item}", flush=True)
        import traceback
        traceback.print_exception(type(item), item, item.__traceback__)
        continue
```

Run the tests with this patch and the actual exception type and traceback will be visible.

---

## Issue 3: No LLM Input/Output Logging

### Current State

- `runner.py` line 29: `logger = logging.getLogger(__name__)` — **imported but never used**
- `orchestrator.py` line 24: `logger = logging.getLogger(__name__)` — only used in `_request_shutdown`
- All current "logging" goes through the `EventEmitter` (JSONL structured events), which is great for machine consumption but unusable for human debugging
- The event stream is **disabled by default** (`EventStreamConfig.enabled: bool = False`)
- Even when enabled, the JSONL format mixes LLM payloads into dense single-line JSON — unreadable

### What Exists

The runner already emits these events with full payloads when `include_payloads=True`:

| Event | Data | Where |
|-------|------|-------|
| `model_request` | messages array, prompt chars | `_call_model` line 178 |
| `model_request_debug` | full request payload (messages, tools, tool_choice) | `_emit_request_debug` line 311 |
| `model_tools_before/after` | tools array, tool_choice | `_emit_tool_debug` line 290 |
| `model_response` | response text, token usage, duration | `_emit_model_response` line 380 |
| `tool_call` | tool name | `_dispatch_tool` line 502 |
| `tool_result` | tool output | `_emit_tool_result` line 417 |
| `submit_result` | final status | `_build_submit_result` line 477 |

The data is there — it just needs a human-readable output channel.

---

## Implementation Plan: LLM Readable Logging

### Goal

Create a separate, human-readable log file that captures the full LLM conversation flow in a format like:

```
═══════════════════════════════════════════════════════
AGENT: lint-aa772d716f363c8b | Operation: lint
Node: calculator | File: src/calculator.py
═══════════════════════════════════════════════════════

── Turn 1 (model_load) ───────────────────────────────

→ SYSTEM PROMPT:
  You are a Python linting agent. Analyze the code...

→ USER MESSAGE:
  Please lint the following function:
  ```python
  def calculate_discount(price, discount):
      return price - price * discount
  ```

← MODEL RESPONSE (1247ms, 312 tokens):
  I'll run the linter on this code first.

← TOOL CALLS:
  1. run_linter(target_file="src/calculator.py")
     → Result: {"issues": [...]}

── Turn 2 (loop) ─────────────────────────────────────

← MODEL RESPONSE (892ms, 156 tokens):
  Found 2 issues. Applying fixes...

← TOOL CALLS:
  1. apply_fix(file="src/calculator.py", line=1, ...)
     → Result: {"applied": true}
  2. submit_result(status="success", ...)

═══════════════════════════════════════════════════════
RESULT: success | Duration: 2139ms | Tokens: 468
═══════════════════════════════════════════════════════
```

### Implementation: New `LlmConversationLogger` Class

#### [NEW] `remora/llm_logger.py`

A new module that hooks into the existing event emitter infrastructure:

```python
"""Human-readable LLM conversation logger."""

from __future__ import annotations

import logging
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)


class LlmConversationLogger:
    """Writes human-readable LLM conversation transcripts.
    
    Hooks into the existing EventEmitter system and reformats
    structured events into readable conversation logs.
    """

    def __init__(
        self,
        output: Path | TextIO | None = None,
        *,
        include_full_prompts: bool = True,
        max_content_lines: int = 100,
    ) -> None:
        self._output = output
        self._include_full_prompts = include_full_prompts
        self._max_content_lines = max_content_lines
        self._stream: TextIO | None = None
        self._current_agent: str | None = None
    
    def open(self) -> None:
        if isinstance(self._output, Path):
            self._output.parent.mkdir(parents=True, exist_ok=True)
            self._stream = self._output.open("a", encoding="utf-8")
        elif hasattr(self._output, "write"):
            self._stream = self._output
    
    def close(self) -> None:
        if self._stream and isinstance(self._output, Path):
            self._stream.close()
    
    def handle_event(self, payload: dict[str, Any]) -> None:
        """Route an event payload to the appropriate formatter."""
        event = payload.get("event", "")
        handler = getattr(self, f"_handle_{event}", None)
        if handler:
            handler(payload)
    
    def _write(self, text: str) -> None:
        if self._stream:
            self._stream.write(text + "\n")
            self._stream.flush()
    
    def _handle_model_request(self, p: dict) -> None:
        agent_id = p.get("agent_id", "?")
        if agent_id != self._current_agent:
            self._current_agent = agent_id
            self._write_agent_header(p)
        
        phase = p.get("step", p.get("phase", "?"))
        self._write(f"\n── Turn ({phase}) {'─' * 40}")
        
        # Write messages if included
        messages = p.get("messages")
        if messages and isinstance(messages, list):
            for msg in messages:
                role = msg.get("role", "?").upper()
                content = msg.get("content", "")
                self._write(f"\n→ {role}:")
                self._write(textwrap.indent(str(content)[:2000], "  "))
    
    def _handle_model_response(self, p: dict) -> None:
        status = p.get("status", "?")
        duration = p.get("duration_ms", "?")
        tokens = p.get("total_tokens", "?")
        response = p.get("response_text", "")
        
        self._write(f"\n← MODEL RESPONSE ({duration}ms, {tokens} tokens) [{status}]:")
        if response:
            self._write(textwrap.indent(str(response)[:2000], "  "))
        
        if p.get("error"):
            self._write(f"  ERROR: {p['error']}")
    
    def _handle_tool_call(self, p: dict) -> None:
        tool = p.get("tool_name", "?")
        self._write(f"\n  ⚙ TOOL CALL: {tool}")
    
    def _handle_tool_result(self, p: dict) -> None:
        tool = p.get("tool_name", "?")
        status = p.get("status", "?")
        output = p.get("tool_output", "")
        self._write(f"    → {tool} [{status}]")
        if output:
            self._write(textwrap.indent(str(output)[:1000], "      "))
    
    def _handle_submit_result(self, p: dict) -> None:
        status = p.get("status", "?")
        agent_id = p.get("agent_id", "?")
        self._write(f"\n{'═' * 60}")
        self._write(f"RESULT: {status} | Agent: {agent_id}")
        self._write(f"{'═' * 60}\n")
        self._current_agent = None
    
    def _handle_agent_error(self, p: dict) -> None:
        self._write(f"\n{'!' * 60}")
        self._write(f"AGENT ERROR: {p.get('error', '?')}")
        self._write(f"  Agent: {p.get('agent_id')} | Phase: {p.get('phase')}")
        if p.get("error_code"):
            self._write(f"  Code: {p['error_code']}")
        self._write(f"{'!' * 60}\n")
    
    def _write_agent_header(self, p: dict) -> None:
        self._write(f"\n{'═' * 60}")
        self._write(f"AGENT: {p.get('agent_id', '?')} | Op: {p.get('operation', '?')}")
        self._write(f"Model: {p.get('model', '?')}")
        self._write(f"Time: {datetime.now(timezone.utc).isoformat()}")
        self._write(f"{'═' * 60}")
```

#### [MODIFY] `remora/events.py` — Add Composite Emitter

Add a `CompositeEventEmitter` that can fan out to both the JSONL emitter and the conversation logger:

```python
@dataclass
class CompositeEventEmitter:
    """Fans out events to multiple emitters."""
    emitters: list[EventEmitter]
    enabled: bool = True
    include_payloads: bool = True
    max_payload_chars: int = 4000

    def emit(self, payload: dict[str, Any]) -> None:
        for emitter in self.emitters:
            emitter.emit(payload)

    def close(self) -> None:
        for emitter in self.emitters:
            emitter.close()
```

#### [MODIFY] `remora/config.py` — Add LLM Log Config

```python
class LlmLogConfig(BaseModel):
    enabled: bool = False
    output: Path | None = None  # defaults to .remora_cache/llm_conversations.log
    include_full_prompts: bool = True
    max_content_lines: int = 100
```

#### [MODIFY] `remora/orchestrator.py` — Wire It Up

In `Coordinator.__init__`, if `config.llm_log.enabled`, create the `LlmConversationLogger` and wrap the event emitter in a `CompositeEventEmitter`.

### Config Example

```yaml
# remora.yaml
event_stream:
  enabled: true
  output: .remora_cache/events.jsonl
  include_payloads: true

llm_log:
  enabled: true
  output: .remora_cache/llm_conversations.log
  include_full_prompts: true
```

---

## Issue 4: `runner.py` Logger Is Unused

### Current State

```python
# runner.py line 29
logger = logging.getLogger(__name__)
# ... never called anywhere in the file
```

### Fix

Add `logger.debug()` / `logger.info()` calls at key points in the runner:

```python
# In __post_init__:
logger.info("Runner initialized for %s (model=%s, turns=%d)",
            self.workspace_id, self._model_target, self.definition.max_turns)

# In _call_model before the HTTP call:
logger.debug("Calling model %s (phase=%s, turn=%d, messages=%d)",
             self._model_target, phase, self.turn_count, len(self.messages))

# In _call_model after response:
logger.debug("Model response (phase=%s, request_id=%s, tool_calls=%d)",
             phase, request_id, len(message.tool_calls or []))

# In _dispatch_tool:
logger.debug("Dispatching tool %s for %s", tool_name, self.workspace_id)

# In _build_submit_result:
logger.info("Agent %s submitted result: status=%s", self.workspace_id, result.status)
```

---

## Summary of All Changes

| File | Change | Priority |
|------|--------|----------|
| `orchestrator.py` L288 | Catch `Exception` not just `AgentError` in `run_with_limit` | **Critical** |
| `orchestrator.py` L328 | Only swallow `CancelledError`, log + record all others | **Critical** |
| `orchestrator.py` | Add workspace setup error logging | **High** |
| `runner.py` | Add `logger.debug/info` calls at key points | **High** |
| `llm_logger.py` [NEW] | Human-readable LLM conversation log formatter | **Medium** |
| `events.py` | Add `CompositeEventEmitter` for multi-output | **Medium** |
| `config.py` | Add `LlmLogConfig` model | **Medium** |
| `orchestrator.py` | Wire `LlmConversationLogger` into Coordinator | **Medium** |

### Verification

After applying the **Critical** fixes:

1. Re-run `pytest -s -vv` — the acceptance tests should either:
   - **Pass** (if the swallowed exception was transient/environmental)
   - **Fail with visible error messages** showing the actual root cause
2. Check the vLLM logs for `model_request` events (should now appear)
3. Check for `agent_error` events with tracebacks

### Immediate Next Step

Before implementing any LLM logging, apply the **temporary debugging patch** (Issue 2) to print the swallowed exception. This will reveal the actual error being hidden and determine whether any of the workspace setup code needs fixing too.
