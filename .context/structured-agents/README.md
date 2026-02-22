# structured-agents

Structured tool orchestration with grammar-constrained LLM outputs. `structured-agents` provides a focused, composable agent loop that integrates model calls, tool execution, and observable events without taking over workspace or multi-agent coordination.

## What This Library Is

- A minimal, reusable agent kernel for tool-calling workflows.
- A structured output pipeline that supports grammar-constrained decoding via XGrammar.
- A toolkit for bundling tools, prompts, and model configuration.
- A clean integration layer for Grail `.pym` tools and Python tool backends.

## What This Library Is Not

- A multi-agent orchestrator.
- A workspace or filesystem manager.
- A code discovery or parsing engine.

## Installation

```bash
pip install structured-agents
```

`structured-agents` expects an OpenAI-compatible API (vLLM, etc.) and the XGrammar runtime for grammar-constrained decoding. Grail is required if you execute `.pym` tools.

## Quick Start

```python
import asyncio

from structured_agents import (
    AgentKernel,
    FunctionGemmaPlugin,
    KernelConfig,
    Message,
    ToolSchema,
)
from structured_agents.backends import PythonBackend
from structured_agents.registries import PythonRegistry
from structured_agents.tool_sources import RegistryBackendToolSource


async def main() -> None:
    config = KernelConfig(
        base_url="http://localhost:8000/v1",
        model="google/functiongemma-270m-it",
    )

    registry = PythonRegistry()
    backend = PythonBackend(registry=registry)

    async def greet(name: str) -> str:
        return f"Hello, {name}!"

    backend.register("greet", greet)
    tool_source = RegistryBackendToolSource(registry, backend)

    kernel = AgentKernel(
        config=config,
        plugin=FunctionGemmaPlugin(),
        tool_source=tool_source,
    )

    result = await kernel.run(
        initial_messages=[Message(role="user", content="Greet Alice")],
        tools=[
            ToolSchema(
                name="greet",
                description="Greet someone",
                parameters={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            )
        ],
        max_turns=3,
    )

    print(result.final_message.content)
    await kernel.close()


if __name__ == "__main__":
    asyncio.run(main())
```

## Tool Sources

`AgentKernel` requires a `ToolSource`. The default bridge is `RegistryBackendToolSource`, which combines a tool registry with an execution backend.

```python
from structured_agents.backends import GrailBackend, GrailBackendConfig
from structured_agents.registries import GrailRegistry, GrailRegistryConfig
from structured_agents.tool_sources import RegistryBackendToolSource

registry = GrailRegistry(GrailRegistryConfig(agents_dir="./agents"))
backend = GrailBackend(GrailBackendConfig(grail_dir="./agents"))
source = RegistryBackendToolSource(registry, backend)
```

## Parallel Tool Execution

Tool calls execute concurrently by default. Configure the strategy on `KernelConfig` if you need sequential execution or lower concurrency.

```python
from structured_agents import KernelConfig, ToolExecutionStrategy

config = KernelConfig(
    base_url="http://localhost:8000/v1",
    model="google/functiongemma-270m-it",
    tool_execution_strategy=ToolExecutionStrategy(mode="sequential", max_concurrency=1),
)
```

## Bundles

Bundles package prompts, tool definitions, and model configuration into a directory with a `bundle.yaml`.

```yaml
name: "docstring_writer"
model:
  plugin: "function_gemma"
  grammar:
    mode: "json_schema"
initial_context:
  system_prompt: "You are a docstring agent."
  user_template: "{{ input }}"
tools:
  - name: "read_file"
    registry: "grail"
  - name: "submit_result"
    registry: "grail"
registries:
  - type: "grail"
    config:
      agents_dir: "tools"
```

```python
from structured_agents import load_bundle
from structured_agents.backends import GrailBackend, GrailBackendConfig

bundle = load_bundle("./bundles/docstring_writer")
plugin = bundle.get_plugin()
messages = bundle.build_initial_messages({"input": "Add a docstring"})
backend = GrailBackend(GrailBackendConfig(grail_dir="./tools"))
source = bundle.build_tool_source(backend)
```

## Client Reuse

Use the client factory if you want to drive model calls directly while reusing `KernelConfig`.

```python
from structured_agents import KernelConfig
from structured_agents.client import build_client

config = KernelConfig(base_url="http://localhost:8000/v1", model="test")
client = build_client(config)
```

## Observability

The kernel emits events during execution. Observers can stream logs, drive TUIs, or capture telemetry.

```python
from structured_agents import CompositeObserver, NullObserver

observer = CompositeObserver([NullObserver()])
```

## API Overview

- `AgentKernel`: core agent loop and lifecycle.
- `ToolSource`: unified tool discovery + execution interface.
- `ToolExecutionStrategy`: controls sequential vs concurrent tool calls.
- `ModelPlugin`: composed plugin that formats messages/tools and parses responses.
- `AgentBundle`: bundle loader and tool schema generator.
- `Observer`: event hooks for external integrations.

## Project Status

The library is actively evolving. The API is stable for the core agent loop, but new plugins/backends may be added.

## License

MIT
