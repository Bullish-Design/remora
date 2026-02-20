# vLLM Server-Side Logging Guide

This guide provides implementation steps to add comprehensive server-side logging to capture the "true" inputs and outputs at the vLLM layer before and after any formatting/parsing.

## Problem Context

The harness encounters 400 Bad Request errors on the **second** model request (after tool execution). The error suggests JSON parsing issues:

```
Invalid JSON: EOF while parsing a list at line 120 column 4
input_value='[\\n    {"name": "simple_...n    \\n    \\n    \\n    ', input_type=str
```

To debug this, we need to capture:
1. **Raw HTTP request body** - exactly what the OpenAI client sends
2. **Parsed request after pydantic validation** - what vLLM interprets
3. **Chat template input** - messages/tools before Jinja rendering
4. **Chat template output** - the actual prompt string sent to the model
5. **Raw model output** - tokenized output before tool parsing
6. **Parsed tool calls** - extracted function calls after parsing

---

## Implementation Options

### Option 1: HTTP Middleware Logging (Recommended First Step)

Add middleware to log raw HTTP request/response bodies.

**File to create:** `server/logging_middleware.py`

```python
"""HTTP logging middleware for vLLM debugging."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("vllm.http_debug")

LOG_DIR = Path("/tmp/vllm_debug_logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


class RequestResponseLogger(BaseHTTPMiddleware):
    """Log raw HTTP request and response bodies."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only log chat completions
        if "/v1/chat/completions" not in str(request.url):
            return await call_next(request)

        request_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        # Read and log request body
        body = await request.body()
        request_log = LOG_DIR / f"{request_id}_request.json"

        try:
            parsed_body = json.loads(body)
            request_log.write_text(
                json.dumps(parsed_body, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            logger.info("Request logged to %s", request_log)

            # Log key fields
            logger.info(
                "REQUEST %s: messages=%d, tools=%d, tool_choice=%s",
                request_id,
                len(parsed_body.get("messages", [])),
                len(parsed_body.get("tools", [])),
                parsed_body.get("tool_choice"),
            )

            # Log message structure
            for i, msg in enumerate(parsed_body.get("messages", [])):
                role = msg.get("role", "unknown")
                has_tool_calls = "tool_calls" in msg
                tool_call_type = type(msg.get("tool_calls")).__name__ if has_tool_calls else "N/A"
                logger.info(
                    "  Message %d: role=%s, has_tool_calls=%s, tool_calls_type=%s",
                    i, role, has_tool_calls, tool_call_type
                )

        except json.JSONDecodeError as e:
            logger.error("Failed to parse request body: %s", e)
            request_log.write_bytes(body)

        # Get response
        response = await call_next(request)

        # Log response (would need response body capture)
        response_log = LOG_DIR / f"{request_id}_response_status.txt"
        response_log.write_text(f"status={response.status_code}")

        return response
```

**Integration:** Add to vLLM startup in `entrypoint.sh`:

```bash
# Add to Python path
export PYTHONPATH="/app:$PYTHONPATH"

# Modify vLLM serve command to use custom app wrapper
python -c "
from vllm.entrypoints.openai.api_server import run_server
from logging_middleware import RequestResponseLogger
# ... wrap app with middleware
"
```

---

### Option 2: vLLM Internal Hooks (More Comprehensive)

Create a custom plugin to hook into vLLM's internal processing.

**File to create:** `server/vllm_debug_plugin.py`

```python
"""vLLM debug plugin for comprehensive logging."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("vllm.debug_plugin")

LOG_DIR = Path("/tmp/vllm_internal_logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_request_preprocessing(
    request_id: str,
    messages: list[dict],
    tools: list[dict],
    tool_choice: str,
) -> None:
    """Log request data after pydantic parsing but before template rendering."""
    log_file = LOG_DIR / f"{request_id}_preprocessed.json"

    data = {
        "timestamp": datetime.now().isoformat(),
        "messages_count": len(messages),
        "tools_count": len(tools),
        "tool_choice": tool_choice,
        "messages": messages,
        "tools": tools,
    }

    # Detailed message analysis
    for i, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant" and "tool_calls" in msg:
            tool_calls = msg["tool_calls"]
            data[f"message_{i}_tool_calls_type"] = type(tool_calls).__name__
            data[f"message_{i}_tool_calls_is_string"] = isinstance(tool_calls, str)
            if isinstance(tool_calls, str):
                data[f"message_{i}_tool_calls_raw"] = tool_calls[:500]
            elif isinstance(tool_calls, list):
                data[f"message_{i}_tool_calls_length"] = len(tool_calls)
                for j, tc in enumerate(tool_calls):
                    data[f"message_{i}_tool_call_{j}_type"] = type(tc).__name__
                    if isinstance(tc, dict):
                        data[f"message_{i}_tool_call_{j}_keys"] = list(tc.keys())

    log_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )
    logger.info("Preprocessed request logged to %s", log_file)


def log_chat_template_io(
    request_id: str,
    template_input: dict[str, Any],
    template_output: str,
) -> None:
    """Log the exact input/output of the chat template rendering."""
    input_file = LOG_DIR / f"{request_id}_template_input.json"
    output_file = LOG_DIR / f"{request_id}_template_output.txt"

    input_file.write_text(
        json.dumps(template_input, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )
    output_file.write_text(template_output, encoding="utf-8")

    logger.info("Template I/O logged: input=%s, output=%s", input_file, output_file)
    logger.info("Template output length: %d chars", len(template_output))


def log_model_output(
    request_id: str,
    raw_output: str,
    parsed_tool_calls: list[dict] | None,
) -> None:
    """Log raw model output and parsed tool calls."""
    raw_file = LOG_DIR / f"{request_id}_model_raw.txt"
    parsed_file = LOG_DIR / f"{request_id}_model_parsed.json"

    raw_file.write_text(raw_output, encoding="utf-8")

    if parsed_tool_calls:
        parsed_file.write_text(
            json.dumps(parsed_tool_calls, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    logger.info(
        "Model output logged: raw=%s (%d chars), has_tool_calls=%s",
        raw_file, len(raw_output), parsed_tool_calls is not None
    )
```

---

### Option 3: Patch vLLM Source (Most Detailed)

For maximum visibility, patch the vLLM source files directly.

**Key files to patch in vLLM:**

1. **`vllm/entrypoints/openai/serving_chat.py`**
   - Add logging in `create_chat_completion()` before and after request processing

2. **`vllm/entrypoints/chat_utils.py`**
   - Log in `apply_hf_chat_template()` or `apply_mistral_chat_template()`

3. **`vllm/tool_parsers/functiongemma_tool_parser.py`**
   - Add logging in `extract_tool_calls()` and `extract_tool_calls_streaming()`

**Example patch for serving_chat.py:**

```python
# Add at the top
import json
from pathlib import Path

DEBUG_LOG_DIR = Path("/tmp/vllm_serving_debug")
DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)

# In create_chat_completion method, before processing:
def create_chat_completion(self, request: ChatCompletionRequest, ...):
    request_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

    # Log raw request
    log_file = DEBUG_LOG_DIR / f"{request_id}_serving_input.json"
    log_file.write_text(json.dumps({
        "messages": [m.model_dump() for m in request.messages],
        "tools": [t.model_dump() for t in (request.tools or [])],
        "tool_choice": request.tool_choice,
    }, indent=2, default=str))

    # ... existing code ...
```

---

## Quick Start: Minimal Debug Setup

Add this to your `entrypoint.sh` for immediate visibility:

```bash
#!/bin/bash
set -e

# Enable verbose logging
export VLLM_LOGGING_LEVEL=DEBUG
export VLLM_TRACE_FUNCTION=1

# Create debug log directory
mkdir -p /tmp/vllm_debug

# Start vLLM with logging
vllm serve google/functiongemma-270m-it \
    --enable-auto-tool-choice \
    --tool-call-parser functiongemma \
    --chat-template /app/tool_chat_template_functiongemma.jinja \
    --max-num-seqs 32 \
    --max-model-len 32768 \
    --enable-prefix-caching \
    2>&1 | tee /tmp/vllm_debug/vllm_output.log
```

Then monitor with:
```bash
# Watch vLLM output
docker exec -it vllm-gemma tail -f /tmp/vllm_debug/vllm_output.log

# Search for specific errors
docker exec -it vllm-gemma grep -i "error\|validation\|invalid" /tmp/vllm_debug/vllm_output.log
```

---

## Specific Areas to Investigate

Based on the error pattern, focus logging on:

### 1. Tool Schema Parsing

The error mentions `{"name": "simple_...` which suggests the tools array structure. Log:
- Raw `tools` parameter from request
- Type of each tool item (`type(tool)`)
- Structure validation results

### 2. Message tool_calls Field

The error occurs on second request (with tool history). Log:
- Whether `tool_calls` is string or list
- If string, what it contains
- If list, type of each element

### 3. Pydantic Validation

The error `list[function-wrap[__log_extra_fields__()]]` is pydantic-specific. Check:
- vLLM's pydantic model definitions for tools
- Whether extra fields are being passed
- Schema compatibility with your tool definitions

---

## Log Analysis Script

Create `scripts/analyze_vllm_logs.py`:

```python
#!/usr/bin/env python3
"""Analyze vLLM debug logs for the 400 error pattern."""

import json
import sys
from pathlib import Path


def analyze_request(request_file: Path) -> None:
    """Analyze a request log file for potential issues."""
    data = json.loads(request_file.read_text())

    print(f"\n=== Analyzing {request_file.name} ===")

    # Check messages
    messages = data.get("messages", [])
    print(f"Messages: {len(messages)}")

    for i, msg in enumerate(messages):
        role = msg.get("role")
        print(f"  [{i}] role={role}")

        if role == "assistant" and "tool_calls" in msg:
            tc = msg["tool_calls"]
            print(f"      tool_calls type: {type(tc).__name__}")
            if isinstance(tc, str):
                print(f"      WARNING: tool_calls is STRING: {tc[:100]}...")
            elif isinstance(tc, list):
                print(f"      tool_calls count: {len(tc)}")
                for j, call in enumerate(tc):
                    print(f"        [{j}] type={type(call).__name__}, keys={list(call.keys()) if isinstance(call, dict) else 'N/A'}")

        if role == "tool":
            print(f"      tool_call_id: {msg.get('tool_call_id', 'MISSING')}")
            print(f"      name: {msg.get('name', 'MISSING')}")

    # Check tools
    tools = data.get("tools", [])
    print(f"\nTools: {len(tools)}")
    for i, tool in enumerate(tools):
        if isinstance(tool, dict):
            func = tool.get("function", {})
            print(f"  [{i}] {func.get('name', 'unknown')}")
        else:
            print(f"  [{i}] WARNING: tool is {type(tool).__name__}, not dict")


if __name__ == "__main__":
    log_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/vllm_debug_logs")

    for request_file in sorted(log_dir.glob("*_request.json")):
        try:
            analyze_request(request_file)
        except Exception as e:
            print(f"Error analyzing {request_file}: e}")
```

---

## Expected Findings

When logging is enabled, look for these specific patterns:

1. **tool_calls as string** - Should be a list, not JSON string
2. **Truncated JSON** - Look for incomplete arrays/objects
3. **Extra whitespace** - The `\\n    \\n    \\n` pattern suggests empty lines
4. **Type mismatches** - Pydantic expecting dict but receiving string

The logs should reveal exactly where the malformation occurs in the request pipeline.
