# Remora Demo Development Log

## Overview

This document tracks the development of the Remora HTTP Multi-Agent Demo, which demonstrates Remora's ability to invoke multiple distinct agent bundles over HTTP with real vLLM calls.

---

## 1. Files Created

### Demo Scripts (`demo/`)

| File | Purpose |
|------|---------|
| `setup_demo.py` | Creates demo input files and workspace directories |
| `start_server.py` | Starts the Remora Hub Server on port 8001 |
| `api_demo.py` | HTTP client demonstrating fire-and-forget pattern with SSE events |
| `run_agent.py` | Standalone demo using structured-agents directly with vLLM |

### Demo Agent Bundle (`demo/agents/simple_analyzer/`)

| File | Purpose |
|------|---------|
| `bundle.yaml` | Bundle manifest defining the agent config |
| `tools/write_result.pym` | Grail tool that returns analysis results |
| `tools/write_result/inputs.json` | Tool schema definition |

### Documentation (`demo/`)

| File | Purpose |
|------|---------|
| `README.md` | User/developer/investor focused documentation |

---

## 2. Architecture

### The Demo Flow

```
api_demo.py (HTTP Client)
    │
    ├─► POST /graph/execute (fire-and-forget, returns graph_id immediately)
    │
    ├─► GET /events (SSE stream for real-time events)
    │
    └─► GET /api/files (query workspace state)

Hub Server (port 8001)
    │
    ├─► AgentGraph (compiles and executes agent workflows)
    │
    ├─► structured-agents (loads bundles, runs AgentKernel)
    │
    ├─► vLLM at remora-server:8000 (actual LLM calls)
    │
    └─► EventBus (streams agent:started, agent:completed events)

Demo Agent Bundle (simple_analyzer)
    │
    ├─► bundle.yaml (Qwen model config, prompts, tool definitions)
    │
    └─► tools/write_result.pym (Grail tool for returning results)
```

### Key Components

1. **Fire-and-Forget HTTP**: Client POSTs to `/graph/execute` and immediately gets a `graph_id` - no waiting for completion
2. **SSE Events**: Real-time streaming of agent lifecycle events via `/events`
3. **structured-agents**: Uses `AgentKernel`, `QwenPlugin`, `GrailBackend` for actual vLLM calls
4. **Bundle System**: Agent capabilities packaged as bundles with `bundle.yaml` manifests

---

## 3. Issues Found and Fixes

### Issue 1: SSE Events Showed Datastar HTML Instead of JSON

**Symptom**: Connecting to `/subscribe` returned full HTML page patches instead of raw event JSON.

**Root Cause**: The `/subscribe` endpoint is designed for the Datastar dashboard UI, not API clients.

**Fix**: Created a new `/events` endpoint that streams raw JSON events:
- Updated `src/remora/hub/server.py` to add `/events` route
- Used `StreamingResponse` with manual SSE formatting
- Updated `api_demo.py` to connect to `/events` instead of `/subscribe`

### Issue 2: HTTP Client Blocked Waiting for Response

**Symptom**: Second POST request timed out while waiting for first agent to complete.

**Root Cause**: Demo was incorrectly waiting for completion before sending next request.

**Fix**: Implemented proper fire-and-forget pattern:
- Client sends POST, immediately gets `graph_id` 
- Uses separate SSE listener for events
- Demonstrates true async behavior

### Issue 3: Bundle Names Showed "default" Instead of Actual Bundle

**Symptom**: Events showed `"bundle": "default"` even when requesting specific bundles.

**Root Cause**: The `read_signals()` function from Datastar only works for Datastar requests (has `Datastar-Request` header). Regular JSON POSTs returned `None`, causing fallback to default.

**Fix**: Modified `execute_graph` in `server.py` to handle both:
```python
# Handle both Datastar signals and regular JSON POST
signals = await read_signals(request) or {}

# If signals is empty, try reading plain JSON body
if not signals and request.method == "POST":
    try:
        body = await request.body()
        if body:
            signals = json.loads(body)
    except json.JSONDecodeError:
        signals = {}
```

### Issue 4: Bundle Path Resolution

**Symptom**: Server couldn't find bundles in `demo/agents/` directory.

**Fix**: Added demo paths to bundle search paths in `agent_graph.py`:
```python
search_paths = [
    Path.cwd() / "agents" / bundle_name,
    Path(__file__).parent.parent.parent / "agents" / bundle_name,
    Path.cwd() / ".grail" / "agents" / bundle_name,
    Path(__file__).parent.parent.parent / ".grail" / "agents" / bundle_name,
    Path.cwd() / "demo" / "agents" / bundle_name,
    Path(__file__).parent.parent.parent / "demo" / "agents" / bundle_name,
]
```

### Issue 5: Demo Agent Bundle Not Found

**Symptom**: Bundle loader falling back to simulation.

**Fix**: Updated `api_demo.py` to use actual bundle name `simple_analyzer` instead of non-existent `run_linter`.

### Issue 6: Server Port Conflict

**Symptom**: `Address already in use` errors when restarting server.

**Fix**: User manually restarts server between test runs.

---

## 4. Current Working State

The demo now successfully:

1. ✅ **Fire-and-forget POST** - Returns `graph_id` immediately
2. ✅ **Real bundle loading** - Uses `simple_analyzer` bundle (not "default")
3. ✅ **SSE event streaming** - Events show actual bundle name
4. ✅ **Agent completion** - Agents run and complete

### Remaining Issues & Analysis

**Issue A: Simulation Running Instead of Real Kernel**

**Current Behavior**:
```
"result": "{'status': 'completed', 'output': 'Executed simple_analyzer on code'}"
```

This is the simulation output, not the real vLLM result.

**Evidence**: The `_simulate_execution` function in `agent_graph.py` returns:
```python
return {"status": "completed", "output": f"Executed {agent.bundle} on {agent.target_type}"}
```

**Root Cause Analysis**:

1. The bundle name is now correct (`simple_analyzer`)
2. But `_get_bundle_path()` might not be finding the bundle
3. Or the bundle loading is failing and falling back to simulation

**Likely Fix**: Need to add debug logging to `_execute_agent` to see if:
- `bundle_path` is being found
- `load_bundle()` is succeeding
- `_run_kernel()` is being called

The most likely issue is that the bundle path resolution in `_get_bundle_path` isn't working correctly when the server runs from a different directory context.

**Server Context Issue**:
- Server runs from `demo/` directory (based on `start_server.py`)
- But `Path.cwd()` in `agent_graph.py` resolves differently depending on where the module was loaded from
- The search paths need to account for the server's working directory

**Probable Fix**:
Add explicit logging in `_execute_agent` to see what's happening, or make the bundle path resolution more robust by using absolute paths relative to the project root.

**Issue B: vLLM Connection in Hub Server**

Even when the kernel runs, it might fail to connect to vLLM because:
- The standalone `run_agent.py` uses `http://remora-server:8000/v1`
- The Hub server's `_run_kernel` also uses this URL
- But the network context might be different

---

## 5. How to Run

### Prerequisites

1. **vLLM Server** (running at `remora-server:8000`):
   ```bash
   vllm serve Qwen/Qwen3-4B-Instruct-2507-FP8 --dtype half --port 8000
   ```

2. **Install Dependencies**:
   ```bash
   uv pip install -e ".[frontend,backend]"
   uv pip install httpx httpx-sse
   ```

### Running the Demo

**Terminal 1** - Setup:
```bash
cd demo
python setup_demo.py
```

**Terminal 2** - Start Hub Server:
```bash
cd demo
python start_server.py
```

**Terminal 3** - Run HTTP Client:
```bash
cd demo
python api_demo.py
```

---

## 6. Standalone Demo (run_agent.py)

For direct structured-agents testing without HTTP:

```bash
cd demo
python run_agent.py
```

This demonstrates:
- Direct `AgentKernel` usage
- Qwen plugin with vLLM
- Tool execution via GrailBackend
- Result extraction from conversation history
- Writing output to local file

---

## 7. Next Steps

1. **Wire up actual vLLM calls** in the Hub server's `_run_kernel` method
2. **Add result persistence** - write agent results to workspace files
3. **Create more bundles** - lint, docstring, test agents
4. **Human-in-the-loop** - implement ask_user() for blocked agents

---

## 8. Key Files Reference

| File | Lines | Purpose |
|------|-------|---------|
| `src/remora/agent_graph.py` | 530 | AgentGraph, AgentNode, execution |
| `src/remora/hub/server.py` | ~350 | Hub REST API server |
| `src/remora/event_bus.py` | ~285 | Event streaming system |
| `demo/api_demo.py` | ~150 | HTTP client demo |
| `demo/run_agent.py` | ~120 | Direct structured-agents demo |
| `demo/agents/simple_analyzer/bundle.yaml` | ~25 | Agent bundle manifest |

---

*Last Updated: 2026-02-25*
