# Remora Ultimate HTTP + Multi-Agent Demo Guide

This guide provides a comprehensive, step-by-step implementation for testing Remora's full capabilities over **actual HTTP calls**, while specifically demonstrating how easily we can switch between and invoke **multiple distinct agent bundles** (powered by Grail scripts and `structured-agents`).

Instead of running the `AgentGraph` directly in the same process, we will spin up the `HubServer` (using FastAPI/Starlette) and use a separate client script to trigger and monitor agent execution over network calls.

This ensures all functionality is verified via real HTTP boundaries, testing JSON payloads, REST endpoints (`/graph/execute`), and Server-Sent Events (`/subscribe`).

---

## 1. Prerequisites

Before running the demo, ensure your environment is configured.

**1. Start the vLLM Server**
Remora interacts with local models via the OpenAI-compatible vLLM server. Start the server in a separate terminal:
```bash
vllm serve Qwen/Qwen3-4B-Instruct-2507-FP8 --dtype half --port 8000
```

**2. Install Dependencies**
Ensure `remora` and its associated components from `.context/` are installed using `uv`:
```bash
uv pip install -e ".[frontend,backend]"
# We also need httpx and httpx-sse for our HTTP client demo
uv pip install httpx httpx-sse
```

---

## 2. Scaffolding the Input Data (`setup_demo.py`)

First, we generate a dummy project (`demo_input`) containing files that need **linting** and files that need **docstrings**, because we are going to test two entirely different agent behaviors over HTTP.

Create a file named `setup_demo.py` and run it:

```python
#!/usr/bin/env python3
"""setup_demo.py - Scaffolds the input environment for the Remora Demo."""

from pathlib import Path
import textwrap

def generate_file(path_str: str, content: str):
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(textwrap.dedent(content).strip() + "\n")
    print(f"✅ Created {path}")

def main():
    print("🚀 Scaffolding Remora Demo Environment...")
    
    # 1. Dummy Python Project Files
    
    # Needs a linting fix (unused imports)
    generate_file(
        "demo_input/src/main.py",
        """
        import os
        import sys
        
        def calculate_sum(a, b):
            result = a + b
            return result
        """
    )
    
    # Needs a docstring
    generate_file(
        "demo_input/src/utils/helpers.py",
        """
        def format_greeting(name: str) -> str:
            return f"Hello, {name}!"
        """
    )
    
    # 2. Remora Configuration
    generate_file(
        "demo_input/remora.yaml",
        """
        discovery:
          query_pack: remora_core
        server:
          base_url: http://localhost:8000/v1
          default_adapter: Qwen/Qwen3-4B-Instruct-2507-FP8
          default_plugin: function_gemma
        """
    )

    # 3. Create a workspace directory for the server
    Path("demo_workspaces").mkdir(exist_ok=True)
    print("\n🎉 Scaffolding complete. You are ready to start the server.")

if __name__ == "__main__":
    main()
```

Run this script:
```bash
python setup_demo.py
```

---

## 3. Starting the Remora Hub Server

We need to start the standalone REST API Server. This server will host the `/graph/execute`, `/subscribe`, and `/api/files` endpoints. It dynamically loads agent bundles based on the `bundle` name passed during the HTTP POST.

Open a **new terminal** and run the following python script `start_server.py`:

```python
#!/usr/bin/env python3
"""start_server.py - Runs the Remora Hub standalone server."""

import asyncio
import logging
from pathlib import Path
from remora.hub.server import run_hub

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

if __name__ == "__main__":
    print("🟢 Starting Remora Hub Server on http://0.0.0.0:8001")
    # Using port 8001 for Hub Server to avoid clashing with vLLM on 8000
    asyncio.run(run_hub(
        workspace_path=Path("demo_workspaces/global.workspace"),
        host="0.0.0.0",
        port=8001,
        workspace_base=Path("demo_workspaces")
    ))
```

Run the server:
```bash
python start_server.py
```
Leave this terminal running. 

---

## 4. The Multi-Agent HTTP Client (`api_demo.py`)

This script acts as the external consumer. It makes actual HTTP calls to the running Hub Server using `httpx`. 

We will demonstrate Remora's ability to easily switch between agents by sending **two different POST requests**:
1. Invoking the `lint` agent bundle targeting `main.py`.
2. Invoking the `docstring` agent bundle targeting `helpers.py`.

It will also listen to the SSE event stream to show how multiple parallel graph executions emit typed events.

Create a file named `api_demo.py` in another terminal:

```python
#!/usr/bin/env python3
"""api_demo.py - Tests the Hub Server via multiple HTTP execution calls."""

import asyncio
import httpx
from httpx_sse import aconnect_sse
from pathlib import Path
import json

HUB_URL = "http://localhost:8001"

async def listen_to_events(stop_event: asyncio.Event, expected_completions: int):
    """Connects to the SSE stream and prints events as they happen."""
    completed_graphs = 0
    try:
        async with httpx.AsyncClient() as client:
            print(f"🔌 Connecting to Event Stream at {HUB_URL}/subscribe...")
            async with aconnect_sse(client, "GET", f"{HUB_URL}/subscribe") as event_source:
                async for sse in event_source.aiter_sse():
                    if sse.event == "ping":
                        continue
                    print(f"\n🔔 [SSE Event] {sse.event.upper()}")
                    
                    try:
                        payload = json.loads(sse.data)
                        print(f"   Payload: {json.dumps(payload, indent=2)}")
                    except json.JSONDecodeError:
                        print(f"   Payload: {sse.data}")
                    
                    # Track graph completions
                    if sse.event == "graph:completed" or sse.event == "graph:failed":
                        completed_graphs += 1
                        if completed_graphs >= expected_completions:
                            print("\n🛑 Received all expected graph completions. Terminating monitor.")
                            stop_event.set()
                            break
    except Exception as e:
        print(f"❌ Event Stream Error: {e}")
        stop_event.set()

async def trigger_execution(agent_bundle: str, file_path: str, target_code: str):
    """Makes a physical POST request to start an agent graph compilation/execution."""
    payload = {
        "bundle": agent_bundle,
        "target_path": file_path,
        "target": target_code
    }

    print(f"\n🚀 Sending POST request for '{agent_bundle}' bundle...")
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{HUB_URL}/graph/execute", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success! Server returned Graph ID: {data.get('graph_id')} assigned to '{agent_bundle}'")
        else:
            print(f"❌ HTTP Error for {agent_bundle}: {response.status_code} - {response.text}")

async def list_files():
    """Demonstrates listing the workspace generated by the server via HTTP."""
    print("\n📂 Fetching final workspace state via HTTP GET /api/files...")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{HUB_URL}/api/files?path=")
        if response.status_code == 200:
            print(f"✅ Workspace API returned: {json.dumps(response.json(), indent=2)}")

async def main():
    print("=" * 70)
    print("🌐 REMORA MULTI-AGENT HTTP CLIENT DEMO")
    print("=" * 70)
    
    stop_event = asyncio.Event()

    # We expect 2 graphs to complete (lint and docstring)
    listener_task = asyncio.create_task(listen_to_events(stop_event, expected_completions=2))

    # Give the listener a second to connect
    await asyncio.sleep(1)

    # Trigger Agent 1: The Linter
    await trigger_execution(
        agent_bundle="lint",
        file_path="demo_input/src/main.py",
        target_code="def calculate_sum(a, b):\n    result = a + b\n    return result"
    )

    # Introduce a slight delay just so logs differentiate
    await asyncio.sleep(0.5)

    # Trigger Agent 2: The Docstring Writer
    await trigger_execution(
        agent_bundle="docstring",
        file_path="demo_input/src/utils/helpers.py",
        target_code="def format_greeting(name: str) -> str:\n    return f\"Hello, {name}!\""
    )

    print("\n⏳ Both requests sent off. AgentGraphs are running asynchronously on the server. Waiting on EventBus streams...\n")

    # Wait for the completion event from the SSE stream
    await stop_event.wait()
    listener_task.cancel()
    
    # Query final state
    await list_files()
    
    print("\n" + "=" * 70)
    print("🎉 CLIENT DEMO COMPLETE: Multi-Agent functionality verified.")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
```

Run the API demo client:
```bash
python api_demo.py
```

---

## 5. Validating the Results

By running `api_demo.py`, you strictly enforce network separation between the graph caller and the executor, and beautifully highlight Remora's flexibility:

1. **Verify the Multi-Agent Dispatch:** The terminal running `api_demo.py` will show two totally separate `POST` requests—one mapped to the `lint` bundle and one mapped to the `docstring` bundle.
2. **Verify Event Streaming Across Bundles:** As events stream back linearly via SSE, you will see `tool:called` payloads dynamically referring to different Grail `.pym` tool invocations (e.g. `run_linter.pym` vs `write_docstring.pym`), all emitted in real-time from the backend's remote execution of the `structured-agents` framework.
3. **Verify the API File Listing:** Once execution is finished, `api_demo.py` fetches the workspace layout from `/api/files`. Since two graphs were deployed, you will see two randomly generated workspace IDs inside the server's working directory!
4. **Inspect the Server Terminal:** The terminal running `start_server.py` will show the internal `_build_agent_graph` logic mounting disparate AI plugins and grammar parsers conditionally on the parsed JSON body.

By doing this, you've demonstrated that Remora transforms a single server endpoint (`/graph/execute`) into a universal code-automation dispatcher capable of routing any `AgentGraph` request to any Grail tool bundle seamlessly.
