# Remora Library Detailed Demo Plan

This document outlines a comprehensive step-by-step demonstration of all Remora library functionality, including actual vLLM calls, real agent bundles, and Grail scripts.

---

## Overview

Remora is a local code analysis and enhancement library featuring:
- **AgentGraph**: Declarative agent composition with DAG-based execution
- **Workspace**: Isolated workspaces for agent graphs with KV store IPC
- **Hub**: Background daemon for code indexing and state management
- **Discovery**: Tree-sitter based code node discovery
- **Event Bus**: Unified event system for all components
- **Context Manager**: Lazy-loading context from Hub for agents
- **vLLM Integration**: Real LLM calls via AsyncOpenAI client
- **Grail Scripts**: Pym-based external tools for agent execution

---

## Demo Structure

### Phase 1: Setup Input Example Directory Tree

Create a sample project demonstrating Remora's capabilities.

```
demo_input/
├── pyproject.toml
├── src/
│   ├── __init__.py
│   ├── main.py              # Main application entry
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── helpers.py       # Utility functions
│   │   └── math_utils.py    # Math functions (needs lint/docstring)
│   └── models/
│       ├── __init__.py
│       └── user.py          # Data model (needs tests)
├── tests/
│   ├── __init__.py
│   └── test_main.py
└── README.md
```

**Files to Create:**

1. **demo_input/pyproject.toml**
   ```toml
   [project]
   name = "demo-project"
   version = "0.1.0"
   
   [tool.ruff]
   select = ["E", "W", "F"]
   ```

2. **demo_input/src/main.py** - Contains multiple functions/classes for linting
3. **demo_input/src/utils/helpers.py** - Functions needing docstrings
4. **demo_input/src/utils/math_utils.py** - Functions needing lint fixes
5. **demo_input/src/models/user.py** - Class needing tests
6. **demo_input/tests/test_main.py** - Existing test file

---

### Phase 2: Create Remora Configuration

Create `remora.yaml` with full configuration.

**Step-by-step:**
1. Create `demo_input/remora.yaml` with:
   - Server config (vLLM endpoint)
   - Discovery config (query pack, languages)
   - Operations (lint, test, docstring)
   - Runner config (max turns, tokens, temperature)
   - Cairn config (concurrency, limits)
   - Hub config (daemon mode)

```yaml
discovery:
  query_pack: remora_core
  languages:
    .py: tree_sitter_python

server:
  base_url: http://localhost:8000/v1
  default_adapter: Qwen/Qwen3-4B-Instruct-2507-FP8
  default_plugin: function_gemma

operations:
  lint:
    subagent: lint
    enabled: true
  docstring:
    subagent: docstring
    style: google
  test:
    subagent: test

runner:
  max_turns: 20
  max_tokens: 4096
  temperature: 0.1

cairn:
  max_concurrent_agents: 4
  timeout: 300
  limits_preset: default

hub:
  mode: daemon
  enable_cross_file_analysis: true
  max_indexing_workers: 4
```

---

### Phase 3: Agent Bundles & Grail Scripts

Demonstrate the existing agent infrastructure.

#### 3.1 Lint Agent Bundle (`agents/lint/`)

**bundle.yaml:**
- Model: FunctionGemma via vLLM
- Tools: run_linter, apply_fix, read_file, submit_result
- Max turns: 15

**Grail Scripts:**

1. **tools/run_linter.pym** - Runs ruff linter
   ```python
   from grail import Input, external
   
   check_only: bool = Input("check_only", default=True)
   
   @external
   async def run_json_command(cmd: str, args: list[str]) -> Any:
       ...
   
   # Runs: ruff check --output-format json --select E,W,F <file>
   # Returns: {"issues": [...], "total": N, "fixable_count": N}
   ```

2. **tools/apply_fix.pym** - Applies automatic fixes
   ```python
   issue_code: str = Input("issue_code")
   line_number: int = Input("line_number")
   
   # Runs: ruff check --fix --select <code> <file>
   # Returns: {"success": bool, "message": str}
   ```

3. **tools/read_file.pym** - Reads file contents

4. **tools/submit_result.pym** - Submits final result

#### 3.2 Docstring Agent Bundle (`agents/docstring/`)

**bundle.yaml:**
- Model: FunctionGemma via vLLM
- Tools: read_current_docstring, read_type_hints, write_docstring, submit_result

**Grail Scripts:**

1. **tools/read_current_docstring.pym** - Reads existing docstrings
2. **tools/read_type_hints.pym** - Extracts type annotations
3. **tools/write_docstring.pym** - Writes docstrings in specified style

#### 3.3 Test Agent Bundle (`agents/test/`)

**bundle.yaml:**
- Model: FunctionGemma via vLLM
- Tools: analyze_signature, read_existing_tests, write_test_file, run_tests, submit_result

**Grail Scripts:**

1. **tools/analyze_signature.pym** - Extracts function signatures
2. **tools/read_existing_tests.pym** - Reads existing test files
3. **tools/write_test_file.pym** - Generates pytest tests
4. **tools/run_tests.pym** - Runs pytest

---

### Phase 4: Initialize Hub and Code Indexing

Demonstrate Hub daemon functionality.

**Step-by-step:**
1. **Start Hub daemon:**
   ```bash
   remora-hub start --project-root ./demo_input
   ```

2. **Show cold-start indexing:**
   - Parallel file processing with `max_indexing_workers`
   - File hash comparison for incremental updates
   - NodeState storage in Fsdantic workspace

3. **Demonstrate file watching:**
   - `HubWatcher` monitors for changes
   - Change queue with backpressure
   - Concurrent change workers

4. **Cross-file analysis:**
   - Call graph analysis
   - Test discovery relationships
   - Import tracking

5. **Query indexed nodes:**
   ```python
   from remora.hub_client import HubClient
   
   client = HubClient()
   nodes = await client.get_context(["node_id1", "node_id2"])
   ```

6. **Check metrics:**
   ```bash
   remora metrics
   ```

---

### Phase 5: Create Workspaces

Demonstrate workspace management for agent graphs.

**Step-by-step:**
1. Create `GraphWorkspace`:
   ```python
   from remora.workspace import GraphWorkspace
   
   workspace = await GraphWorkspace.create("graph-123", root="/tmp/remora/workspaces/graph-123")
   ```

2. Show workspace structure:
   ```
   workspace/
   ├── agents/
   │   ├── agent-1/
   │   └── agent-2/
   ├── shared/          # Shared space for IPC
   ├── original/        # Read-only source snapshot
   ├── kv/             # Key-value store for IPC
   │   └── *.json
   └── metadata.json
   ```

3. Snapshot original source:
   ```python
   await workspace.snapshot_original(Path("demo_input/src/main.py"))
   ```

4. Create agent spaces:
   ```python
   agent_space = workspace.agent_space("agent-1")
   ```

5. Demonstrate KV store:
   ```python
   await workspace.kv.set("agent:1:state", {"status": "running"})
   value = await workspace.kv.get("agent:1:state")
   keys = await workspace.kv.list(prefix="agent:")
   ```

6. Merge changes:
   ```python
   await workspace.merge()
   ```

---

### Phase 6: Build Agent Graph

Demonstrate declarative agent composition.

**Step-by-step:**
1. Create graph:
   ```python
   from remora.agent_graph import AgentGraph
   
   graph = AgentGraph()
   ```

2. Add agents:
   ```python
   graph.agent(
       name="lint-main",
       bundle="lint",
       target=source_code,
       target_path=Path("src/main.py"),
       target_type="function"
   )
   ```

3. Define dependencies:
   ```python
   graph.after("lint-main").run("docstring-main")
   graph.run_parallel("test-1", "test-2")
   ```

4. Use auto-discovery:
   ```python
   graph.discover(
       root_dirs=[Path("demo_input/src")],
       bundles={"function": "lint", "class": "docstring", "module": "test"}
   )
   ```

5. Configure execution:
   ```python
   from remora.agent_graph import GraphConfig, ErrorPolicy
   
   config = GraphConfig(
       max_concurrency=4,
       timeout=300.0,
       error_policy=ErrorPolicy.STOP_GRAPH
   )
   ```

---

### Phase 7: Execute Agent Graph with vLLM

Demonstrate graph execution with real LLM calls.

**Step-by-step:**
1. **Configure server:**
   ```python
   from remora.config import ServerConfig
   from remora.client import build_client
   
   server_config = ServerConfig(
       base_url="http://localhost:8000/v1",
       default_adapter="Qwen/Qwen3-4B-Instruct-2507-FP8"
   )
   client = build_client(server_config)
   ```

2. **Execute graph:**
   ```python
   executor = graph.execute(config)
   results = await executor.run()
   ```

3. **Agent execution flow:**
   - Load bundle with `structured_agents.load_bundle()`
   - Initialize FunctionGemma with grammar
   - Send system prompt + user template
   - LLM generates tool calls
   - Execute Grail scripts via Cairn
   - Loop until termination tool called

4. **Handle events:**
   ```python
   from remora.event_bus import Event
   
   await event_bus.subscribe("agent:*", handler)
   # Events: started, blocked, resumed, completed, failed, cancelled
   ```

5. **Interactive mode:**
   ```python
   async def handle_blocked(agent, question):
       # Show question to user
       answer = await agent.inbox.ask_user(question)
       return answer
   
   graph.on_blocked(handle_blocked)
   ```

---

### Phase 8: Event Bus Demonstration

Show the unified event system.

**Step-by-step:**
1. **Publish events:**
   ```python
   from remora.event_bus import Event, get_event_bus
   
   event_bus = get_event_bus()
   
   await event_bus.publish(Event.agent_started(agent_id="123"))
   await event_bus.publish(Event.agent_blocked(agent_id="123", question="Approve?"))
   await event_bus.publish(Event.agent_completed(agent_id="123", result="..."))
   ```

2. **Subscribe to patterns:**
   ```python
   await event_bus.subscribe("agent:completed", handler)
   await event_bus.subscribe("tool:*", handler)  # Wildcard
   ```

3. **Stream events:**
   ```python
   async for event in event_bus.stream():
       print(event)
   ```

4. **SSE formatting:**
   ```python
   sse_data = await event_bus.send_sse(event)
   # Returns: "data: {...}\n\n"
   ```

---

### Phase 9: Code Discovery

Demonstrate Tree-sitter based code discovery.

**Step-by-step:**
1. Initialize discoverer:
   ```python
   from remora.discovery.discoverer import TreeSitterDiscoverer
   
   discoverer = TreeSitterDiscoverer(
       root_dirs=[Path("demo_input/src")],
       query_pack="remora_core"
   )
   ```

2. Discover nodes:
   ```python
   nodes = discoverer.discover()
   # Returns: list[CSTNode] with:
   # - name, node_type, file_path
   # - start_byte, end_byte
   # - text (source code)
   ```

3. Node types discovered:
   - `function` - Python functions
   - `class` - Python classes
   - `method` - Class methods
   - `import` - Import statements

---

### Phase 10: Hub Server (Web API)

Demonstrate the Hub REST API server.

**Step-by-step:**
1. **Start server:**
   ```bash
   remora-hub serve --workspace-base /tmp/remora/workspaces --port 8000
   ```

2. **API Endpoints:**

   | Endpoint | Method | Description |
   |----------|--------|-------------|
   | `/` | GET | Dashboard HTML |
   | `/subscribe` | GET | SSE event stream |
   | `/graph/execute` | POST | Execute agent graph |
   | `/graph/list` | GET | List workspaces |
   | `/api/files` | GET | Browse workspace files |
   | `/agent/{id}/respond` | POST | Respond to blocked agent |

3. **Execute graph via API:**
   ```bash
   curl -X POST http://localhost:8000/graph/execute \
     -H "Content-Type: application/json" \
     -d '{
       "bundle": "lint",
       "target_path": "demo_input/src/main.py",
       "target": "def foo(): pass"
     }'
   ```

4. **Subscribe to events:**
   ```bash
   curl -N http://localhost:8000/subscribe
   ```

5. **Browse workspace:**
   ```bash
   curl "http://localhost:8000/api/files?path=graph-123"
   ```

---

### Phase 11: CLI Commands

Demonstrate all CLI functionality.

**Step-by-step:**
1. **Show configuration:**
   ```bash
   remora config
   remora config --discovery-language python --max-turns 10
   ```

2. **Display metrics:**
   ```bash
   remora metrics
   # Output:
   # Counters: files_indexed, nodes_indexed, files_failed
   # Timing: cold_start_duration, index_latency
   # Gauges: queue_size, workers_active
   ```

3. **List agents:**
   ```bash
   remora list-agents
   # Shows: Agent, Enabled, YAML exists, Adapter, Model available
   ```

4. **Hub daemon control:**
   ```bash
   remora-hub start --project-root ./demo_input
   remora-hub status
   remora-hub stop
   ```

5. **Start web server:**
   ```bash
   remora-hub serve --port 8000
   ```

---

### Phase 12: Agent State Management

Demonstrate KV-based agent state.

**Step-by-step:**
1. Initialize:
   ```python
   from remora.agent_state import AgentKVStore
   
   kv = AgentKVStore(workspace, agent_id="agent-1")
   ```

2. Manage messages:
   ```python
   kv.add_message({"role": "user", "content": "Fix this code"})
   messages = kv.get_messages()
   ```

3. Track tool results:
   ```python
   kv.add_tool_result({"name": "run_linter", "output": {...}})
   results = kv.get_tool_results()
   ```

4. Manage metadata:
   ```python
   kv.set_metadata({"status": "running"})
   metadata = kv.get_metadata()
   ```

5. Snapshots:
   ```python
   snapshot_id = kv.create_snapshot("before-fix")
   kv.restore_snapshot("snapshot:before-fix:abc123")
   snapshots = kv.list_snapshots()
   ```

---

### Phase 13: Save Output Example Directory Tree

Save modified workspace to output directory.

**Step-by-step:**
1. **Merge workspace changes:**
   ```python
   await workspace.merge()
   ```

2. **Save to output:**
   ```python
   output_dir = Path("demo_output")
   output_dir.mkdir(exist_ok=True)
   
   # Copy merged files
   for file in workspace.original_source().rglob("*"):
       rel = file.relative_to(workspace.original_source())
       dest = output_dir / rel
       dest.parent.mkdir(parents=True, exist_ok=True)
       shutil.copy2(file, dest)
   ```

3. **Output structure:**
   ```
   demo_output/
   ├── src/
   │   ├── main.py           # Lint fixes applied
   │   ├── utils/
   │   │   ├── helpers.py    # Docstrings added
   │   │   └── math_utils.py # Fixed
   │   └── models/
   │       └── user.py       # Tests generated
   ├── tests/
   │   ├── test_main.py
   │   └── test_user.py     # New tests
   └── metadata.json         # Graph execution metadata
   ```

4. **Verify transformations:**
   - Check lint fixes in main.py
   - Verify docstrings in helpers.py
   - Confirm tests in test_user.py

---

## Complete Demo Workflow

### Pre-requisites

1. **Start vLLM server:**
   ```bash
   vllm serve Qwen/Qwen3-4B-Instruct-2507-FP8 --dtype half
   ```

2. **Install dependencies:**
   ```bash
   uv pip install -e ".[frontend,backend]"
   ```

### Full Demo Script

```python
#!/usr/bin/env python3
"""Complete Remora Demo Script"""

import asyncio
from pathlib import Path
import shutil

from remora.agent_graph import AgentGraph, GraphConfig, ErrorPolicy
from remora.workspace import GraphWorkspace
from remora.discovery.discoverer import TreeSitterDiscoverer
from remora.event_bus import get_event_bus, Event
from remora.config import load_config
from remora.hub.daemon import HubDaemon
from remora.hub.server import HubServer
from remora.hub_client import HubClient
from remora.agent_state import AgentKVStore


async def main():
    print("=" * 60)
    print("REMORA LIBRARY DEMO")
    print("=" * 60)
    
    # Phase 1: Setup
    print("\n[Phase 1] Setting up demo input files...")
    demo_input = Path("demo_input")
    # (Create files as outlined in Phase 1)
    
    # Phase 2: Config
    print("\n[Phase 2] Loading configuration...")
    config = load_config(demo_input / "remora.yaml")
    
    # Phase 3: Hub Daemon
    print("\n[Phase 3] Starting Hub daemon...")
    daemon = HubDaemon(project_root=demo_input)
    # daemon.run()  # In production
    
    # Phase 4: Workspaces
    print("\n[Phase 4] Creating workspace...")
    workspace = await GraphWorkspace.create("demo-graph")
    await workspace.snapshot_original(demo_input / "src")
    
    # Phase 5: Discovery
    print("\n[Phase 5] Discovering code nodes...")
    discoverer = TreeSitterDiscoverer(
        root_dirs=[demo_input / "src"],
        query_pack="remora_core"
    )
    nodes = discoverer.discover()
    print(f"  Found {len(nodes)} code nodes")
    
    # Phase 6: Build Graph
    print("\n[Phase 6] Building agent graph...")
    graph = AgentGraph()
    
    # Add agents for each node
    for node in nodes:
        if node.node_type == "function":
            graph.agent(
                name=f"lint-{node.name}",
                bundle="lint",
                target=node.text or "",
                target_path=node.file_path,
                target_type="function"
            )
    
    # Dependencies
    graph.after("lint-main").run("docstring-main")
    
    # Phase 7: Execute
    print("\n[Phase 7] Executing agent graph...")
    event_bus = get_event_bus()
    
    # Subscribe to events
    async def log_event(event: Event):
        print(f"  Event: {event.type}")
    
    await event_bus.subscribe("agent:*", log_event)
    
    # Execute with vLLM
    executor = graph.execute(GraphConfig(
        max_concurrency=2,
        timeout=300.0,
        error_policy=ErrorPolicy.STOP_GRAPH
    ))
    
    results = await executor.run()
    print(f"  Completed {len(results)} agents")
    
    # Phase 8: State Management
    print("\n[Phase 8] Managing agent state...")
    kv = AgentKVStore(workspace, "agent-1")
    kv.add_message({"role": "system", "content": "Starting"})
    snapshot = kv.create_snapshot("checkpoint-1")
    
    # Phase 9: Hub Client
    print("\n[Phase 9] Querying Hub context...")
    client = HubClient()
    if await client.health_check():
        node_context = await client.get_context([n.node_id for n in nodes[:3]])
        print(f"  Got context for {len(node_context)} nodes")
    
    # Phase 10: Save Output
    print("\n[Phase 10] Saving output...")
    await workspace.merge()
    
    output_dir = Path("demo_output")
    output_dir.mkdir(exist_ok=True)
    
    # Copy merged files
    for src_file in workspace.original_source().rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(workspace.original_source())
            dst = output_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst)
    
    print(f"  Saved to {output_dir}")
    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Summary of All Remora Functionality

| Component | Features Demonstrated |
|-----------|----------------------|
| **AgentGraph** | Declarative composition, DAG dependencies, parallel/sequential execution, auto-discovery |
| **AgentNode** | State machine, inbox for user interaction, KV store, execution |
| **Workspace** | Graph workspaces, agent spaces, shared space, KV IPC, snapshots |
| **Hub Daemon** | File watching, parallel indexing, cold-start, cross-file analysis, metrics |
| **Hub Server** | REST API, SSE streaming, graph execution, interactive agents |
| **HubClient** | Lazy context loading, health checks, ad-hoc indexing |
| **Event Bus** | Pub/sub patterns, wildcard subscriptions, SSE formatting |
| **Discovery** | Tree-sitter parsing, query packs, multi-language |
| **CLI** | Config management, metrics, agent listing, daemon control |
| **AgentKVStore** | Message history, tool results, metadata, snapshots |
| **vLLM Integration** | AsyncOpenAI client, FunctionGemma plugin, grammar |
| **Grail Scripts** | Pym tools, external functions, Cairn execution |

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/remora/agent_graph.py` | Agent composition & execution |
| `src/remora/workspace.py` | Workspace management |
| `src/remora/hub/daemon.py` | Hub background daemon |
| `src/remora/hub/server.py` | Hub REST API server |
| `src/remora/hub_client.py` | Hub client for context |
| `src/remora/event_bus.py` | Unified event system |
| `src/remora/discovery/discoverer.py` | Tree-sitter discovery |
| `src/remora/agent_state.py` | KV-based state |
| `src/remora/config.py` | Configuration system |
| `agents/*/bundle.yaml` | Agent bundle definitions |
| `agents/*/tools/*.pym` | Grail tool scripts |
