# How to Create a `structured-agents` Agent

This guide is the single source of truth for building agents with `structured-agents`. It covers the core agent loop, how to define tools, how to package agents with bundles, and how to execute `.pym` tools with Grail.

> **Prerequisite:** Read [HOW_TO_CREATE_A_GRAIL_PYM_SCRIPT.md](HOW_TO_CREATE_A_GRAIL_PYM_SCRIPT.md) if you plan to use `.pym` tools.

---

## Table of Contents

1. [What a `structured-agents` Agent Is](#1-what-a-structured-agents-agent-is)
2. [Core Components](#2-core-components)
3. [Architecture and Component Interaction](#3-architecture-and-component-interaction)
4. [AgentKernel Basics](#4-agentkernel-basics)
5. [Tool Schemas](#5-tool-schemas)
6. [Tool Sources: Registries and Backends](#6-tool-sources-registries-and-backends)
7. [Bundles: The Recommended Packaging Model](#7-bundles-the-recommended-packaging-model)
8. [bundle.yaml Schema Reference](#8-bundleyaml-schema-reference)
9. [Context Providers](#9-context-providers)
10. [Termination and Tool Choice](#10-termination-and-tool-choice)
11. [End-to-End Example (Bundle + Kernel)](#11-end-to-end-example-bundle--kernel)
12. [Debugging and Validation](#12-debugging-and-validation)

---

## 1. What a `structured-agents` Agent Is

`structured-agents` is a **minimal, composable agent loop**. An “agent” in this library is a combination of:

- A set of messages (system + user)
- A set of tool schemas the model may call
- A tool execution backend
- A model plugin that formats tool calls and parses responses
- A termination condition

The library does **not** manage workspaces, multi-agent orchestration, or state persistence. Those are responsibilities of the consumer.

---

## 2. Core Components

These are the building blocks you will use in every agent:

- `AgentKernel`: the loop that calls the model and executes tools.
- `ToolSchema`: OpenAI-compatible tool schema objects.
- `ToolSource`: discovers tools and executes them.
- `ModelPlugin`: formats messages/tools and parses responses (e.g., `FunctionGemmaPlugin`).
- `ToolBackend`: executes tool calls (e.g., `GrailBackend`, `PythonBackend`).
- `ToolRegistry`: discovers tool schemas (e.g., `GrailRegistry`, `PythonRegistry`).

---

## 3. Architecture and Component Interaction

This section provides a detailed architecture overview of how the core components interact during a run.

### High-Level Data Flow

```
Messages + Tool Schemas
        │
        ▼
ModelPlugin → formatted messages/tools + grammar
        │
        ▼
LLMClient → completion response
        │
        ▼
ModelPlugin → parsed content + ToolCalls
        │
        ▼
ToolSource → ToolResults
        │
        ▼
History + Observer Events → RunResult
```

### Architecture Diagram

```
┌─────────────┐   formatted   ┌──────────────┐   call    ┌────────────┐
│  Messages   ├──────────────►│  ModelPlugin │──────────►│ LLMClient  │
└──────┬──────┘               └──────┬───────┘           └─────┬──────┘
       │                             │                         │
       │ tools                        ▼                         │
       │                    parsed tool calls                   │
       │                             │                         ▼
       │                             │                 completion
       │                             │                         │
       │                             ▼                         │
┌──────▼──────┐  execute     ┌──────────────┐   results  ┌──────▼──────┐
│ ToolSource │──────────────►│ ToolBackend │───────────►│ ToolResult  │
└──────┬──────┘               └──────┬──────┘           └──────┬──────┘
       │                             │                         │
       │ resolve                      │                         │
       ▼                             ▼                         ▼
┌──────────────┐             ┌──────────────┐          ┌────────────────┐
│ ToolRegistry │             │ Context/IO   │          │ History/Events │
└──────────────┘             └──────────────┘          └────────────────┘
```

### Component Responsibilities

- **AgentKernel**
  - Owns the turn loop and termination checks.
  - Trims history using the configured `HistoryStrategy`.
  - Emits observer events (`KernelStartEvent`, `ModelRequestEvent`, `ToolResultEvent`, etc.).

- **ModelPlugin**
  - Formats raw `Message` objects and tool schemas into model-ready payloads.
  - Builds grammar constraints (EBNF, JSON schema, or structural tag) via `GrammarProvider`.
  - Parses model responses into content + `ToolCall` objects.

- **LLMClient**
  - Executes chat completion requests against an OpenAI-compatible API.
  - Returns raw responses, tool calls, and token usage metadata.

- **ToolSource**
  - Resolves tool schemas by name and executes tool calls.
  - The default implementation (`RegistryBackendToolSource`) bridges a registry and a backend.

- **ToolRegistry**
  - Discovers and returns `ToolSchema` definitions.
  - `GrailRegistry` reads `.pym` tools and their `.grail/<tool>/inputs.json` metadata.
  - `PythonRegistry` builds schemas from Python function signatures.

- **ToolBackend**
  - Executes tools and returns `ToolResult` objects.
  - `GrailBackend` runs `.pym` files in separate processes and injects externals.
  - `PythonBackend` executes local Python functions for tests or lightweight tools.

- **Observer**
  - Receives structured lifecycle events for logging, telemetry, or UI hooks.
  - Events include request/response timing, tool call details, and run termination.

### Context Flow

`AgentKernel` can call an optional `context_provider` each turn. The returned context dict is:

1. Merged into tool arguments at execution time.
2. Available to context provider scripts when using Grail tools.

This context is **not** automatically filtered or injected into the model prompt. The consumer controls what the model sees.

### Termination

The kernel does not hardcode a termination tool. It relies on a caller-supplied `termination` predicate that inspects `ToolResult`. Bundles store `termination_tool` as a convention, not an enforcement mechanism.

---

## 4. AgentKernel Basics

At the lowest level, you can build an agent by hand:

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

This example uses Python tools, not Grail. The kernel will:

1. Send the system/user messages + tool schema to the model.
2. Parse the tool call.
3. Execute the tool.
4. Append the tool result to the conversation.
5. Repeat until max turns or termination.

---

## 5. Tool Schemas

Tool schemas are OpenAI-compatible JSON Schema definitions:

```python
ToolSchema(
    name="read_file",
    description="Read a file and return its contents.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)
```

The schema is what the model sees. Keep it accurate and minimal. For Grail tools, the schema is usually derived from `inputs.json` generated by `grail check`.

---

## 6. Tool Sources: Registries and Backends

`ToolSource` abstracts discovery and execution. The default implementation is `RegistryBackendToolSource`, which combines:

- A **registry** to discover tool schemas.
- A **backend** to execute tool calls.

Common configurations:

### Python Tools

```python
registry = PythonRegistry()
backend = PythonBackend(registry=registry)
source = RegistryBackendToolSource(registry, backend)
```

### Grail `.pym` Tools

```python
from structured_agents.backends import GrailBackend, GrailBackendConfig
from structured_agents.registries import GrailRegistry, GrailRegistryConfig

registry = GrailRegistry(GrailRegistryConfig(agents_dir="./agents"))
backend = GrailBackend(GrailBackendConfig(grail_dir="./agents"))
source = RegistryBackendToolSource(registry, backend)
```

---

## 7. Bundles: The Recommended Packaging Model

Bundles package prompts, tool definitions, and model configuration into a portable directory.

A typical bundle layout:

```
my_bundle/
  bundle.yaml
  tools/
    read_file.pym
    write_file.pym
```

You can load and run a bundle like this:

```python
from structured_agents import AgentKernel, KernelConfig, load_bundle
from structured_agents.backends import GrailBackend, GrailBackendConfig

bundle = load_bundle("./my_bundle")
backend = GrailBackend(GrailBackendConfig(grail_dir="./my_bundle/tools"))
plugin = bundle.get_plugin()

kernel = AgentKernel(
    config=KernelConfig(base_url="http://localhost:8000/v1", model="test"),
    plugin=plugin,
    tool_source=bundle.build_tool_source(backend),
)

messages = bundle.build_initial_messages({"input": "Add a docstring"})
result = await kernel.run(messages, bundle.tool_schemas, max_turns=bundle.max_turns)
```

---

## 8. `bundle.yaml` Schema Reference

`bundle.yaml` is validated against `BundleManifest`. This is the canonical structure:

```yaml
name: "docstring_writer"
version: "1.0"

model:
  plugin: "function_gemma"   # Plugin name
  adapter: null               # Optional LoRA adapter
  grammar:
    mode: "json_schema"      # ebnf | structural_tag | json_schema
    allow_parallel_calls: true
    args_format: "permissive"  # permissive | escaped_strings | json

initial_context:
  system_prompt: "You are a docstring tool. Always call a function."
  user_template: "{{ input }}"

max_turns: 10
termination_tool: "submit_result"

tools:
  - name: "read_file"
    registry: "grail"
    description: "Read a file and return its contents."
  - name: "submit_result"
    registry: "grail"
    description: "Submit the final result."

registries:
  - type: "grail"
    config:
      agents_dir: "tools"
```

### Tool Fields

Each tool supports:

- `name`: Tool name (must match `.pym` stem or Python registry tool name)
- `registry`: Registry name (`grail` or `python`)
- `description`: Optional tool description override
- `inputs_override`: Optional full schema override **(replaces** `parameters`)
- `context_providers`: Optional list of `.pym` scripts run before the tool

> Note: `inputs_override` replaces the schema entirely, so you must provide a complete JSON Schema object if you use it.

---

## 9. Context Providers

Context providers are `.pym` scripts that run before a tool executes. Their output is prepended to the tool response as JSON lines. This is useful for injecting configuration (e.g., lint settings) without a separate model call.

Context providers are configured in `bundle.yaml` under each tool:

```yaml
tools:
  - name: "run_linter"
    registry: "grail"
    context_providers:
      - "context/ruff_config.pym"
```

---

## 10. Termination and Tool Choice

`AgentKernel.run()` accepts an optional termination callback:

```python
async def is_submit(result: ToolResult) -> bool:
    return result.name == "submit_result" and not result.is_error

result = await kernel.run(messages, tools, max_turns=5, termination=is_submit)
```

Bundles include `termination_tool` as a convention, but the kernel itself does not enforce it. You must pass a termination function if you want the kernel to stop on a specific tool.

Tool choice is controlled by `KernelConfig.tool_choice` and grammar settings on the plugin.

---

## 11. End-to-End Example (Bundle + Kernel)

```
my_agent/
  bundle.yaml
  tools/
    read_file.pym
    write_file.pym
    submit_result.pym
```

`bundle.yaml`:

```yaml
name: "my_agent"
model:
  plugin: "function_gemma"
initial_context:
  system_prompt: "You are a file editing tool. Always call a function."
  user_template: "{{ input }}"
max_turns: 6
termination_tool: "submit_result"

tools:
  - name: "read_file"
    registry: "grail"
  - name: "write_file"
    registry: "grail"
  - name: "submit_result"
    registry: "grail"

registries:
  - type: "grail"
    config:
      agents_dir: "tools"
```

Run it:

```python
from structured_agents import AgentKernel, KernelConfig, load_bundle
from structured_agents.backends import GrailBackend, GrailBackendConfig
from structured_agents.types import ToolResult

bundle = load_bundle("./my_agent")
backend = GrailBackend(GrailBackendConfig(grail_dir="./my_agent/tools"))
plugin = bundle.get_plugin()

kernel = AgentKernel(
    config=KernelConfig(base_url="http://localhost:8000/v1", model="test"),
    plugin=plugin,
    tool_source=bundle.build_tool_source(backend),
)

messages = bundle.build_initial_messages({"input": "Update the README"})

def is_submit(result: ToolResult) -> bool:
    return result.name == bundle.termination_tool and not result.is_error

result = await kernel.run(messages, bundle.tool_schemas, max_turns=bundle.max_turns, termination=is_submit)
await kernel.close()
```

---

## 12. Debugging and Validation

### Validate `.pym` Scripts

Always run:

```bash
grail check path/to/tool.pym
```

This generates `.grail/<tool_name>/inputs.json` used by `GrailRegistry`.

### Inspect Tool Schemas

You can print `bundle.tool_schemas` or `ToolSchema.to_openai_format()` to inspect the JSON sent to the model.

### Model Issues

If the model refuses to call tools or produces no tool calls:

- Ensure the system prompt is concise and ends with “Always call a function.”
- Ensure tool descriptions are distinct and start with verbs.
- Ensure tool schemas have correct `required` parameters.

---

## Quick Reference

### Minimal Bundle

```yaml
name: "agent"
model:
  plugin: "function_gemma"
initial_context:
  system_prompt: "You are a tool. Always call a function."
  user_template: "{{ input }}"
max_turns: 3
termination_tool: "submit_result"
tools:
  - name: "submit_result"
    registry: "grail"
registries:
  - type: "grail"
    config:
      agents_dir: "tools"
```

### Minimal `.pym`

```python
from grail import Input

message: str = Input("message")

{"echo": message}
```

---

## Structured-Agents Cheat Sheet

- **Core loop:** `AgentKernel.run()` drives model → tool → history
- **Tool discovery:** `ToolRegistry` resolves `ToolSchema` definitions
- **Tool execution:** `ToolBackend` executes calls (`GrailBackend` or `PythonBackend`)
- **Tool wiring:** `RegistryBackendToolSource` combines registry + backend
- **Bundles:** `bundle.yaml` defines tools, prompts, model settings
- **Termination:** pass a `termination` predicate to `AgentKernel.run()`
- **Context:** `context_provider` returns a dict merged into tool args
- **Grammar constraints:** configured via bundle `model.grammar` or `GrammarConfig`
