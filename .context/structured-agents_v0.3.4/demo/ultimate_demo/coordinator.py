from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from structured_agents.agent import Agent, AgentManifest
from structured_agents.client import build_client
from structured_agents.events.observer import NullObserver, Observer
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter
from structured_agents.models.parsers import QwenResponseParser
from structured_agents.tools.protocol import Tool

from demo.ultimate_demo.config import API_KEY, BASE_URL, GRAMMAR_CONFIG, MODEL_NAME
from demo.ultimate_demo.state import DemoState
from demo.ultimate_demo.subagents import build_subagent_tools
from demo.ultimate_demo.tools import build_demo_tools

SYSTEM_PROMPT = (
    "You are a project coordinator. Use tools to update state: add_task, "
    "update_task_status, record_risk, log_update. When asked for plans or risks, "
    "delegate to task_planner or risk_analyst subagents. Always call tools to "
    "record structured updates before responding."
)


@dataclass(frozen=True, slots=True)
class DemoCoordinator:
    state: DemoState
    tools: list[Tool]
    subagent_tools: list[Tool]
    kernel: AgentKernel
    agent: Agent


def build_demo_state() -> DemoState:
    return DemoState.initial()


def build_demo_kernel(
    tools: list[Tool],
    subagent_tools: list[Tool],
    observer: Observer | None = None,
) -> AgentKernel:
    pipeline = (
        ConstraintPipeline(GRAMMAR_CONFIG) if GRAMMAR_CONFIG is not None else None
    )
    adapter = ModelAdapter(
        name="qwen",
        response_parser=QwenResponseParser(),
        constraint_pipeline=pipeline,
    )
    client = build_client(
        {
            "base_url": BASE_URL,
            "api_key": API_KEY,
            "model": MODEL_NAME,
        }
    )
    return AgentKernel(
        client=client,
        adapter=adapter,
        tools=[*tools, *subagent_tools],
        observer=observer or NullObserver(),
    )


def build_demo_agent(kernel: AgentKernel) -> Agent:
    manifest = AgentManifest(
        name="ultimate-demo",
        system_prompt=SYSTEM_PROMPT,
        agents_dir=Path(__file__).resolve().parent,
    )
    return Agent(kernel=kernel, manifest=manifest)


def build_demo_coordinator(observer: Observer | None = None) -> DemoCoordinator:
    state = build_demo_state()
    tools = build_demo_tools(state)
    subagent_tools = build_subagent_tools(state, observer=observer)
    kernel = build_demo_kernel(tools, subagent_tools, observer=observer)
    agent = build_demo_agent(kernel)
    return DemoCoordinator(
        state=state,
        tools=tools,
        subagent_tools=subagent_tools,
        kernel=kernel,
        agent=agent,
    )
