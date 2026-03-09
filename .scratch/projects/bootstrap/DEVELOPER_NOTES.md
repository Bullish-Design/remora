# Bootstrap Implementation — Developer Notes

> Supplements IMPLEMENTATION_GUIDE.md with missing details and context
> a developer needs that the guide doesn't spell out.

---

## 1. Missing File Content

### 1.1 `src/remora/bootstrap/__init__.py`

The guide lists this file but never specifies its content:
```python
"""Bootstrap V6 — substrate layer for self-defining agent swarms."""

from remora.bootstrap.bedrock import BootstrapEvent, build_bedrock, _make_files_provider
from remora.bootstrap.schema_loader import TurnSchema, load_schema
from remora.bootstrap.turn_executor import TurnExecutor, TurnResult

__all__ = [
    "BootstrapEvent",
    "build_bedrock",
    "_make_files_provider",
    "TurnSchema",
    "load_schema",
    "TurnExecutor",
    "TurnResult",
]
```

### 1.2 Test package `__init__.py` files

Create empty files for the new test packages:
```
tests/unit/bootstrap/__init__.py
tests/integration/bootstrap/__init__.py
```

### 1.3 Test fixtures (`conftest.py`)

The test examples reference fixtures that aren't defined anywhere. Create
`tests/unit/bootstrap/conftest.py`:
```python
import pytest
from pathlib import Path
from remora.core.store.event_store import EventStore


@pytest.fixture
async def event_store(tmp_path):
    store = EventStore(tmp_path / "test.db")
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def node_store(event_store):
    return event_store.nodes


@pytest.fixture
async def node_store_with_data(node_store):
    # Insert a test AgentNode row for tests that need live code nodes.
    # Use the same INSERT columns as the nodes table schema in
    # core/store/event_store_schema.py.
    ...
    return node_store


@pytest.fixture
def bootstrap_agents_dir(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "base_code_agent.yaml").write_text("""
version: "1"
name: base_code_agent
system: "You are a code agent for {node.full_name}."
tools: [read_file, write_file]
max_turns: 8
termination: "DONE"
""")
    return agents_dir
```

---

## 2. Integration Gaps (how the pieces connect at runtime)

### 2.1 How bootstrap activations are triggered — write `runner.py`

The guide shows `handle_agent_needed()` as a standalone function but never says
where it's called from. In v1, `EventStore.get_triggers()` is polled by
`runner/agent_runner.py` and `runner/swarm_executor.py`. Bootstrap needs the
same pattern.

Create `src/remora/bootstrap/runner.py`:
```python
"""Bootstrap runtime — event loop that drives agent activations."""
import asyncio
from pathlib import Path
from remora.core.config import Config
from remora.core.store.event_store import EventStore
from remora.core.agents.cairn_bridge import CairnWorkspaceService
from remora.core.events.subscriptions import SubscriptionRegistry
from remora.bootstrap.bedrock import build_bedrock, _make_files_provider, _extract_workspace_tools
from remora.bootstrap.turn_executor import TurnExecutor
from remora.bootstrap.seed_graph import seed_coordinator_node, seed_module_nodes_from_filesystem
from remora.core.tools.grail import discover_grail_tools
from remora.core.agents.cairn_externals import CairnExternals
from remora.core.events.subscriptions import SubscriptionPattern


BOOTSTRAP_TOOLS_DIR = Path(__file__).parent.parent.parent / "bootstrap" / "tools"


async def run_bootstrap(config: Config, project_root: Path) -> None:
    """Initialize and run the bootstrap event loop."""
    subscriptions = SubscriptionRegistry()
    event_store = EventStore(
        project_root / ".remora" / "event_store.db",
        subscriptions=subscriptions,
    )
    await event_store.initialize()

    workspace_service = CairnWorkspaceService(config, project_root=project_root)
    await workspace_service.initialize()

    # Seed the graph (coordinator node + module nodes if LSP hasn't run yet)
    await seed_coordinator_node(event_store)
    node_count = len(await event_store.nodes.list_nodes(node_type="module"))
    if node_count == 0:
        await seed_module_nodes_from_filesystem(event_store, project_root, swarm_id=config.swarm_id)

    # Emit the first activation event for the coordinator
    from remora.bootstrap.bedrock import BootstrapEvent
    await event_store.append(config.swarm_id, BootstrapEvent(
        event_type="AgentNeededEvent",
        payload={"agent_id": "coordinator", "node_id": "coordinator"},
    ))

    # Drive activations from the trigger queue
    async for agent_id, event_id, event in event_store.get_triggers():
        asyncio.create_task(
            handle_agent_needed(
                event=event,
                workspace_service=workspace_service,
                subscriptions=subscriptions,
                event_store=event_store,
                config=config,
                swarm_id=config.swarm_id,
                bootstrap_tools_dir=BOOTSTRAP_TOOLS_DIR,
            )
        )
```

### 2.2 `EventStore` and `CairnWorkspaceService` must be initialized before use

- `event_store.nodes` raises `RuntimeError` until `await event_store.initialize()` is called.
- `workspace_service.get_agent_workspace()` raises `WorkspaceError` until
  `await workspace_service.initialize()` is called.
- `EventStore` must be constructed with a `SubscriptionRegistry` for
  `get_triggers()` to work (raises `RuntimeError` otherwise).

### 2.3 How bootstrap events trigger subscriptions

Bootstrap events go through `event_store.append()` which populates the
`_trigger_queue`. For subscriptions to be matched, `EventStore` must have been
constructed with a `SubscriptionRegistry`:
```python
subscriptions = SubscriptionRegistry()
event_store = EventStore(db_path, subscriptions=subscriptions)
```

Bootstrap agents register their subscriptions via
`subscriptions.register(agent_id, SubscriptionPattern(...))`.

---

## 3. `structured_agents` Package Reference

`structured_agents` is a Remora dependency available in the devenv. Key symbols
used by bootstrap:

| Symbol | Used in |
|--------|---------|
| `Message(role, content)` | TurnExecutor — build message list |
| `build_client(config_dict)` | TurnExecutor — create LLM client |
| `AgentKernel` | Returned by `create_kernel()` |
| `kernel.run(messages, tool_schemas, max_turns=N)` | TurnExecutor |
| `kernel.close()` | TurnExecutor — always in a `finally` block |
| `Event` (base class) | `BootstrapEvent` inheritance |

The `kernel.run()` return value has `result.final_message.content` (a string).
See `core/agents/execution.py` lines 206–216 for the extraction pattern.

---

## 4. v1 API Quick Reference

Verified against actual source. Key signatures for classes the guide uses.

### EventStore
```python
EventStore(db_path, subscriptions=None, event_bus=None, projection=None)
await event_store.initialize()           # must call first
await event_store.append(graph_id, event)  # → int (event_id)
await event_store.get_recent_events(agent_id, limit=5)  # → list[dict]
async for agent_id, event_id, event in event_store.get_triggers(): ...
event_store.nodes  # → NodeStore (only after initialize())
```

### NodeStore
```python
await node_store.get_node(node_id)        # → AgentNode | None
await node_store.list_nodes(*, file_path=None, node_type=None, columns=None)
                                          # → list[AgentNode]
# New methods added by this implementation:
await node_store.read_graph(selector)     # → str (JSON)
await node_store.write_graph(op, data)    # → str (JSON)
```

### CairnWorkspaceService
```python
CairnWorkspaceService(config, *, graph_id=None, swarm_root=None, project_root=None)
await workspace_service.initialize(*, sync_mode=SyncMode.FULL)
await workspace_service.get_agent_workspace(agent_id)  # → AgentWorkspace
workspace_service.get_externals(agent_id, workspace)   # → dict[str, Callable]
                                                       # (Grail externals dict, NOT CairnExternals)
workspace_service.resolver  # → PathResolver
workspace_service._stable_workspace  # internal — needed for CairnExternals construction
```

### AgentWorkspace
```python
workspace.cairn  # → underlying Cairn workspace object (pass as agent_fs to CairnExternals)
# No .path attribute — it's a virtual FS backed by SQLite, not a real directory
```

### CairnExternals
```python
# Constructor — build this directly, don't use get_externals() for CairnExternals objects
CairnExternals(
    agent_id=agent_id,
    agent_fs=workspace.cairn,                      # from AgentWorkspace.cairn
    stable_fs=workspace_service._stable_workspace, # private attr
    resolver=workspace_service.resolver,           # public attr
)
await cairn_externals.read_file(path)              # → str
await cairn_externals.write_file(path, content)    # → bool (not str; return ignored)
await cairn_externals.list_dir(path=".")           # → list[str]
```

### Config (`remora.core.config.Config`)
```python
config.model_base_url    # str
config.model_default     # str (model name)
config.model_api_key     # str | None
config.timeout_s         # float
config.swarm_id          # str
config.swarm_root        # Path
```

---

## 5. tach.toml — Run check after adding the module

After adding `remora.bootstrap` to `tach.toml`, run:
```bash
devenv shell -- tach check
```

If there are violations, add the missing direct dependencies. `depends_on` must
list all direct imports, not just parent packages. Expected dependencies:
- `remora.core` (covers core submodules if tach.toml is configured that way)
- `remora.utils`

Adjust based on what `tach check` reports.

---

*End of DEVELOPER_NOTES.md*
