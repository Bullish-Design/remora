# HOW TO USE REMORA

This guide is a one stop shop for building applications with Remora. It explains the Remora core, the Datastar way (SSE + signals + DOM patches), and how to align everything with Stario so you can build real time apps without a JS framework.

If you are new to the stack, read in this order:
1. Remora stack overview
2. Remora core architecture
3. Datastar fundamentals
4. Stario fundamentals
5. Building your app on Remora + Datastar + Stario
6. Custom agents and bundles

---

## 1. Remora stack overview

Remora is an event driven agent orchestration layer for codebases. It discovers code nodes, runs structured agent bundles on each node, isolates work in Cairn workspaces, and streams structured events so UIs can render live progress.

The recommended stack for real time UI is:

- Remora: core agent graph, workspaces, event stream
- Datastar: client side signals + DOM patching over SSE
- Stario: server framework to render HTML and stream SSE updates

Mental model:

- Remora produces events. Your UI consumes events.
- Datastar is the wire format for live HTML patches and signal updates.
- Stario is the server framework that makes Datastar easy and explicit.

### 1.1 Compatibility and installation

Remora targets Python 3.13+ (`requires-python = ">=3.13"`). Stario requires Python 3.14+. If you want a Stario frontend, run it in a separate service while the Remora backend stays on 3.13 if needed.

Remora install options (from `docs/INSTALLATION.md`):

- `pip install remora`: core runtime (EventBus, workspaces, CLI). No structured agents or vLLM.
- `pip install "remora[backend]"`: adds structured agents, vLLM, xgrammar, openai.
- `pip install "remora[full]"`: convenience meta extra.

If you want to run agents locally, you need the backend extra. If you only consume events via the service endpoints, the core runtime is enough.

---

## 2. Remora core architecture (what it does and how)

### 2.1 Discovery and node graph

- Remora parses source files using tree sitter queries in `src/remora/queries/`.
- Every discovered code element becomes a `CSTNode` with stable ids and location.
- `build_graph()` maps nodes to bundles based on `remora.yaml` bundle mapping.
- Dependencies are computed by file relationships (functions depend on their file node).
- The result is a topologically sorted list of `AgentNode` objects.

Discovery specifics:

- Language detection is by file extension (see `LANGUAGE_EXTENSIONS` in `src/remora/core/discovery.py`).
- If tree sitter is missing for a language, Remora falls back to a file level node.
- If query packs are missing for a language, Remora still creates a file node.
- Node ids are deterministic SHA256 hashes of file path + name + line range.

Key types:
- `CSTNode`: immutable data about a code element
- `AgentNode`: immutable graph node with dependencies and bundle path

Why it matters:
- You can target only specific node types (file, class, function, method).
- Bundles can have priorities to run earlier.
- A graph enables bounded concurrency while honoring dependencies.

### 2.2 Graph execution and error policy

`GraphExecutor` runs the graph in dependency order with bounded concurrency.

- Configured with `ExecutionConfig` (concurrency, timeout, max turns, error policy).
- Emits graph and agent lifecycle events into the `EventBus`.
- Uses the Remora `ContextBuilder` to build prompt context for each node.

Error handling modes (from `remora.config.ErrorPolicy`):
- `stop_graph`: stop on first failure
- `skip_downstream`: skip dependent nodes when a node fails
- `continue`: keep going regardless of failures

### 2.3 Event bus (the center of the system)

The `EventBus` is the backbone of Remora.

- Implements the structured agents `Observer` protocol.
- Receives kernel events from structured agents (model requests, tool calls).
- Emits Remora events (graph start, agent complete, human input requests).
- Supports `stream()` for SSE / WebSocket consumers.

Key event types (from `src/remora/core/events.py`):
- Graph: `GraphStartEvent`, `GraphCompleteEvent`, `GraphErrorEvent`
- Agent: `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`, `AgentSkippedEvent`
- Human: `HumanInputRequestEvent`, `HumanInputResponseEvent`
- Kernel: `ModelRequestEvent`, `ToolResultEvent`, etc (re-exported from structured agents)

If you want a UI, analytics, or logs, you can subscribe to the EventBus in-process or use `/events` and `/subscribe` from the Remora service.

EventBus streaming notes:

- `stream()` is an async context manager that yields an async iterator.
- It does not backfill history. If you need state, build it in your consumer (or use `UiStateProjector`).

### 2.4 Context builder (two track memory)

`ContextBuilder` listens to the EventBus and builds a prompt context.

- Short track: recent tool results and agent actions.
- Long track: persistent summaries from completed agents.
- `build_context_for(node)` injects recent actions and prior analysis.

This is how Remora keeps each agent aware of recent work without making the prompt huge.

### 2.5 Workspaces (Cairn integration)

Remora uses Cairn to isolate changes per agent.

- A stable workspace is synced from your project root.
- Each agent gets a copy on write workspace backed by a separate sqlite DB.
- Reads fall back to the stable workspace if a file was not touched.
- Writes are isolated in the agent workspace.
- Workspaces live under `workspace.base_path` (default `.remora/workspaces/<graph_id>`).
- The stable workspace sync skips common ignore dirs (`.git`, `.venv`, `node_modules`, `.remora`, etc).

Cairn integration layers:
- `CairnWorkspaceService`: manages stable + per agent workspaces.
- `AgentWorkspace`: safe read / write wrapper.
- `CairnDataProvider`: loads files for Grail tool execution.
- `CairnResultHandler`: persists tool outputs back to workspace.

Important limitation:
- Workspace snapshots are not supported by the current Cairn API.
- Checkpoints store metadata only (see `src/remora/core/checkpoint.py`).

### 2.6 Tools and Grail integration

Remora uses Grail `.pym` tools for agent actions.

- `.pym` scripts declare `Input()` parameters (builds JSON schemas).
- Remora loads scripts and builds tool schemas automatically.
- External functions are injected from `CairnExternals`.

Default externals available in `.pym` tools:
- `read_file`, `write_file`, `list_dir`, `file_exists`
- `search_files`, `search_content`
- `submit_result`, `log`

`submit_result` writes a submission record into the Cairn workspace. Remora reads
this summary after the agent completes and surfaces it in the dashboard and context.

Remora runs tools through structured agents. It can either:
- Send tool schemas to the model (native OpenAI style tool calls), or
- Avoid sending schemas and parse XML tool calls (legacy / Qwen XML parser)

This is controlled by `grammar.send_tools_to_api` in the bundle.

### 2.7 Structured agents integration

Remora does not implement a custom LLM loop. It uses structured agents.

Key pieces:
- `ModelAdapter` for request formatting + response parsing
- `AgentKernel` to run multi turn tool calling
- `ConstraintPipeline` for structured output constraints

Remora supplies:
- `base_url`, `api_key`, and `model` from config
- tool schemas derived from `.pym` tools
- the EventBus observer
- `max_turns` from bundle (if set) or from `execution.max_turns`

### 2.8 Path normalization and virtual FS

Remora normalizes file paths so tools can operate on a stable virtual FS:

- `PathResolver` converts absolute paths into workspace relative POSIX paths.
- `CairnDataProvider` loads files into a virtual FS for Grail.
- `build_virtual_fs()` adds both `path` and `/path` variants for tool lookup.

In practice, tools should use relative paths. Remora will map them to the right workspace paths.

### 2.9 Checkpoints and resume

`CheckpointManager` stores execution metadata so you can resume a graph:

- Saved metadata: node state, results, pending, failed, skipped.
- Not saved: workspace file contents (Cairn does not support snapshots yet).

Use checkpoints for recovery and diagnostics, not full workspace restore.

### 2.10 Indexer and related code

The indexer is an optional background daemon (`remora-index`) that watches files and updates a symbol store.

- Config: `indexer.watch_paths`, `indexer.store_path` in `remora.yaml`.
- Uses watchfiles and fsdantic to track node state.
- When available, the ContextBuilder can pull related code into prompts.

### 2.11 Service UI (Starlette + Datastar reference)

Remora ships a Datastar reference UI through the service layer.

- UI rendering lives in `src/remora/ui/` (`UiStateProjector`, `render_dashboard`).
- Service endpoints live in `src/remora/service/` and are exposed via `remora.adapters.starlette.create_app`.
- `/subscribe` streams Datastar patch events (DatastarResponse).
- `/events` streams raw JSON SSE events.
- `/run` starts a graph execution.
- `/input` posts human responses.

This is the in-repo reference for Datastar. External frontends (Stario or other)
consume `/subscribe` and `/events` from a separate service.

---

## 3. Remora server and model stack

Remora expects an OpenAI compatible model server. The reference stack is in `server/`.

### 3.1 vLLM server (reference)

- Uses `vllm/vllm-openai` Docker image.
- Exposes OpenAI compatible API at `http://remora-server:8000/v1`.
- Uses Tailscale for LAN or remote networking.

Bring up:

```bash
cd server
docker compose up -d --build
uv run server/test_connection.py
```

### 3.2 Optional agents server

The `agents-server` container can serve bundles for remote clients.

```bash
curl http://remora-server:8001/agents/lint/bundle.yaml
```

### 3.3 Hot load adapters

```bash
python server/adapter_manager.py --name lint --path /models/adapters/lint
```

### 3.4 Remora config defaults

Default model server settings are in `docs/CONFIGURATION.md`:

- `model.base_url`: `http://remora-server:8000/v1`
- `model.api_key`: use `EMPTY` for local servers
- `model.default_model`: e.g. `Qwen/Qwen3-4B`

---

## 4. Remora configuration (remora.yaml)

A minimal `remora.yaml`:

```yaml
bundles:
  path: agents
  mapping:
    function: lint/bundle.yaml
    class: docstring/bundle.yaml
    file: lint/bundle.yaml

discovery:
  paths: ["src/"]
  languages: ["python"]
  max_workers: 4

model:
  base_url: "http://remora-server:8000/v1"
  api_key: "EMPTY"
  default_model: "Qwen/Qwen3-4B"

execution:
  max_concurrency: 4
  error_policy: skip_downstream
  timeout: 300
  max_turns: 8
  truncation_limit: 1024

workspace:
  base_path: ".remora/workspaces"
  cleanup_after: "1h"
```

Environment overrides:

- `REMORA_MODEL_BASE_URL`
- `REMORA_MODEL_API_KEY`
- `REMORA_MODEL_DEFAULT`
- `REMORA_EXECUTION_MAX_CONCURRENCY`
- `REMORA_EXECUTION_TIMEOUT`
- `REMORA_WORKSPACE_BASE_PATH`

---

## 5. Running Remora

### 5.1 CLI run

```bash
remora run src/
```

What happens:

- Remora discovers nodes in `src/`.
- It builds a graph using the bundle mapping.
- It executes bundles with bounded concurrency.
- Events are emitted for every agent and tool call.

### 5.2 Service

```bash
remora serve --host 0.0.0.0 --port 8420
```

Use this to confirm your event stream before building a custom UI.

### 5.3 Programmatic usage

```python
import asyncio
from pathlib import Path

from remora.core.config import load_config
from remora.core.discovery import discover
from remora.core.event_bus import EventBus
from remora.core.graph import build_graph
from remora.core.executor import GraphExecutor

async def main() -> None:
    config = load_config()
    nodes = discover(list(config.discovery.paths))
    bundle_root = Path(config.bundles.path)
    bundle_mapping = {
        node_type: bundle_root / bundle
        for node_type, bundle in config.bundles.mapping.items()
    }
    graph = build_graph(nodes, bundle_mapping)
    event_bus = EventBus()
    executor = GraphExecutor(config=config, event_bus=event_bus)
    results = await executor.run(graph, "example-run")
    print(f"Completed {len(results)} agents")

asyncio.run(main())
```

### 5.4 Indexer daemon

```bash
remora-index src/
```

Use this if you want related code and symbol context for prompts or dashboards.

---

## 6. Datastar fundamentals (the Datastar way)

Datastar is a minimal client side runtime that uses SSE for real time UI.

Core ideas:

- Every request can return 0..N SSE events.
- Events patch DOM elements or update reactive signals.
- HTML + signals are the source of truth, not client side JS state.

### 6.1 SSE events

Datastar uses SSE events like:

- `datastar-patch-elements`: send HTML fragments, patch by id or selector
- `datastar-patch-signals`: send JSON to update signals
- `datastar-redirect`, `datastar-script`, etc

The Python SDK (`datastar_py`) provides:

- `ServerSentEventGenerator` for building event lines
- `DatastarResponse` wrappers for frameworks
- `read_signals()` to read client signals
- `attribute_generator` to generate data attributes

Datastar SSE responses should use these headers (provided by the SDK):

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `X-Accel-Buffering: no`

### 6.2 Signals

Signals are client side reactive state. They are synced to the server:

- GET requests: signals are encoded in the `datastar` query parameter
- POST requests: signals are sent as JSON with the `Datastar-Request` header

On the server, read them with `read_signals()` (datastar_py) or
`c.signals()` (Stario).

### 6.3 Patch vs sync

Two ways to update the UI:

- Patch elements: send HTML to update a DOM fragment
- Sync signals: send JSON updates and let bound elements update

Use patch for structural changes. Use sync for small state updates.

### 6.4 Attribute helpers

Datastar attributes (generated by helpers):

- `data.signals({})` initialize signals
- `data.bind("signal")` two way binding
- `data.text("$signal")` text binding
- `data.on("click", "...")` event handler
- `data.init("@get('/subscribe')")` run on mount

These are the foundation for Stario + Datastar views.

---

## 7. Stario fundamentals (the Stario way)

Stario is a real time hypermedia framework. It is built for Datastar.

### 7.1 Handler signature

Every handler is explicit:

```python
async def handler(c: Context, w: Writer) -> None:
    ...
```

- `Context`: request data and signals
- `Writer`: all response and SSE streaming actions

### 7.1.1 Context access

`Context` is your request surface:

- `c.req.method`, `c.req.path`, `c.req.query`, `c.req.headers`, `c.req.cookies`
- `await c.req.json()` for JSON bodies
- `await c.signals()` for Datastar signals

Signals can be parsed into a dataclass shape if you want typed access.

### 7.2 Writer methods

One shot responses:

- `w.html(el)`
- `w.json(data)`
- `w.text(text)`
- `w.redirect(url)`

Datastar streaming:

- `w.patch(el)`
- `w.sync(data)`
- `w.navigate(url)`
- `w.execute(js)`
- `w.remove(selector)`

### 7.2.1 Actions and attributes

Stario exposes Datastar helpers directly:

- `data.*` for attributes (signals, bind, text, on, init)
- `at.*` for actions (get, post, put, patch, delete)

Example:

```python
from stario import data, at
from stario.html import Button

Button(data.on("click", at.post("/run")), "Run")
```

### 7.3 Long lived connections

Use `w.alive()` to keep a stream open and exit cleanly on disconnect
or server shutdown.

```python
async def subscribe(c: Context, w: Writer) -> None:
    async for msg in w.alive(relay.subscribe("updates")):
        w.patch(render(msg))
```

### 7.4 Storyboard approach

Stario encourages server rendered snapshots over client diff logic.

- Render the full UI state as HTML.
- Stream patches over SSE.
- Let Datastar morph the DOM.

This reduces client side state and eliminates sync bugs.

### 7.5 Dependency injection pattern

Use closures to pass dependencies (no DI containers):

```python
def make_handlers(db):
    async def handler(c: Context, w: Writer) -> None:
        user = await db.load(...)
        w.json(user)
    return handler
```

This makes handlers testable and explicit.

### 7.6 Server runtime

Stario runs with `app.serve()` or by constructing `Server` directly.

- Supports multiple worker threads (one event loop per worker).
- Uses a graceful shutdown that works well with SSE streams.
- Use uvloop in production for better performance.

---

## 8. Aligning Remora with Datastar + Stario

Remora already has an event bus. Stario can consume it and expose a
Datastar UI in a few steps.

### 8.1 Recommended architecture

- Remora runs the graph and exposes `/subscribe` and `/events`.
- A Stario frontend connects to the Remora service over HTTP (or proxies the stream).
- Datastar updates the UI via signals and DOM patches.
- Human input flows back to Remora via `/input`.

### 8.2 Minimal Stario dashboard skeleton

This is a small proxy that forwards Remora's Datastar stream and endpoints.
For a complete example, see `examples/stario_reference/app.py`.

```python
import asyncio
import os

import httpx
from stario import Context, RichTracer, Stario, Writer, at, data
from stario.html import Body, Div, Head, Html, Script, Title

REMORA_URL = os.environ.get("REMORA_URL", "http://localhost:8420")


def page(*children):
    return Html(
        {"lang": "en"},
        Head(
            Title("Remora Dashboard"),
            Script(
                {
                    "type": "module",
                    "src": "https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js",
                }
            ),
        ),
        Body(
            data.init(at.get("/subscribe")),
            *children,
        ),
    )


async def index(_c: Context, w: Writer) -> None:
    w.html(page(Div({"id": "remora-root"}, "Connecting...")))


async def subscribe(_c: Context, w: Writer) -> None:
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", f"{REMORA_URL}/subscribe") as response:
            async for chunk in response.aiter_text():
                w.raw(chunk)


async def run(c: Context, w: Writer) -> None:
    payload = await c.req.json()
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{REMORA_URL}/run", json=payload)
    w.json(response.json())


async def submit_input(c: Context, w: Writer) -> None:
    payload = await c.req.json()
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{REMORA_URL}/input", json=payload)
    w.json(response.json())


async def main() -> None:
    with RichTracer() as tracer:
        app = Stario(tracer)
        app.get("/", index)
        app.get("/subscribe", subscribe)
        app.post("/run", run)
        app.post("/input", submit_input)
        await app.serve(port=9000)


if __name__ == "__main__":
    asyncio.run(main())
```

Why this works:

- The UI connects once using `data.init(@get('/subscribe'))`.
- Stario proxies Remora's Datastar patch stream to the browser.
- `/run` and `/input` forward JSON payloads to Remora.

This keeps Remora on Python 3.13 while Stario runs separately on 3.14+.

---

## 9. Creating custom agents

Custom agents are created by defining bundles and tools.

### 9.1 Bundle layout

A typical bundle looks like:

```
agents/
  my_agent/
    bundle.yaml
    tools/
      read_file.pym
      write_file.pym
      submit_result.pym
```

### 9.2 Bundle configuration

Example `bundle.yaml`:

```yaml
name: my_agent
model: qwen

initial_context:
  system_prompt: |
    You are a code review agent. Identify risks and propose fixes.

grammar:
  strategy: ebnf
  allow_parallel_calls: false
  send_tools_to_api: true

agents_dir: tools
termination: submit_result
max_turns: 6

node_types:
  - function
  - class
priority: 10
requires_context: true
```

Important fields:

- `initial_context.system_prompt`: base system prompt
- `grammar.send_tools_to_api`: if false, tool schemas are not sent to the model
- `agents_dir`: path to tool scripts
- `termination`: tool name that ends the run (convention)
- `node_types`: node types this bundle supports
- `requires_context`: whether Remora should inject context
- `model`: bundle adapter name (structured agents) and optional model override in YAML

Model override note:

Remora will look for a model override in the bundle YAML under `model.id`, `model.name`,
or `model.model`. If none are present, it falls back to `model.default_model` in config.

### 9.3 Tool scripts (.pym)

Tools are Grail scripts. Each script declares inputs and externals.

Example `submit_result.pym`:

```python
from grail import Input, external

@external
async def submit_result(summary: str, changed_files: list[str]) -> bool:
    ...

summary: str = Input("summary")
changed_files: list[str] = Input("changed_files")

await submit_result(summary, changed_files)
{"status": "ok", "summary": summary, "changed_files": changed_files}
```

Remora injects externals from Cairn. If you declare `@external` with one of the
supported names, it will be provided.

Tool discovery notes:

- Remora loads every `.pym` file in `agents_dir` (top level only).
- Keep that directory focused on tool scripts to avoid accidental tools.

### 9.4 Validating tools

Use Grail to validate `.pym` scripts and generate `inputs.json`:

```bash
grail check agents/my_agent/tools/read_file.pym
```

This helps tool schemas stay in sync with tool inputs.

### 9.5 Mapping bundles to node types

In `remora.yaml`:

```yaml
bundles:
  path: agents
  mapping:
    function: my_agent/bundle.yaml
    class: my_agent/bundle.yaml
```

### 9.6 Tool calling modes (important)

- `send_tools_to_api: true` (default): tool schemas are sent to the model
- `send_tools_to_api: false`: tool schemas are not sent; model must emit XML calls

If you are using Qwen models with XML tool calling, set `send_tools_to_api: false`.
If you want OpenAI style tool calls, set it to true and ensure the model supports it.

Note: structured output constraints are only attached when tool schemas are sent.
If `send_tools_to_api` is false, constraints are not applied.

---

## 10. Example use cases and toy architectures

These are conceptual examples of how to use the Remora stack.

### 10.1 Code hygiene pipeline

Goal: Run lint, docstrings, and tests across a repo.

Architecture:

- Remora discovers nodes and builds a graph.
- Bundles: lint, docstring, test.
- Stario dashboard shows live progress and events.

Toy structure:

```
remora.yaml
agents/
  lint/
  docstring/
  test/
app/
  frontend.py
```

Execution flow:

1. `remora run src/` or a Stario /run endpoint triggers graph execution.
2. Each agent writes to its workspace.
3. `submit_result` summarizes changes.
4. UI shows progress from the EventBus (via `/events` or `/subscribe`).

### 10.2 Live code review assistant

Goal: Run review agents on every PR or branch.

Architecture:

- Remora runs on CI or locally.
- Stario dashboard renders review notes live.
- Use Datastar signals for filters (files, severity).

Toy UI flow:

- `data.signals({"severity": "all"})`
- `data.on("change", at.get("/filter"))`
- `w.sync({"severity": "high"})` updates view filters

### 10.3 Interactive refactor coach

Goal: Ask humans for decisions mid run.

Architecture:

- Tools emit `HumanInputRequestEvent` when blocked.
- Stario UI renders a form for responses.
- `/input` posts `HumanInputResponseEvent`.

Toy pattern:

- UI listens to event stream and renders questions.
- User response flows back through `/input`.

### 10.4 Knowledge indexer

Goal: Keep a live index of code symbols.

Architecture:

- Run `remora-index` to start the indexer daemon.
- UI subscribes to index changes and shows related code per node.
- Use Datastar to patch a right side panel.

### 10.5 Agent marketplace UI

Goal: Let users browse and run bundles on demand.

Architecture:

- Stario UI lists bundles from `agents/`.
- Datastar signals filter by node type, priority, and tools.
- A `/run` endpoint triggers a graph run with a selected bundle mapping.

---

## 11. Best practices and gotchas

### Remora specific

- Ensure `model.base_url` is reachable (most errors are server connectivity).
- Set `max_concurrency` based on GPU capacity and tool load.
- Use `skip_downstream` if failures should not halt the graph.
- Use `requires_context: true` for agents that need recent activity summaries.
- Keep tools small and focused. Let the model orchestrate, not replace tools.
- Add explicit `submit_result` tools so results show up in dashboards.

### Datastar specific

- Use `w.sync` for simple state updates and `w.patch` for layout changes.
- Ensure patched elements have stable `id` values.
- Use `data.init(@get('/subscribe'))` for SSE connections.
- Avoid large signals. Keep them small and scoped to UI state.

### Stario specific

- Keep handlers explicit: Context in, Writer out.
- Use closures for dependencies, not globals.
- Use `w.alive()` for long SSE connections and cleanup.
- Render snapshots instead of incremental JSON diffs.

---

## 12. Testing and validation

- Unit tests: `pytest tests/unit/ -v`
- Integration tests: `pytest tests/integration/ -v` (requires a running vLLM server)
- Service smoke: run `remora serve` and load `/` in the browser

---

## 13. Key references

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/CONFIGURATION.md`
- `docs/HOW_TO_CREATE_AN_AGENT.md`
- `docs/HOW_TO_USE_GRAIL.md`
- `docs/HOW_TO_USE_STRUCTURED_AGENTS.md`
- `server/README.md`
- `src/remora/ui/` and `src/remora/service/` (Datastar reference UI + service layer)
- `examples/stario_reference/` (external Stario proxy template)
