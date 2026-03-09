"""Shared kernel factory for LLM client/kernel creation.

v0.4 API: ModelAdapter removed, response_parser is now a direct kernel parameter.
"""

from __future__ import annotations

from typing import Any

from structured_agents import (
    AgentKernel,
    ConstraintPipeline,
    NullObserver,
    build_client,
    get_response_parser,
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


def extract_response_text(result: Any) -> str:
    """Extract text content from an AgentKernel run result."""
    if hasattr(result, "final_message") and result.final_message:
        message = result.final_message
        if hasattr(message, "content") and message.content:
            return message.content
        return str(result)

    if hasattr(result, "content") and result.content:
        return result.content

    return str(result)


__all__ = ["create_kernel", "extract_response_text"]
