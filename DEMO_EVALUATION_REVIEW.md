# Demo Evaluation Review

This document evaluates the current implementations within the `demo/` directory against the capabilities of the underlying libraries (`structured-agents`, `vLLM`, and `Grail`), as well as the vision laid out in `DEMO_PLAN.md`.

## 1. Current State of the Demo

The `demo/` directory currently consists of three main scripts:
- `setup_demo.py`: Scaffolds a basic Python project structure (`main.py`, `helpers.py`, `remora.yaml`) inside a `demo_input/` folder.
- `start_server.py`: Boots up the Remora Hub server (`HubServer`).
- `api_demo.py`: Runs a fire-and-forget client script that utilizes `httpx` and `httpx_sse` to connect to the server, triggers `/graph/execute` twice (for `run_linter` and `write_docstring`), and monitors Server-Sent Events (SSE) until completion.

### Evaluation vs. `DEMO_PLAN.md`
The current demo is an abbreviated version (MVP) of the 13-phase plan outlined in `DEMO_PLAN.md`. 
**Missing functionality from the demo:**
- **AgentGraph & Dependencies**: We are triggering agents via separate `/graph/execute` endpoints rather than building a DAG (`graph.after("lint-main").run("docstring-main")`) natively.
- **TreeSitter Discovery**: Missing entirely from the demo; `target_code` and `file_path` are hardcoded in `api_demo.py`.
- **Workspace State Management**: We do not showcase snapshots or IPC KV interactions.
- **Interactive Mode**: No demonstration of an agent pausing to ask the user a question via inbox.

---

## 2. structured-agents & vLLM Utilization

The Remora bundles (`agents/lint/bundle.yaml` and `agents/docstring/bundle.yaml`) demonstrate significant usage of `structured-agents` and `vLLM` concepts.

**Features Fully Utilized:**
- **Inference Plugins**: Usage of the `function_gemma` plugin.
- **Adapter Configurations**: Specifying LoRA adapters like `google/functiongemma-270m-it`.
- **Structured Grammar**: EBNF mode for deterministic outputs.
- **Parallel Tool Calling**: Enabled via `allow_parallel_calls: true` allowing the agent to emit multiple tool calls at once.
- **Argument Parsing Policies**: Explicitly setting `args_format: permissive`.
- **Context Management**: Provisioning context scripts (`context/ruff_config.pym`, `context/docstring_style.pym`) into the system prompt.
- **Flow Control**: Multi-turn generation loop limits (`max_turns: 15`).

**Under-Utilized or Missing Features:**
- **Per-Call Dynamic Routing (LoRA multiplexing)**: The config sets a default adapter, but the demo does not showcase routing different tasks dynamically at runtime to specific vLLM adapters (e.g., using a testing specific adapter versus a docstring adapter in parallel).
- **Token Streaming**: While we listen to SSE event status (`agent:started`, `agent:completed`), we are not showcasing the granular token streaming of the LLM output.

---

## 3. Grail Functionality Utilization

The agent tools (e.g., `run_linter.pym`, `apply_fix.pym`, `read_current_docstring.pym`) are implemented as `.pym` scripts defining tools in the Grail registry.

**Features Fully Utilized:**
- **Input Directives**: Defining tool arguments explicitly using `Input("param", default=...)` syntax.
- **Host Decorators**: Seamless interop bridging execution bounds using the `@external` decorator (e.g., `read_file`, `run_json_command`, `run_command`).
- **Standardized Execution Results**: Handing back well-structured `result` dictionaries mapping `knowledge_delta` and `outcome`.

**Under-Utilized or Missing Features:**
- **Sub-Agent Pym Calling**: We do not currently demonstrate a Grail script spawning or interacting with another agent entirely through standard `grail` constructs.
- **Advanced State Management**: Limited demonstration of holding complex, persistent cross-turn state locally inside the script memory bounding.
- **Native Pydantic Inputs**: Instead of standard types, Grail can utilize rich `pydantic` types for input definitions which isn't showcased (the `agents/*` inputs usually cast directly using primitives like `str` and `bool` overrides inside the `bundle.yaml`).

---

## Summary Recommendations
1. **Extend the `api_demo.py`** (or create a new `full_demo.py`) to natively instantiate `AgentGraph`, `TreeSitterDiscoverer`, and `GraphWorkspace` bypassing HTTP to demonstrate the deep integrations Remora has.
2. Add an **Interactive Pause** step to show the `AgentInbox` working, fulfilling the vision in `TUI_DEMO_CONCEPT.md`.
3. Highlight **Dynamic Model Routing** with `structured-agents` by having the demo spin up two distinct adapter profiles at once.
