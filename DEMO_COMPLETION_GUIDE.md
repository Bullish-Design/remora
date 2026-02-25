# Ultimate Demo Completion Guide

This guide provides a step-by-step roadmap for building the "Ultimate Demo" script (`scripts/full_demo.py`). This demo will bypass the HTTP REST layer to natively instantiate Remora's core components and showcase the full power of `structured-agents`, `vLLM`, and `Grail`, emphasizing dynamic switching, interactive pausing, and multi-model routing.

---

## 1. Architecture of the Ultimate Demo

The goal is to create a comprehensive Python script that orchestrates the following:
1. **Code Discovery:** Use `TreeSitterDiscoverer` to locally parse a sample project (`demo_input/`).
2. **Dynamic Agent Routing & Switching:** Use `structured-agents` (`AgentKernel`, `load_bundle`) to assign completely different prompts, tool sets, and even LLM plugins/adapters based on the AST node type (e.g., function vs. class).
3. **Interactive Pauses (Human-in-the-Loop):** Utilize the `structured-agents` `CompositeObserver` and Remora's `event_bus` to pause agent execution and request human input (e.g., "Do you want to apply this fix?").
4. **Parallel Tool Execution:** Showcase `Grail` backend executing multiple tools concurrently per turn.

---

## 2. Step-by-Step Implementation Plan

### Step 1: Scaffold the Native Script Setup
Create a new file `demo/full_demo.py` (or `scripts/full_demo.py`).
- Initialize the `HubDaemon` natively in a background `asyncio.Task`.
- Create a `GraphWorkspace` linked to `demo_input/`.
- Instantiate the `TreeSitterDiscoverer` to extract `CSTNode`s.

```python
# Pseudo-code Example
discoverer = TreeSitterDiscoverer(root_dirs=[Path("demo_input/src")], query_pack="remora_core")
nodes = discoverer.discover()
```

### Step 2: Showcase Dynamic Model Routing & Agent Switching
Instead of relying on a single default `vLLM` adapter, demonstrate `structured-agents` flexibility.
- For `function` nodes: Load the `agents/lint` bundle. Configure its `KernelConfig` to use the `QwenPlugin` plugin and a specific fast adapter (e.g., `Qwen/Qwen3-4B-Instruct-2507-FP`).
- For `class` nodes: Load the `agents/docstring` bundle. Configure its `KernelConfig` to use qwen as well.

**Key Concept to Highlight:** How quickly we can stitch together a `registry`, `backend`, and `KernelConfig` per Agent Node before executing the `AgentGraph`.

```python
from structured_agents import load_bundle, KernelConfig
from structured_agents.backends import GrailBackend

# Dynamically load different bundles per node
lint_bundle = load_bundle("agents/lint")
docstring_bundle = load_bundle("agents/docstring")
```

### Step 3: Integrate Interactive Pauses (Agent Inbox)
The current demo fires and forgets. We need to show the "wow" factor of a paused agent.
- Hook into the `AgentGraph.on_blocked` callback.
- When an agent emits a "Needs Approval" or "Question" event, the script should visually halt.
- Provide a simple CLI prompt (or TUI if integrated with `textual` / `datastar` as per `TUI_DEMO_CONCEPT.md`) for the human to answer.
- Feed the answer back to the agent via `agent.inbox.ask_user(question)` or resolving the `AgentNode` state.

### Step 4: Leverage Parallel Tool Execution with Grail
Showcase the `structured-agents` concurrency model.
- Ensure `KernelConfig(tool_execution_strategy=ToolExecutionStrategy(mode="concurrent"))` is set.
- Ensure the grammar `allow_parallel_calls` is `true`.
- In the demo output, log when multiple Grail `.pym` scripts (e.g., `run_linter` and `read_file`) are fired at the exact same time by the `GrailBackend`.

### Step 5: Wire up the Observability Setup
Use `structured-agents`'s `Observer` pattern to stream beautiful console outputs.
- Create a custom observer that implements `on_tool_call`, `on_tool_result`, and `on_turn_complete`.
- Print rich console output (using the `rich` library) showing exactly what the agent is thinking, which tools it selected, and how long the vLLM inference took.

```python
from structured_agents import Observer

class RichConsoleObserver(Observer):
    async def on_tool_call(self, event):
        print(f"[bold cyan]Agent is calling tool:[/bold cyan] {event.tool_call.name}")
```

---

## 3. Final Output & Artifacts

By the end of the `full_demo.py` script:
1. The `demo_output/` directory should contain the fully modified codebase (lint fixes applied, docstrings generated).
2. The terminal should have displayed a rich, interactive log showing different LLM models being routed dynamically, tools executing in parallel, and at least one human-in-the-loop interaction.

Review `demo/setup_demo.py` to ensure it generates a complex enough sample file to trigger all these conditions (e.g., a file with both lint errors and missing docstrings on classes).
