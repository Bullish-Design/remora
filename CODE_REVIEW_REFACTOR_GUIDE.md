# Remora Refactor Implementation Guide (Junior Dev, Expanded)

This is the exact, step-by-step plan to implement all fixes and refactors from `CODE_REVIEW.md`. It gives file paths, functions to edit, and code snippets to paste. Follow the steps in order.

Important rules for this refactor:
- No backwards compatibility. Remove graph-era features completely.
- Swarm-first: EventStore + SubscriptionRegistry + SwarmState + AgentRunner are the core.
- EventStore is the only write path for events. EventBus is notification only.
- Use project-relative POSIX paths for all file paths in events and subscriptions.

--------------------------------------------------------------------------------

## 0) Preflight Checklist

Before you change code:
1. Read `CODE_REVIEW.md` and this guide end-to-end.
2. Run these discovery commands (do not edit yet):
   - `rg -n "GraphExecutor|build_graph|GraphStartEvent|GraphCompleteEvent|GraphErrorEvent" src tests`
   - `rg -n "indexer|checkpoint|streaming_sync|WorkspaceManager|EventBridge" src tests docs README.md HOW_TO_USE_REMORA.md`
   - `rg -n "swarm" src/remora`
3. Keep a running list of every file you touch.

--------------------------------------------------------------------------------

## 1) Fix EventStore Trigger Wiring (Blocking Bug)

### Goal
If subscriptions are set after `EventStore.initialize()`, the trigger queue must still be created.

### File
`src/remora/core/event_store.py`

### Exact changes

1) Update `set_subscriptions()` to create `_trigger_queue` if missing.

Replace the method with:
```python
    def set_subscriptions(self, subscriptions: "SubscriptionRegistry") -> None:
        """Set the subscription registry for trigger matching."""
        self._subscriptions = subscriptions
        if self._trigger_queue is None:
            self._trigger_queue = asyncio.Queue()
```

2) Make `get_triggers()` fail loudly if subscriptions are not configured.

Replace the start of `get_triggers()` with:
```python
    async def get_triggers(self) -> AsyncIterator[tuple[str, int, RemoraEvent]]:
        """Iterate over event triggers for matched subscriptions."""
        if self._trigger_queue is None:
            raise RuntimeError("EventStore subscriptions not configured")
```

### Acceptance
- `EventStore.get_triggers()` yields triggers after `set_subscriptions()` is called post-init.

--------------------------------------------------------------------------------

## 2) Wire AgentRunner into Swarm Startup (Blocking Bug)

### Goal
`remora swarm start` must reconcile and run the reactive runner loop.

### File
`src/remora/cli/main.py`

### Exact changes

Inside `swarm_start()`, replace the current `_start()` body with the following structure.
Keep all error handling and click messages, but update logic as shown.

```python
    async def _start() -> None:
        from remora.core.event_bus import EventBus
        from remora.core.event_store import EventStore
        from remora.core.swarm_state import SwarmState
        from remora.core.subscriptions import SubscriptionRegistry
        from remora.core.reconciler import reconcile_on_startup
        from remora.core.agent_runner import AgentRunner

        swarm_path = root / ".remora"
        event_store_path = swarm_path / "events" / "events.db"
        subscriptions_path = swarm_path / "subscriptions.db"
        swarm_state_path = swarm_path / "swarm_state.db"

        event_bus = EventBus()
        subscriptions = SubscriptionRegistry(subscriptions_path)
        swarm_state = SwarmState(swarm_state_path)
        event_store = EventStore(
            event_store_path,
            subscriptions=subscriptions,
            event_bus=event_bus,
        )

        await event_store.initialize()
        await subscriptions.initialize()
        swarm_state.initialize()

        click.echo("Reconciling swarm...")
        result = await reconcile_on_startup(
            root,
            swarm_state,
            subscriptions,
            event_store=event_store,
            swarm_id=config.swarm_id,
        )
        click.echo(
            f"Swarm reconciled: {result['created']} new, "
            f"{result['orphaned']} orphaned, {result['total']} total"
        )

        runner = AgentRunner(
            event_store=event_store,
            subscriptions=subscriptions,
            swarm_state=swarm_state,
            config=config,
            event_bus=event_bus,
            project_root=root,
        )
        runner_task = asyncio.create_task(runner.run_forever())

        nvim_server = None
        if nvim:
            from remora.nvim.server import NvimServer

            nvim_socket = swarm_path / "nvim.sock"
            nvim_server = NvimServer(
                nvim_socket,
                event_store=event_store,
                subscriptions=subscriptions,
                event_bus=event_bus,
                project_root=root,
            )
            await nvim_server.start()
            click.echo(f"Neovim server started on {nvim_socket}")

        click.echo("Swarm started. Press Ctrl+C to stop.")

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            runner_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner_task
            await runner.stop()
            if nvim_server:
                await nvim_server.stop()
```

### Acceptance
- `remora swarm start` keeps a runner task active and can process new events.

--------------------------------------------------------------------------------

## 3) Make AgentRunner Real (Remove Stub Execution)

### Goal
AgentRunner must execute real agent turns and emit lifecycle events through EventStore.

### Files
- `src/remora/core/agent_runner.py`
- New: `src/remora/core/swarm_executor.py`
- `src/remora/core/agent_state.py`
- `src/remora/core/swarm_state.py`
- `src/remora/core/reconciler.py`
- `src/remora/core/events.py`

### 3.1 Add missing identity fields to AgentState

#### File
`src/remora/core/agent_state.py`

#### Exact changes
Update `AgentState` to include `name` and `full_name`:
```python
@dataclass
class AgentState:
    agent_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    parent_id: str | None = None
    range: tuple[int, int] | None = None
    ...
```

Update `from_dict()` and `to_dict()` remain the same (dataclasses handles new fields automatically).

### 3.2 Update SwarmState schema to include names

#### File
`src/remora/core/swarm_state.py`

Add fields to `AgentMetadata`:
```python
@dataclass
class AgentMetadata:
    agent_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    parent_id: str | None = None
    start_line: int = 1
    end_line: int = 1
```

Update DB schema in `initialize()`:
```python
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    parent_id TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
```

Update all inserts/updates to include `name` and `full_name`.

### 3.3 Update reconciler to populate name/full_name

#### File
`src/remora/core/reconciler.py`

When building `AgentMetadata`, pass `node.name` and `node.full_name`.
Also update `AgentState` creation to set `name` and `full_name`.

Exact snippet in the create loop:
```python
        metadata = AgentMetadata(
            agent_id=node.node_id,
            node_type=node.node_type,
            name=node.name,
            full_name=node.full_name,
            file_path=node.file_path,
            parent_id=None,
            start_line=node.start_line,
            end_line=node.end_line,
        )

        state = AgentState(
            agent_id=node.node_id,
            node_type=node.node_type,
            name=node.name,
            full_name=node.full_name,
            file_path=node.file_path,
            range=(node.start_line, node.end_line),
        )
```

### 3.4 Create SwarmExecutor (new file)

#### File
`src/remora/core/swarm_executor.py`

Create this new module (copy the key logic from `executor.py` but single-agent only). The snippet below uses the flat config fields from Step 6.
```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from structured_agents.agent import get_response_parser, load_manifest
from structured_agents.client import build_client
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter
from structured_agents.types import Message

from remora.core.agent_state import AgentState
from remora.core.context import ContextBuilder
from remora.core.discovery import CSTNode
from remora.core.event_store import EventSourcedBus, EventStore
from remora.core.tools.grail import build_virtual_fs, discover_grail_tools
from remora.core.workspace import CairnDataProvider
from remora.core.cairn_bridge import CairnWorkspaceService
from remora.utils import PathResolver, truncate


class SwarmExecutor:
    def __init__(
        self,
        config: Any,
        event_bus: Any,
        event_store: EventStore,
        swarm_id: str,
        project_root: Path,
    ):
        self.config = config
        self._event_bus = EventSourcedBus(event_bus, event_store, swarm_id)
        self.context_builder = ContextBuilder()
        self._path_resolver = PathResolver(project_root)
        self._event_bus.subscribe_all(self.context_builder.handle)
        self._workspace_service = CairnWorkspaceService(
            config=self.config,
            swarm_root=Path(self.config.swarm_root),
            project_root=self._path_resolver.project_root,
        )

    async def run_agent(self, state: AgentState, swarm_id: str) -> str:
        bundle_path = self._resolve_bundle_path(state)
        manifest = load_manifest(bundle_path)

        await self._workspace_service.initialize()
        workspace = await self._workspace_service.get_agent_workspace(state.agent_id)
        externals = self._workspace_service.get_externals(state.agent_id, workspace)

        data_provider = CairnDataProvider(workspace, self._path_resolver)
        node = _state_to_cst_node(state)
        files = await data_provider.load_files(node)

        prompt = self._build_prompt(state, node, files, requires_context=getattr(manifest, "requires_context", True))

        async def files_provider() -> dict[str, str | bytes]:
            current_files = await data_provider.load_files(node)
            return build_virtual_fs(current_files)

        tools = discover_grail_tools(
            manifest.agents_dir,
            externals=externals,
            files_provider=files_provider,
        )

        model_name = self._resolve_model_name(bundle_path, manifest)
        result = await self._run_kernel(manifest, prompt, tools, model_name=model_name)

        return truncate(str(result), max_len=self.config.truncation_limit)

    def _resolve_bundle_path(self, state: AgentState) -> Path:
        bundle_root = Path(self.config.bundle_root)
        mapping = self.config.bundle_mapping
        if state.node_type not in mapping:
            raise ValueError(f"No bundle mapping for node_type: {state.node_type}")
        return bundle_root / mapping[state.node_type]

    def _resolve_model_name(self, bundle_path: Path, manifest: Any) -> str:
        path = bundle_path / "bundle.yaml" if bundle_path.is_dir() else bundle_path
        override = None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            model_data = data.get("model")
            if isinstance(model_data, dict):
                override = model_data.get("id") or model_data.get("name") or model_data.get("model")
        except Exception:
            override = None
        if override:
            return str(override)
        return self.config.model_default or getattr(manifest, "model", "")

    async def _run_kernel(self, manifest: Any, prompt: str, tools: list[Any], *, model_name: str) -> Any:
        parser = get_response_parser(manifest.model)
        pipeline = ConstraintPipeline(manifest.grammar_config) if manifest.grammar_config else None
        adapter = ModelAdapter(name=manifest.model, response_parser=parser, constraint_pipeline=pipeline)
        client = build_client(
            {
                "base_url": self.config.model_base_url,
                "api_key": self.config.model_api_key or "EMPTY",
                "model": model_name,
                "timeout": self.config.timeout_s,
            }
        )
        kernel = AgentKernel(client=client, adapter=adapter, tools=tools, observer=self._event_bus)
        try:
            messages = [
                Message(role="system", content=manifest.system_prompt),
                Message(role="user", content=prompt),
            ]
            tool_schemas = [tool.schema for tool in tools]
            if manifest.grammar_config and not manifest.grammar_config.send_tools_to_api:
                tool_schemas = []
            max_turns = getattr(manifest, "max_turns", None) or self.config.max_turns
            return await kernel.run(messages, tool_schemas, max_turns=max_turns)
        finally:
            await kernel.close()

    def _build_prompt(self, state: AgentState, node: CSTNode, files: dict[str, str], *, requires_context: bool) -> str:
        sections: list[str] = []
        sections.append(f"# Target: {state.full_name}")
        sections.append(f"File: {state.file_path}")
        if state.range:
            sections.append(f"Lines: {state.range[0]}-{state.range[1]}")
        code = files.get(self._path_resolver.to_workspace_path(state.file_path)) or files.get(state.file_path)
        if code is not None:
            sections.append("")
            sections.append("## Code")
            sections.append("```")
            sections.append(code)
            sections.append("```")
        if requires_context:
            context = self.context_builder.build_context_for(node)
            if context:
                sections.append(context)
        return "\n".join(sections)


def _state_to_cst_node(state: AgentState) -> CSTNode:
    start_line = state.range[0] if state.range else 1
    end_line = state.range[1] if state.range else 1
    return CSTNode(
        node_id=state.agent_id,
        node_type=state.node_type,
        name=state.name,
        full_name=state.full_name,
        file_path=state.file_path,
        text="",
        start_line=start_line,
        end_line=end_line,
        start_byte=0,
        end_byte=0,
    )
```

### 3.5 Update AgentRunner to use SwarmExecutor and EventStore

#### File
`src/remora/core/agent_runner.py`

Make the following edits:
1) Add `swarm_id` and `swarm_executor` fields.
```python
from remora.core.swarm_executor import SwarmExecutor

class AgentRunner:
    def __init__(..., config: Config, ...):
        ...
        self._swarm_id = config.swarm_id
        self._executor = SwarmExecutor(
            config=config,
            event_bus=event_bus,
            event_store=event_store,
            swarm_id=self._swarm_id,
            project_root=self._project_root,
        )
```

2) Read cooldown and depth from the flat config:
```python
        self._max_concurrency = config.max_concurrency
        self._max_trigger_depth = config.max_trigger_depth
        self._trigger_cooldown_ms = config.trigger_cooldown_ms
```

3) Replace EventBus-only emissions with EventStore.append() calls.
Example in `_execute_turn()`:
```python
        await self._event_store.append(
            self._swarm_id,
            AgentStartEvent(
                graph_id=self._swarm_id,
                agent_id=agent_id,
                node_name=state.node_type,
            ),
        )
```
Also update `_emit_error()`:
```python
    async def _emit_error(self, agent_id: str, error: str) -> None:
        await self._event_store.append(
            self._swarm_id,
            AgentErrorEvent(
                graph_id=self._swarm_id,
                agent_id=agent_id,
                error=error,
            ),
        )
```

4) Replace `_run_agent()` with:
```python
    async def _run_agent(self, context: ExecutionContext) -> Any:
        return await self._executor.run_agent(context.state, self._swarm_id)
```

### Acceptance
- Triggering `AgentMessageEvent` executes a real agent turn and persists events to EventStore.

--------------------------------------------------------------------------------

## 4) Fix Neovim JSON-RPC Server Binding and Notifications

### Goal
Fix handler binding and broadcast notifications.

### File
`src/remora/nvim/server.py`

### Exact changes

1) Update constructor to accept EventBus and project_root, and bind handlers:
```python
from remora.core.event_bus import EventBus

class NvimServer:
    def __init__(..., event_bus: EventBus | None = None, project_root: PathLike | None = None):
        ...
        self._event_bus = event_bus
        self._project_root = normalize_path(project_root or Path.cwd())
        self._handlers = {
            "swarm.emit": self._handle_swarm_emit,
            "agent.select": self._handle_agent_select,
            "agent.chat": self._handle_agent_chat,
            "agent.subscribe": self._handle_agent_subscribe,
            "agent.get_subscriptions": self._handle_agent_get_subscriptions,
        }
```

2) Subscribe to EventBus in `start()`:
```python
    async def start(self) -> None:
        ...
        if self._event_bus is not None:
            self._event_bus.subscribe_all(self._broadcast_event)
```

3) Unsubscribe on stop (optional, but do it):
```python
    async def stop(self) -> None:
        if self._event_bus is not None:
            self._event_bus.unsubscribe(self._broadcast_event)
```

### Acceptance
- JSON-RPC requests respond normally.
- Clients receive `event.subscribed` notifications.

--------------------------------------------------------------------------------

## 5) Remove Graph-Era APIs and Services (No Backwards Compatibility)

### Goal
Delete all graph execution code, CLI, tests, and docs.

### Files to delete
Remove these files entirely:
- `src/remora/core/executor.py`
- `src/remora/core/graph.py`
- `tests/integration/test_executor_real.py`
- `tests/integration/test_error_policy_real.py`
- `tests/integration/test_long_running_graph_real.py`
- `tests/integration/test_complex_graph_topologies_real.py`
- Any tests that import `GraphExecutor` or `build_graph`

### Files to edit

1) `src/remora/cli/main.py`
- Delete the `run` command and helper functions `_resolve_project_root`, `_normalize_target_path`, `_wait_for_gate`, etc.
- Remove unused imports (`GraphCompleteEvent`, `GraphErrorEvent`, `RunRequest`, `normalize_event`).

2) `src/remora/service/handlers.py`
- Delete `handle_run`, `handle_plan`, and `_execute_graph`.
- Remove `GraphExecutor` imports and related helpers.
- Replace with new swarm handlers (see Step 7 for new endpoints).
 - Remove `ExecutorFactory` and `executor_factory` usage from `ServiceDeps`.

3) `src/remora/service/api.py`
- Remove `run()` and `plan()` methods from `RemoraService`.
- Remove `event_store` usage that depends on `graph_id` replay unless you re-scope it to swarm events.
 - Remove `executor_factory` and `running_tasks` fields from `ServiceDeps` and from `RemoraService.__init__`.

4) `src/remora/core/events.py`
- Remove graph-level events and their inclusion in `RemoraEvent`.

5) `src/remora/ui/projector.py`
- Remove Graph event imports and handling.
- Update `record()` so it does not rely on `GraphStartEvent`/`GraphCompleteEvent`.
  Replace the Graph sections with:
  ```python
  if isinstance(event, AgentStartEvent):
      if event.agent_id not in self.agent_states:
          self.total_agents += 1
      self.agent_states[event.agent_id] = {
          "state": "started",
          "name": event.node_name or event.agent_id,
      }
      return
  ```
  Keep completion counts based on AgentCompleteEvent and AgentErrorEvent.

### Acceptance
- `rg -n "GraphExecutor|build_graph|GraphStartEvent" src tests` returns nothing.

--------------------------------------------------------------------------------

## 5B) Add Swarm HTTP API Endpoints (If Service Stays)

### Goal
Replace graph `/run` and `/plan` with swarm endpoints.

### Files
- `src/remora/service/handlers.py`
- `src/remora/service/api.py`
- `src/remora/adapters/starlette.py`
- `src/remora/models/__init__.py`

### Exact changes

1) Create new request/response models.

In `src/remora/models/__init__.py`, delete `RunRequest`, `PlanRequest`, `RunResponse`, `PlanResponse` and add:
```python
@dataclass(slots=True)
class SwarmEmitRequest:
    event_type: str
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SwarmEmitRequest":
        payload = dict(data or {})
        return cls(
            event_type=str(payload.get("event_type", "")).strip(),
            data=dict(payload.get("data", {}) or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SwarmEmitResponse:
    event_id: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```
Update `__all__` to export `SwarmEmitRequest` and `SwarmEmitResponse`.

2) Add swarm handlers in `src/remora/service/handlers.py` and extend `ServiceDeps`:
```python
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.swarm_state import SwarmState

@dataclass(slots=True)
class ServiceDeps:
    ...
    swarm_state: SwarmState | None = None
    subscriptions: SubscriptionRegistry | None = None
```

Then add handlers:
```python
from remora.core.events import AgentMessageEvent, ContentChangedEvent
from remora.models import SwarmEmitRequest, SwarmEmitResponse

async def handle_swarm_emit(request: SwarmEmitRequest, deps: ServiceDeps) -> SwarmEmitResponse:
    if deps.event_store is None:
        raise ValueError("event store not configured")
    if request.event_type == "AgentMessageEvent":
        event = AgentMessageEvent(
            from_agent=request.data.get("from_agent", "api"),
            to_agent=request.data.get("to_agent", ""),
            content=request.data.get("content", ""),
            tags=request.data.get("tags", []),
        )
    elif request.event_type == "ContentChangedEvent":
        from remora.utils import to_project_relative
        path = to_project_relative(deps.project_root, request.data.get("path", ""))
        event = ContentChangedEvent(path=path, diff=request.data.get("diff"))
    else:
        raise ValueError(f"Unknown event type: {request.event_type}")

    event_id = await deps.event_store.append(deps.config.swarm_id, event)
    return SwarmEmitResponse(event_id=event_id)


def handle_swarm_list_agents(deps: ServiceDeps) -> list[dict[str, Any]]:
    if deps.swarm_state is None:
        raise ValueError("swarm state not configured")
    return deps.swarm_state.list_agents()


def handle_swarm_get_agent(agent_id: str, deps: ServiceDeps) -> dict[str, Any]:
    if deps.swarm_state is None:
        raise ValueError("swarm state not configured")
    agent = deps.swarm_state.get_agent(agent_id)
    if agent is None:
        raise ValueError("agent not found")
    return agent


async def handle_swarm_get_subscriptions(agent_id: str, deps: ServiceDeps) -> list[dict[str, Any]]:
    if deps.subscriptions is None:
        raise ValueError("subscriptions not configured")
    subs = await deps.subscriptions.get_subscriptions(agent_id)
    return [
        {
            "id": sub.id,
            "pattern": {
                "event_types": sub.pattern.event_types,
                "from_agents": sub.pattern.from_agents,
                "to_agent": sub.pattern.to_agent,
                "path_glob": sub.pattern.path_glob,
                "tags": sub.pattern.tags,
            },
            "is_default": sub.is_default,
        }
        for sub in subs
    ]
```
Update `__all__` in `service/handlers.py` to export the new swarm handlers.

If `ServiceDeps` does not have swarm_state/subscriptions, add them (and thread them into `RemoraService`).

3) Update `RemoraService` in `src/remora/service/api.py`:
- In `create_default()`, initialize `SwarmState` and `SubscriptionRegistry` from `config.swarm_root`.
- Call `set_swarm_state()` and `set_subscriptions()` or store them directly on the service.
- When building `ServiceDeps`, set `swarm_state` and `subscriptions`.
  Example inside `RemoraService.__init__`:
  ```python
  self._deps = ServiceDeps(
      event_bus=self._event_bus,
      config=self._config,
      project_root=self._project_root,
      projector=self._projector,
      event_store=self._event_store,
      swarm_state=self._swarm_state,
      subscriptions=self._subscriptions,
  )
  ```
- Add methods:
  - `list_agents()` -> calls `handle_swarm_list_agents()`
  - `get_agent(agent_id)` -> calls `handle_swarm_get_agent()`
  - `emit_event()` -> calls `handle_swarm_emit()`
  - `get_subscriptions(agent_id)` -> calls a new handler that returns SubscriptionRegistry rows

4) Update `src/remora/adapters/starlette.py` routes:
- Remove `/run` and `/plan`.
- Add:
  - `GET /swarm/agents`
  - `GET /swarm/agents/{id}`
  - `POST /swarm/events`
  - `GET /swarm/subscriptions/{id}`
- Remove `RunRequest` and `PlanRequest` imports and handlers.
Example route handlers:
```python
async def swarm_agents(_request: Request) -> JSONResponse:
    return JSONResponse(service.list_agents())

async def swarm_agent(request: Request) -> JSONResponse:
    agent_id = request.path_params["id"]
    return JSONResponse(service.get_agent(agent_id))

async def swarm_events(request: Request) -> JSONResponse:
    payload = await request.json()
    emit_request = SwarmEmitRequest.from_dict(payload)
    response = await service.emit_event(emit_request)
    return JSONResponse(response.to_dict())

async def swarm_subscriptions(request: Request) -> JSONResponse:
    agent_id = request.path_params["id"]
    return JSONResponse(service.get_subscriptions(agent_id))
```

### Acceptance
- `POST /swarm/events` appends to EventStore.
- `GET /swarm/agents` returns SwarmState entries.

--------------------------------------------------------------------------------

## 6) Flatten and Refocus Config (Swarm-Only)

### Goal
Replace nested `RemoraConfig` with a flat `Config`.

### File
`src/remora/core/config.py`

### Exact new flat config (replace entire file)
```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from remora.core.errors import ConfigError
from remora.utils import PathLike, normalize_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Config:
    project_path: str = "."
    discovery_paths: tuple[str, ...] = ("src/",)
    discovery_languages: tuple[str, ...] | None = None
    discovery_max_workers: int = 4

    bundle_root: str = "agents"
    bundle_mapping: dict[str, str] = field(default_factory=dict)

    model_base_url: str = "http://localhost:8000/v1"
    model_default: str = "Qwen/Qwen3-4B"
    model_api_key: str = ""

    swarm_root: str = ".remora"
    max_concurrency: int = 4
    max_turns: int = 8
    truncation_limit: int = 1024
    timeout_s: float = 300.0
    max_trigger_depth: int = 5
    trigger_cooldown_ms: int = 1000
    swarm_id: str = "swarm"

    workspace_ignore_patterns: tuple[str, ...] = (
        ".agentfs",
        ".git",
        ".jj",
        ".mypy_cache",
        ".pytest_cache",
        ".remora",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    )
    workspace_ignore_dotfiles: bool = True

    nvim_enabled: bool = False
    nvim_socket: str = ".remora/nvim.sock"


def load_config(path: PathLike | None = None) -> Config:
    if path is None:
        path = _find_config_file()
    config_path = normalize_path(path)
    if not config_path.exists():
        logger.info("No config file found, using defaults")
        return Config()
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}")
    return _build_config(data)


def _find_config_file() -> Path:
    current = Path.cwd()
    for directory in [current] + list(current.parents):
        config_path = directory / "remora.yaml"
        if config_path.exists():
            return config_path
        if (directory / "pyproject.toml").exists():
            break
    return current / "remora.yaml"


def _build_config(data: dict[str, Any]) -> Config:
    if "discovery_paths" in data and isinstance(data["discovery_paths"], list):
        data["discovery_paths"] = tuple(data["discovery_paths"])
    if "discovery_languages" in data and isinstance(data["discovery_languages"], list):
        data["discovery_languages"] = tuple(data["discovery_languages"])
    if "workspace_ignore_patterns" in data and isinstance(data["workspace_ignore_patterns"], list):
        data["workspace_ignore_patterns"] = tuple(data["workspace_ignore_patterns"])
    return Config(**data)


__all__ = ["Config", "ConfigError", "load_config"]
```

### Update all call sites
Replace `RemoraConfig` imports with `Config` from `remora.core.config`.
Replace usages of `config.discovery.*` with the new flat fields:
- `config.discovery.paths` -> `config.discovery_paths`
- `config.discovery.languages` -> `config.discovery_languages`
- `config.discovery.max_workers` -> `config.discovery_max_workers`
- `config.bundles.path` -> `config.bundle_root`
- `config.bundles.mapping` -> `config.bundle_mapping`
- `config.execution.max_concurrency` -> `config.max_concurrency`
- `config.execution.max_turns` -> `config.max_turns`
- `config.execution.timeout` -> `config.timeout_s`
- `config.workspace.ignore_patterns` -> `config.workspace_ignore_patterns`
- `config.workspace.ignore_dotfiles` -> `config.workspace_ignore_dotfiles`
- `config.swarm.max_trigger_depth` -> `config.max_trigger_depth`
- `config.swarm.trigger_cooldown_ms` -> `config.trigger_cooldown_ms`

### Update `remora.yaml` and `remora.yaml.example`
Replace with flat keys that match the new config:
```yaml
project_path: "."
discovery_paths: ["src/"]
discovery_languages: ["python"]
discovery_max_workers: 4

bundle_root: "agents"
bundle_mapping:
  function: "lint/bundle.yaml"
  class: "docstring/bundle.yaml"
  method: "docstring/bundle.yaml"
  file: "lint/bundle.yaml"

model_base_url: "http://remora-server:8000/v1"
model_api_key: "EMPTY"
model_default: "Qwen/Qwen3-4B"

swarm_root: ".remora"
swarm_id: "swarm"
max_concurrency: 4
max_turns: 8
truncation_limit: 1024
timeout_s: 300.0
max_trigger_depth: 5
trigger_cooldown_ms: 1000

workspace_ignore_patterns:
  - ".git"
  - ".venv"
  - "node_modules"
  - "__pycache__"
  - ".mypy_cache"
  - ".pytest_cache"
workspace_ignore_dotfiles: true

nvim_enabled: false
nvim_socket: ".remora/nvim.sock"
```

### Acceptance
- All references compile with flat config.
- YAML loading works with the new schema.

--------------------------------------------------------------------------------

## 7) Align Workspace Layout with Swarm Model

### Goal
Use per-agent persistent workspaces at `.remora/agents/<id>/workspace.db`.

### Files
- `src/remora/core/reconciler.py`
- `src/remora/core/workspace.py`
- `src/remora/core/cairn_bridge.py`

### Exact changes

1) Change workspace path helper in `reconciler.py`:
```python
def get_agent_workspace_path(swarm_root: Path, agent_id: str) -> Path:
    return get_agent_dir(swarm_root, agent_id) / "workspace.db"
```

2) Remove `WorkspaceManager` (graph-scoped) from `workspace.py`.
- Delete the `WorkspaceManager` class and remove it from `__all__`.

3) Update `CairnWorkspaceService` to use per-agent workspace path, not graph_id.
- Keep the class name, but change its constructor signature.
- Replace the constructor to accept `swarm_root` and `project_root` instead of `graph_id`.

Example replacement inside the class:
```python
class CairnWorkspaceService:
    def __init__(self, config: Config, swarm_root: PathLike, project_root: PathLike | None = None):
        self._swarm_root = normalize_path(swarm_root)
        self._project_root = normalize_path(project_root or Path.cwd()).resolve()
        self._resolver = PathResolver(self._project_root)
        self._manager = cairn_workspace_manager.WorkspaceManager()
        self._stable_workspace = None
        self._agent_workspaces = {}
        self._stable_lock = asyncio.Lock()
        self._ignore_patterns = set(config.workspace_ignore_patterns or ())
        self._ignore_dotfiles = config.workspace_ignore_dotfiles
        ...

    async def get_agent_workspace(self, agent_id: str) -> AgentWorkspace:
        workspace_path = get_agent_workspace_path(self._swarm_root, agent_id)
        ...
```
Also update `initialize()` to write the stable workspace at:
```python
stable_path = self._swarm_root / "stable.db"
```
Remove the old `self._base_path = normalize_path(config.base_path) / graph_id` usage entirely.

4) Update all references to `CairnWorkspaceService` in `SwarmExecutor` and elsewhere to pass `swarm_root` instead of `graph_id`.

### Acceptance
- Every agent has:
  - `.remora/agents/<id>/state.jsonl`
  - `.remora/agents/<id>/workspace.db`

--------------------------------------------------------------------------------

## 8) Fix Subscription Path Matching

### Goal
All subscription path matching uses project-relative POSIX paths.

### Files
- `src/remora/utils/path_resolver.py` (new helper)
- `src/remora/utils/__init__.py` (export helper)
- `src/remora/core/reconciler.py`
- `src/remora/cli/main.py`
- `src/remora/nvim/server.py`

### Exact changes

1) Add helper to `src/remora/utils/path_resolver.py`:
```python
from pathlib import Path

def to_project_relative(project_root: Path, path: str) -> str:
    resolved = Path(path).resolve()
    try:
        rel = resolved.relative_to(project_root.resolve())
        return rel.as_posix()
    except ValueError:
        return resolved.as_posix()
```

2) Export the helper in `src/remora/utils/__init__.py`:
```python
from remora.utils.path_resolver import PathResolver, to_project_relative
...
__all__ = [
    ...,
    "PathResolver",
    "to_project_relative",
    ...
]
```

3) Use this helper before registering default subscriptions:
In `reconciler.py`:
```python
from remora.utils import to_project_relative
...
file_path = to_project_relative(project_path, node.file_path)
...
await subscriptions.register_defaults(node.node_id, file_path)
```

4) Normalize paths before emitting events:
In `cli/main.py` inside `swarm_emit`:
```python
from remora.utils import to_project_relative
...
path = to_project_relative(root, event_data.get("path", ""))
event = ContentChangedEvent(path=path, diff=event_data.get("diff"))
```

In `nvim/server.py` inside `_handle_swarm_emit`:
```python
from remora.utils import to_project_relative
...
path = to_project_relative(self._project_root, event_data.get("path", ""))
event = ContentChangedEvent(path=path, diff=event_data.get("diff"))
```

Add `project_root` to `NvimServer.__init__` so you can normalize paths there.

### Acceptance
- A `ContentChangedEvent` for `src/foo.py` matches `path_glob="src/foo.py"`.

--------------------------------------------------------------------------------

## 9) Reconciliation Updates (Changed Nodes + ContentChangedEvent)

### Goal
Detect changed nodes and emit `ContentChangedEvent`.

### File
`src/remora/core/reconciler.py`

### Exact changes

1) Update function signature to accept EventStore and swarm_id:
```python
async def reconcile_on_startup(..., event_store: EventStore | None = None, swarm_id: str = "swarm") -> dict[str, Any]:
```

2) Build a lookup map for existing agents:
```python
existing_agents = swarm_state.list_agents(status="active")
existing_by_id = {agent["agent_id"]: agent for agent in existing_agents}
```

3) Identify changed nodes:
```python
changed_ids = set()
for node_id, node in node_map.items():
    existing = existing_by_id.get(node_id)
    if not existing:
        continue
    if (
        existing["file_path"] != node.file_path
        or existing["start_line"] != node.start_line
        or existing["end_line"] != node.end_line
    ):
        changed_ids.add(node_id)
```

4) For each changed node:
- Update `SwarmState`.
- Update `AgentState` on disk (append new JSON line).
- Re-register defaults if file_path changed.
- Emit `ContentChangedEvent` via `EventStore` if provided.

Exact snippet inside a new loop:
```python
    for node_id in changed_ids:
        node = node_map[node_id]
        metadata = AgentMetadata(
            agent_id=node.node_id,
            node_type=node.node_type,
            name=node.name,
            full_name=node.full_name,
            file_path=node.file_path,
            parent_id=None,
            start_line=node.start_line,
            end_line=node.end_line,
        )
        swarm_state.upsert(metadata)

        state = AgentState(
            agent_id=node.node_id,
            node_type=node.node_type,
            name=node.name,
            full_name=node.full_name,
            file_path=node.file_path,
            range=(node.start_line, node.end_line),
        )
        save_agent_state(get_agent_state_path(swarm_root, node.node_id), state)

        await subscriptions.unregister_all(node.node_id)
        await subscriptions.register_defaults(node.node_id, node.file_path)

        if event_store is not None:
            await event_store.append(
                swarm_id,
                ContentChangedEvent(path=node.file_path, diff=None),
            )
```

### Acceptance
- Moving a file or changing its range updates swarm state and emits a change event.

--------------------------------------------------------------------------------

## 10) Update Tests (Swarm-Only)

### Goal
Remove graph/indexer/checkpoint tests and add swarm tests.

### Remove tests
Delete tests that reference GraphExecutor, indexer, or checkpoint:
- `tests/integration/test_indexer_daemon_real.py`
- `tests/integration/test_checkpoint_roundtrip.py`
- `tests/integration/test_checkpoint_resume_real.py`
- Any tests that import `remora.core.graph` or `remora.core.executor`

### Add tests (new files)
Create new files:
- `tests/unit/test_subscriptions.py`
- `tests/unit/test_event_store.py` (add trigger tests)
- `tests/unit/test_agent_runner.py`
- `tests/unit/test_reconciler.py`
- `tests/unit/test_nvim_server.py`
- `tests/integration/test_swarm_smoke_real.py`

Use the test ideas from `.refactor/SIMPLIFICATION_REWRITE-PHASE_2..8.md`.

### Acceptance
- `pytest` passes with only swarm-focused tests.

--------------------------------------------------------------------------------

## 11) Documentation Cleanup

### Goal
Docs must describe swarm-only architecture.

### Files to update
- `README.md`
- `HOW_TO_USE_REMORA.md`
- `docs/ARCHITECTURE.md`
- `docs/CONFIGURATION.md`
- `docs/API_REFERENCE.md`
- `docs/REMORA_UI_API.md`

### Exact changes
Remove references to:
- indexer
- checkpointing
- graph execution
- `GraphExecutor` and graph events

Add sections for:
- Swarm CLI (`remora swarm start`, `remora swarm emit`, `remora swarm list`)
- SubscriptionRegistry
- Neovim JSON-RPC server

### Acceptance
- `rg -n "indexer|checkpoint|GraphExecutor|graph execution" README.md docs HOW_TO_USE_REMORA.md` returns nothing.

--------------------------------------------------------------------------------

## 12) API Surface Cleanup

### Goal
Public API should only export swarm components.

### Files
- `src/remora/__init__.py`
- `src/remora/core/__init__.py`

### Exact exports to keep
- `EventStore`, `EventBus`, `SubscriptionRegistry`, `SubscriptionPattern`
- `SwarmState`, `AgentMetadata`
- `AgentRunner`, `AgentState`
- `AgentMessageEvent`, `ContentChangedEvent`, `FileSavedEvent`, `ManualTriggerEvent`
- `reconcile_on_startup` and agent path helpers

Remove any graph and checkpoint exports.

### Acceptance
- `from remora import *` exposes only swarm primitives.

--------------------------------------------------------------------------------

## 13) Final Validation Checklist

Run these checks:
- `rg -n "GraphExecutor|build_graph|GraphStartEvent|Checkpoint|indexer" src tests docs` -> no results
- `remora swarm start` -> reconciliation + runner active
- `remora swarm emit AgentMessageEvent '{"to_agent":"<id>","content":"ping"}'` -> agent processes
- Start Neovim server and verify JSON-RPC `swarm.emit` returns a response and notifications arrive

If any step is blocked, stop and ask for clarification instead of reintroducing legacy logic.
