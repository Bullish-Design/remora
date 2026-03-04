# kernel_factory.py Migration

This file documents the before/after changes for `src/remora/core/kernel_factory.py`.

## Summary

The `ModelAdapter` abstraction has been removed in structured-agents v0.4.
Instead of wrapping `response_parser` and `constraint_pipeline` in an adapter,
pass them directly to `AgentKernel`.

## Before (v0.3 - Current Broken Code)

```python
"""Shared kernel factory for LLM client/adapter/kernel creation."""

from __future__ import annotations
from typing import Any

from structured_agents.agent import get_response_parser          # BROKEN - module deleted
from structured_agents.client import build_client
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter        # BROKEN - module deleted


def create_kernel(
    *,
    model_name: str,
    base_url: str,
    api_key: str,
    timeout: float = 300.0,
    tools: list[Any] | None = None,
    observer: Any | None = None,
    grammar_config: Any | None = None,
    client: Any | None = None,
) -> AgentKernel:
    if client is None:
        client = build_client(
            {
                "base_url": base_url,
                "api_key": api_key or "EMPTY",
                "model": model_name,
                "timeout": timeout,
            }
        )

    parser = get_response_parser(model_name)
    pipeline = ConstraintPipeline(grammar_config) if grammar_config else None
    adapter = ModelAdapter(                                      # BROKEN - class deleted
        name=model_name,
        response_parser=parser,
        constraint_pipeline=pipeline,
    )

    return AgentKernel(
        client=client,
        adapter=adapter,                                         # BROKEN - param removed
        tools=tools or [],
        observer=observer,
    )
```

## After (v0.4 - Fixed Code)

```python
"""Shared kernel factory for LLM client/kernel creation.

v0.4 API: ModelAdapter removed, response_parser is now a direct kernel parameter.
"""

from __future__ import annotations
from typing import Any

from structured_agents import (
    AgentKernel,
    build_client,
    get_response_parser,
    ConstraintPipeline,
    NullObserver,
)


def create_kernel(
    *,
    model_name: str,
    base_url: str,
    api_key: str,
    timeout: float = 300.0,
    tools: list[Any] | None = None,
    observer: Any | None = None,
    grammar_config: Any | None = None,
    client: Any | None = None,
) -> AgentKernel:
    """Create an ``AgentKernel`` with the standard Remora defaults.

    Parameters
    ----------
    model_name:
        Model identifier (e.g. ``"Qwen/Qwen3-4B"`` or ``"hosted_vllm/Qwen/Qwen3-4B"``).
    base_url:
        OpenAI-compatible API base URL.
    api_key:
        API key (``"EMPTY"`` for local servers).
    timeout:
        HTTP request timeout in seconds.
    tools:
        Tool instances to attach to the kernel.
    observer:
        Event observer (``EventBus``, ``EventStore`` wrapper, etc.).
    grammar_config:
        Optional grammar config for constrained decoding (DecodingConstraint).
    client:
        Pre-built LLM client to reuse. If ``None`` a new one is created.
    """
    if client is None:
        client = build_client(
            {
                "base_url": base_url,
                "api_key": api_key or "EMPTY",
                "model": model_name,
                "timeout": timeout,
            }
        )

    # v0.4: response_parser is now a direct kernel parameter
    response_parser = get_response_parser(model_name)
    
    # v0.4: constraint_pipeline is now a direct kernel parameter
    constraint_pipeline = None
    if grammar_config:
        constraint_pipeline = ConstraintPipeline(grammar_config)

    return AgentKernel(
        client=client,
        response_parser=response_parser,
        tools=tools or [],
        observer=observer or NullObserver(),
        constraint_pipeline=constraint_pipeline,
    )


__all__ = ["create_kernel"]
```

## Key Changes

| Aspect | Before (v0.3) | After (v0.4) |
|--------|---------------|--------------|
| Import `get_response_parser` | `from structured_agents.agent` | `from structured_agents` |
| Import `ModelAdapter` | Required | **Removed** |
| Kernel param `adapter` | `adapter=ModelAdapter(...)` | **Removed** |
| Kernel param `response_parser` | N/A (was in adapter) | `response_parser=parser` |
| Kernel param `constraint_pipeline` | N/A (was in adapter) | `constraint_pipeline=pipeline` |
| Observer default | `observer` (could be None) | `observer or NullObserver()` |

## Diff

```diff
-from structured_agents.agent import get_response_parser
-from structured_agents.client import build_client
-from structured_agents.grammar.pipeline import ConstraintPipeline
-from structured_agents.kernel import AgentKernel
-from structured_agents.models.adapter import ModelAdapter
+from structured_agents import (
+    AgentKernel,
+    build_client,
+    get_response_parser,
+    ConstraintPipeline,
+    NullObserver,
+)

...

-    parser = get_response_parser(model_name)
-    pipeline = ConstraintPipeline(grammar_config) if grammar_config else None
-    adapter = ModelAdapter(
-        name=model_name,
-        response_parser=parser,
-        constraint_pipeline=pipeline,
-    )
+    response_parser = get_response_parser(model_name)
+    
+    constraint_pipeline = None
+    if grammar_config:
+        constraint_pipeline = ConstraintPipeline(grammar_config)

     return AgentKernel(
         client=client,
-        adapter=adapter,
+        response_parser=response_parser,
         tools=tools or [],
-        observer=observer,
+        observer=observer or NullObserver(),
+        constraint_pipeline=constraint_pipeline,
     )
```
