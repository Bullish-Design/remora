# Remora Integration Test Suite Review

## Executive Summary

This document provides a comprehensive analysis of the Remora integration test suite's effectiveness at testing **actual, real-world functionality** against live infrastructure (vLLM servers, AgentFS/Cairn workspaces) rather than mocked implementations.

**Overall Assessment: B+**

The integration test suite demonstrates a strong commitment to real infrastructure testing with no mocking. However, significant coverage gaps exist in testing the full breadth of Remora's capabilities, particularly around edge cases, error recovery, multi-language support, and complex graph execution scenarios.

---

## 1. Remora Library Overview

### 1.1 What is Remora?

Remora (v0.4.3) is a **local agent orchestration framework** for running structured, tool-calling code analysis agents on Python projects. It's designed to:

- Decompose code analysis into fine-grained AST-level units (functions, classes, files)
- Run specialized AI agents on each code unit independently and in parallel
- Manage isolated workspaces per agent execution using Cairn
- Provide a unified event-driven architecture for all state changes and UI updates
- Enable human-in-the-loop workflows with dashboard integration

### 1.2 Core Capabilities That Require Integration Testing

| Capability | Description | Test Priority |
|------------|-------------|---------------|
| **Code Discovery** | Tree-sitter based parsing of Python, JS, TS, Go, Rust, Markdown, TOML, YAML, JSON | HIGH |
| **Graph Building** | Convert discovered nodes to executable agent dependency graph | HIGH |
| **Graph Execution** | Execute agents in topological order with bounded concurrency | CRITICAL |
| **vLLM Integration** | Multi-turn agent execution with tool calling via structured-agents | CRITICAL |
| **Workspace Isolation** | Per-agent Cairn workspaces with CoW semantics | CRITICAL |
| **Grail Tool Execution** | Execute `.pym` scripts with externals and virtual FS | HIGH |
| **Event System** | Pub/sub event bus for lifecycle events | MEDIUM |
| **Error Policies** | STOP_GRAPH, SKIP_DOWNSTREAM, CONTINUE | HIGH |
| **Context Building** | Two-track memory (short-term + long-term) | MEDIUM |
| **Checkpointing** | Save/restore execution state | MEDIUM |
| **Dashboard API** | SSE/WebSocket endpoints for real-time UI | MEDIUM |
| **CLI Interface** | `remora run` command execution | MEDIUM |
| **Indexer Daemon** | Background file watching and incremental analysis | LOW |

---

## 2. Integration Test Suite Structure

### 2.1 Test File Inventory

| File | Lines | Purpose | Real Infrastructure |
|------|-------|---------|---------------------|
| `test_smoke_real.py` | 125 | Basic vLLM + Cairn smoke tests | vLLM + AgentFS |
| `test_executor_real.py` | 182 | End-to-end executor workflow | vLLM + AgentFS |
| `test_agent_workflow_real.py` | 381 | Concurrent workflow stress test | vLLM + AgentFS |
| `test_cli_real.py` | 77 | CLI subprocess execution | vLLM + AgentFS |
| `test_error_policy_real.py` | 93 | Error policy validation | vLLM + AgentFS |
| `test_checkpoint_roundtrip.py` | 52 | Checkpoint serialization | None (unit-style) |
| `test_dashboard_real.py` | 79 | Dashboard API + events | vLLM + AgentFS |
| **cairn/test_write_semantics.py** | 38 | CoW write isolation | AgentFS |
| **cairn/test_read_semantics.py** | 80 | Read fall-through behavior | AgentFS |
| **cairn/test_agent_isolation.py** | 81 | Agent-to-agent isolation | AgentFS |
| **cairn/test_workspace_isolation.py** | 104 | Stable workspace protection | AgentFS |
| **cairn/test_lifecycle.py** | 137 | Workspace open/close/cleanup | AgentFS |
| **cairn/test_concurrent_safety.py** | 153 | Concurrency stress tests | AgentFS |
| **cairn/test_error_recovery.py** | 77 | Error handling | AgentFS |
| **cairn/test_path_resolution.py** | 69 | Path normalization | AgentFS |
| **cairn/test_kv_operations.py** | 80 | Submission KV store | AgentFS |
| **cairn/test_merge_operations.py** | 29 | Merge (unsupported) | AgentFS |

**Total Integration Test Lines: ~1,837**

### 2.2 Infrastructure Dependencies

```
┌─────────────────────────────────────────────────────────────┐
│                    Integration Tests                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  vLLM Server (http://remora-server:8000/v1)                │
│  ├── Model: Qwen/Qwen3-4B-Instruct-2507-FP8               │
│  ├── Features: Auto tool choice, XML parser, prefix cache  │
│  └── Max tokens: 32768                                     │
│                                                             │
│  AgentFS/Fsdantic                                          │
│  ├── SQLite-backed virtual filesystem                      │
│  ├── Copy-on-write workspace semantics                     │
│  └── KV store for submissions                              │
│                                                             │
│  Cairn Runtime                                             │
│  ├── Workspace manager                                     │
│  ├── External function bindings                            │
│  └── Lifecycle management                                  │
│                                                             │
│  Grail Engine                                              │
│  ├── .pym script execution                                 │
│  ├── Virtual filesystem                                    │
│  └── External function injection                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. What IS Tested (Strengths)

### 3.1 Real vLLM Model Inference

**Location:** `test_smoke_real.py`, `test_executor_real.py`, `test_agent_workflow_real.py`

The tests execute **actual model inference** against a live vLLM server:

```python
# From test_executor_real.py:84-171
config = RemoraConfig(
    model=ModelConfig(
        base_url=VLLM_CONFIG["base_url"],  # Real server
        api_key=VLLM_CONFIG["api_key"],
        default_model=VLLM_CONFIG["model"],  # Real model
    ),
    ...
)
executor = GraphExecutor(config, event_bus, project_root=project_root)
results = await executor.run(graph, "tool-call")  # Real inference
```

**What's validated:**
- Model responses are received (`ModelResponseEvent`)
- Tool calls are generated by the model
- Tool results are processed
- Multi-turn conversations work
- Agent completes successfully

**Assessment:** STRONG - Tests real model behavior with actual inference.

### 3.2 Real Workspace Operations (Cairn/AgentFS)

**Location:** `tests/integration/cairn/`

The Cairn test suite validates **actual SQLite-backed workspace operations**:

```python
# From test_agent_isolation.py:12-24
ws1 = await workspace_service.get_agent_workspace("agent-1")
ws2 = await workspace_service.get_agent_workspace("agent-2")

await ws1.write("agent1_private.txt", "Private to agent-1")
exists_in_ws2 = await ws2.exists("agent1_private.txt")
assert not exists_in_ws2  # Real isolation validated
```

**What's validated:**
- Database file creation (`stable.db`, `{agent_id}.db`)
- Read/write operations persist to actual SQLite
- Copy-on-write semantics work correctly
- Agent isolation is enforced at the database level
- Concurrent operations don't corrupt data

**Assessment:** STRONG - Comprehensive coverage of workspace semantics.

### 3.3 Real Tool Execution Flow

**Location:** `test_executor_real.py:84-181`, `test_smoke_real.py:66-124`

The tests validate the complete **Grail tool execution pipeline**:

```python
# From test_smoke_real.py:79-106
tool_path.write_text("""
from grail import Input, external

path: str = Input("path")
content: str = Input("content")

@external
async def write_file(path: str, content: str) -> bool:
    ...

await write_file(path, content)
result = {"summary": f"wrote {path}", "outcome": "success"}
result
""")

tool = RemoraGrailTool(tool_path, externals=externals, files_provider=files_provider)
result = await tool.execute({"path": str(target_path), "content": "hello"}, None)
```

**What's validated:**
- Grail script parsing and loading
- External function injection (`write_file`, `submit_result`)
- Tool execution with real externals
- Result capture and serialization

**Assessment:** GOOD - Core tool flow is tested, but limited tool variety.

### 3.4 Concurrent Stress Testing

**Location:** `test_agent_workflow_real.py`, `cairn/test_concurrent_safety.py`

The workflow test runs **20 concurrent agent executions** by default:

```python
# From test_agent_workflow_real.py:54-119
DEFAULT_RUNS = int(os.environ.get("REMORA_WORKFLOW_RUNS", "20"))
DEFAULT_CONCURRENCY = int(os.environ.get("REMORA_WORKFLOW_CONCURRENCY", "8"))
DEFAULT_MIN_SUCCESS = float(os.environ.get("REMORA_WORKFLOW_MIN_SUCCESS", "0.8"))

# ... runs 20 trials with 8 concurrent, requires 80% success rate
```

**What's validated:**
- System handles concurrent vLLM requests
- Workspace isolation under load
- No race conditions in graph execution
- Performance under realistic load

**Assessment:** EXCELLENT - Real-world concurrent workload simulation.

### 3.5 Error Policy Behavior

**Location:** `test_error_policy_real.py`

Tests validate **actual error propagation** through the graph:

```python
# From test_error_policy_real.py:58-92
config = RemoraConfig(
    execution=ExecutionConfig(
        timeout=0.001,  # Force timeout failure
        error_policy=ErrorPolicy.SKIP_DOWNSTREAM,
    ),
    ...
)
# ... validates file node fails, function nodes are skipped
assert file_nodes[0].id in error_agents
assert skipped_agents == {node.id for node in function_nodes}
```

**Assessment:** GOOD - Tests one policy, but not all three.

---

## 4. What is NOT Tested (Gaps)

### 4.1 CRITICAL GAPS

#### 4.1.1 Multi-Language Discovery (NOT TESTED)

**Remora supports:** Python, JavaScript, TypeScript, Go, Rust, Markdown, TOML, YAML, JSON

**Tests only use:** Python

```python
# Every test uses the same pattern:
target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
nodes = discover([target_file], languages=["python"])
```

**Missing coverage:**
- JavaScript/TypeScript function and class discovery
- Go function and struct discovery
- Rust function and impl discovery
- Markdown section discovery
- TOML/YAML table discovery
- Cross-language project discovery

**Impact:** HIGH - Multi-language is a core advertised capability with zero integration coverage.

#### 4.1.2 Complex Graph Topologies (NOT TESTED)

**Tests only cover:** Single-node graphs or simple file→function dependency

**Missing coverage:**
- Deep dependency chains (A→B→C→D)
- Diamond dependencies (A→B, A→C, B→D, C→D)
- Large graphs (50+ nodes)
- Circular dependency detection
- Cross-file dependencies

```python
# Example missing test:
# test_diamond_dependency_execution
nodes = [
    create_node("A", dependencies=[]),
    create_node("B", dependencies=["A"]),
    create_node("C", dependencies=["A"]),
    create_node("D", dependencies=["B", "C"]),
]
graph = build_graph(nodes)
results = await executor.run(graph)
# Validate D waits for both B and C
```

**Impact:** HIGH - Real-world codebases have complex dependency structures.

#### 4.1.3 Real Code Analysis Scenarios (NOT TESTED)

All tests use trivial code snippets:

```python
# Every test:
target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
```

**Missing coverage:**
- Multi-function files
- Class hierarchies with methods
- Decorator-heavy code
- Import dependencies
- Large file handling (1000+ lines)
- Edge cases (empty files, syntax errors)

**Impact:** HIGH - Tests don't reflect real codebase complexity.

#### 4.1.4 Model Response Variations (NOT TESTED)

Tests assume the model always:
1. Makes the correct tool call
2. Passes valid arguments
3. Completes within max_turns

**Missing coverage:**
- Model refuses to call tools (responds with text only)
- Model hallucinates tool names
- Model passes invalid argument types
- Model exceeds max_turns
- Model returns malformed JSON
- Model streaming interruption

**Impact:** CRITICAL - LLM behavior is inherently unpredictable.

### 4.2 HIGH-PRIORITY GAPS

#### 4.2.1 Error Recovery and Resilience (MINIMAL)

**Current coverage:** Only `test_error_recovery.py` (cairn)

**Missing coverage:**
- vLLM server unavailable mid-execution
- vLLM server timeout during streaming
- Network partition during tool execution
- Disk full during workspace write
- Memory pressure during large graph execution
- Graceful degradation under load

#### 4.2.2 Context Building Integration (NOT TESTED)

`ContextBuilder` is a core component but integration tests don't validate:
- Short-track memory accumulation across turns
- Long-track knowledge from completed agents
- Context injection into agent prompts
- Context overflow handling

#### 4.2.3 All Three Error Policies (PARTIAL)

**Tested:** `SKIP_DOWNSTREAM`
**Not tested:** `STOP_GRAPH`, `CONTINUE`

```python
# Missing tests:
def test_stop_graph_policy():
    # First failure should stop entire graph

def test_continue_policy():
    # Failures should not affect other nodes
```

#### 4.2.4 Bundle Configuration Variations (NOT TESTED)

Tests use minimal bundles:

```yaml
name: smoke_agent
model: qwen
initial_context:
  system_prompt: "..."
agents_dir: tools
max_turns: 2
```

**Missing coverage:**
- Grammar configuration (EBNF, parallel calls)
- Custom model overrides per bundle
- Termination conditions
- Node type filtering
- Priority ordering
- Missing/invalid bundle files

#### 4.2.5 Checkpoint Restore During Execution (NOT TESTED)

`test_checkpoint_roundtrip.py` only tests serialization, not:
- Resume execution from checkpoint
- Restore with modified graph
- Workspace state restoration
- Partial completion resume

### 4.3 MEDIUM-PRIORITY GAPS

#### 4.3.1 Dashboard API Surface (MINIMAL)

`test_dashboard_real.py` only tests:
- POST `/run` endpoint

**Missing coverage:**
- GET `/events` SSE stream
- GET `/subscribe` HTML stream
- POST `/input` human-in-the-loop
- WebSocket connections
- Concurrent dashboard clients

#### 4.3.2 CLI Command Coverage (MINIMAL)

`test_cli_real.py` only tests:
- `remora run <target> --config <config>`

**Missing coverage:**
- `remora-dashboard run`
- Invalid arguments handling
- Configuration file errors
- Verbose/quiet modes

#### 4.3.3 Indexer Daemon (NOT TESTED)

The background indexer (`indexer/daemon.py`, `indexer/scanner.py`) has zero integration tests:
- File watching
- Incremental indexing
- Cache management
- Daemon lifecycle

---

## 5. Test Quality Analysis

### 5.1 Assertion Depth

| Test File | Assertion Quality | Issues |
|-----------|-------------------|--------|
| `test_smoke_real.py` | SHALLOW | Only checks `results` is truthy and events exist |
| `test_executor_real.py` | MODERATE | Validates specific event types and result values |
| `test_agent_workflow_real.py` | DEEP | Comprehensive failure categorization and reporting |
| `test_error_policy_real.py` | MODERATE | Validates event types but not full state |
| `cairn/*` | DEEP | Thorough semantic validation |

**Best Example** (`test_agent_workflow_real.py`):
```python
# Comprehensive failure categorization
if not had_tool_call:
    return TrialResult(stage="model", error_type="missing_tool_call")
if not had_tool_result:
    return TrialResult(stage="tool", error_type="missing_tool_result")
if summary.output != spec.summary:
    return TrialResult(stage="submission", error_type="summary_mismatch")
```

**Worst Example** (`test_smoke_real.py`):
```python
# Too shallow
assert results  # Just checks truthy
assert any(isinstance(event, ModelResponseEvent) for event in events)  # Any event
```

### 5.2 Test Isolation

**Issue:** Tests share vLLM server state

The vLLM server maintains:
- KV cache
- Request queues
- Model state

Tests don't explicitly reset server state between runs, which could cause:
- Intermittent failures under load
- Order-dependent test results

### 5.3 Determinism

**Issue:** Model inference is non-deterministic

Even with temperature=0, LLM outputs vary:
- Different tokenization
- Floating-point precision
- Server-side batching effects

The `test_agent_workflow_real.py` handles this by allowing 80% success rate:
```python
DEFAULT_MIN_SUCCESS = float(os.environ.get("REMORA_WORKFLOW_MIN_SUCCESS", "0.8"))
```

This is pragmatic but masks systematic issues.

---

## 6. Recommendations

### 6.1 Critical Additions

1. **Multi-Language Discovery Tests**
   ```python
   @pytest.mark.parametrize("language,content,expected_type", [
       ("javascript", "function hello() { return 'hi'; }", "function"),
       ("typescript", "interface User { name: string; }", "interface"),
       ("go", "func main() {}", "function"),
       ("rust", "fn main() {}", "function"),
   ])
   async def test_multi_language_discovery(language, content, expected_type):
       # ...
   ```

2. **Complex Graph Tests**
   ```python
   async def test_diamond_dependency_graph():
       # Build A→B, A→C, B→D, C→D and verify execution order

   async def test_large_graph_performance():
       # 100+ nodes with bounded concurrency
   ```

3. **Model Failure Handling**
   ```python
   async def test_model_text_only_response():
       # System prompt asks for tool call, model responds with text

   async def test_model_invalid_tool_call():
       # Model calls non-existent tool
   ```

### 6.2 High-Priority Additions

4. **Error Policy Complete Coverage**
   ```python
   async def test_stop_graph_policy():
       # ...

   async def test_continue_policy():
       # ...
   ```

5. **Context Builder Integration**
   ```python
   async def test_context_accumulation_across_agents():
       # Validate short-track and long-track memory
   ```

6. **Real Code Complexity**
   ```python
   @pytest.fixture
   def complex_python_file():
       return '''
   class UserService:
       def __init__(self, db):
           self.db = db

       @auth_required
       async def get_user(self, user_id: int) -> User:
           ...
   '''
   ```

### 6.3 Test Infrastructure Improvements

7. **Add vLLM Health Check**
   ```python
   @pytest.fixture(scope="session")
   def vllm_health():
       # Verify model loaded and responding
       # Check token generation works
       # Validate tool calling enabled
   ```

8. **Add Test Result Analytics**
   - Track success rates over time
   - Identify flaky tests
   - Measure latency distribution

9. **Parameterize Existing Tests**
   ```python
   @pytest.mark.parametrize("max_concurrency", [1, 4, 8])
   @pytest.mark.parametrize("max_turns", [1, 3, 5])
   async def test_executor_configuration_matrix(max_concurrency, max_turns):
       # ...
   ```

---

## 7. Coverage Matrix

### Current Coverage

| Component | Unit Tests | Integration Tests | Real Infrastructure |
|-----------|------------|-------------------|---------------------|
| Discovery | Yes | No | N/A |
| Graph Building | Yes | Implicit | N/A |
| Graph Execution | No | Yes | vLLM + AgentFS |
| Workspace (Cairn) | No | Yes | AgentFS |
| Tool Execution (Grail) | No | Yes | vLLM + AgentFS |
| Event Bus | Yes | Yes | N/A |
| Context Builder | Yes | No | N/A |
| Checkpointing | No | Partial | N/A |
| Dashboard | No | Minimal | vLLM + AgentFS |
| CLI | No | Minimal | vLLM + AgentFS |
| Indexer | No | No | N/A |

### Recommended Coverage

| Component | Priority | Estimated Tests | Estimated Lines |
|-----------|----------|-----------------|-----------------|
| Multi-language Discovery | CRITICAL | 8-10 | 200-300 |
| Complex Graph Execution | CRITICAL | 5-7 | 250-350 |
| Model Failure Handling | CRITICAL | 6-8 | 200-300 |
| Error Policy Coverage | HIGH | 3 | 150-200 |
| Context Integration | HIGH | 4-5 | 200-250 |
| Bundle Variations | HIGH | 5-6 | 200-250 |
| Dashboard API | MEDIUM | 6-8 | 250-350 |
| Indexer Daemon | MEDIUM | 4-5 | 200-250 |
| CLI Commands | LOW | 3-4 | 100-150 |

---

## 8. Conclusion

The Remora integration test suite demonstrates **strong fundamentals**:
- True integration testing against real infrastructure (no mocks)
- Good coverage of workspace isolation semantics
- Reasonable concurrent stress testing
- Pragmatic handling of LLM non-determinism

However, the suite has **significant blind spots**:
- Single-language testing despite multi-language support
- Trivial code samples that don't reflect real codebases
- Missing coverage of model misbehavior scenarios
- Incomplete error policy testing
- No context builder integration tests
- No indexer daemon tests

**The suite tests the happy path well but inadequately tests edge cases, failure modes, and the full breadth of advertised capabilities.**

To achieve production-grade confidence, the test suite needs approximately **40-60 additional integration tests** (1,500-2,500 lines) covering the gaps identified above.

---

## Appendix A: Test Execution Requirements

### Environment Variables

```bash
# vLLM Configuration
REMORA_TEST_VLLM_BASE_URL=http://remora-server:8000/v1
REMORA_TEST_VLLM_API_KEY=EMPTY
REMORA_TEST_VLLM_MODEL=Qwen/Qwen3-4B-Instruct-2507-FP8

# Workflow Test Tuning
REMORA_WORKFLOW_RUNS=20
REMORA_WORKFLOW_CONCURRENCY=8
REMORA_WORKFLOW_MIN_SUCCESS=0.8

# Cairn Stress Test
REMORA_CAIRN_STRESS_AGENTS=200
```

### Running Integration Tests

```bash
# Run all integration tests
pytest tests/integration/ -m integration -v

# Run only Cairn tests
pytest tests/integration/cairn/ -m cairn -v

# Run with custom vLLM server
REMORA_TEST_VLLM_BASE_URL=http://localhost:8000/v1 \
pytest tests/integration/ -m integration -v
```

---

## Appendix B: Test File Quick Reference

```
tests/integration/
├── helpers.py                    # Fixtures and utilities
├── agent_fixtures/
│   └── sample_function.py        # Sample code for testing
├── test_smoke_real.py            # Basic smoke tests
├── test_executor_real.py         # End-to-end executor
├── test_agent_workflow_real.py   # Concurrent workflow stress
├── test_cli_real.py              # CLI subprocess tests
├── test_error_policy_real.py     # Error policy validation
├── test_checkpoint_roundtrip.py  # Checkpoint serialization
├── test_dashboard_real.py        # Dashboard API tests
└── cairn/
    ├── conftest.py               # Cairn-specific fixtures
    ├── test_write_semantics.py   # CoW write isolation
    ├── test_read_semantics.py    # Read fall-through
    ├── test_agent_isolation.py   # Agent-to-agent isolation
    ├── test_workspace_isolation.py # Stable protection
    ├── test_lifecycle.py         # Open/close/cleanup
    ├── test_concurrent_safety.py # Concurrency stress
    ├── test_error_recovery.py    # Error handling
    ├── test_path_resolution.py   # Path normalization
    ├── test_kv_operations.py     # Submission KV store
    └── test_merge_operations.py  # Merge (unsupported)
```
