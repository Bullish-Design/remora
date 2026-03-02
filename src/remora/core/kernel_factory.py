"""Shared kernel factory for LLM client/adapter/kernel creation.

Deduplicates the boilerplate that ``SwarmExecutor._run_kernel`` and
``ChatSession.send`` both need to set up an ``AgentKernel``.
"""

from __future__ import annotations

from typing import Any

from structured_agents.agent import get_response_parser
from structured_agents.client import build_client
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter


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
        Model identifier (e.g. ``"Qwen/Qwen3-4B"``).
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
        Optional ``structured_agents`` grammar config for constrained decoding.
    client:
        Pre-built OpenAI-compatible client to reuse. If ``None`` a new one
        is created via ``build_client``.
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

    parser = get_response_parser(model_name)
    pipeline = ConstraintPipeline(grammar_config) if grammar_config else None
    adapter = ModelAdapter(
        name=model_name,
        response_parser=parser,
        constraint_pipeline=pipeline,
    )

    return AgentKernel(
        client=client,
        adapter=adapter,
        tools=tools or [],
        observer=observer,
    )


__all__ = ["create_kernel"]
