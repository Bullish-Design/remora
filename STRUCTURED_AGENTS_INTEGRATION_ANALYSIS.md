# Structured-Agents Integration Analysis

This document analyzes how well the `structured-agents` library meets Remora's requirements and what it will take to complete the integration refactor.

---

## Executive Summary

**Overall Assessment: 85% Coverage**

The `structured-agents` library successfully provides the core functionality Remora needs:
- Agent loop orchestration with turn-based execution
- Grammar-constrained generation via XGrammar
- Process-isolated .pym script execution via GrailBackend
- Plugin-based model support (FunctionGemma ready, extensible to others)
- Observable event system for monitoring
- Bundle configuration system

**What's Missing/Different**:
- No SnapshotManager (pause/resume) - *Decision: Drop for now*
- No API retry logic - *Decision: Rely on infrastructure*
- ContextManager/DecisionPacket stays in Remora (Two-Track Memory)
- Event type translation needed (RemoraEventBridge)
- Dynamic system prompt injection needs wrapper logic

---

## Part 1: Feature Coverage Analysis

### 1.1 Core Agent Loop

| Feature | Remora (runner.py) | structured-agents | Status |
|---------|-------------------|-------------------|--------|
| Turn-based execution | `while turn_count < max_turns` | `kernel.run()` with `max_turns` | **Full coverage** |
| Model API calls | AsyncOpenAI client | `OpenAICompatibleClient` | **Full coverage** |
| Tool call parsing | FunctionGemma regex | `FunctionGemmaPlugin.parse_response()` | **Full coverage** |
| Tool dispatch | `_dispatch_tool()` → GrailExecutor | `ToolSource.execute()` → `GrailBackend` | **Full coverage** |
| Message history | `self.messages` list | `kernel.history_strategy` | **Full coverage** |
| History trimming | `_trim_history_if_needed(40)` | `SlidingWindowHistory(50)` | **Full coverage** |
| Termination detection | `submit_result` tool check | `termination` callback | **Full coverage** |

### 1.2 Grammar Enforcement (Structured Generation)

| Feature | Remora (grammar.py) | structured-agents | Status |
|---------|-------------------|-------------------|--------|
| EBNF grammar building | `build_functiongemma_grammar()` | `FunctionGemmaGrammarBuilder` | **Full coverage** |
| vLLM structured_outputs | `extra_body["structured_outputs"]` | `plugin.to_extra_body()` | **Full coverage** |
| Tool name alternatives | String escaping, `\|` alternation | Same pattern | **Full coverage** |
| Permissive arg parsing | `[^}]*` for arg body | Configurable `args_format` | **Enhanced** |
| JSON Schema mode | Not present | `FunctionGemmaSchemaGrammarBuilder` | **Enhanced** |
| Structural tag mode | Not present | Supported via config | **Enhanced** |

**Assessment**: structured-agents provides *better* grammar support with multiple modes (EBNF, structural_tag, json_schema) and configurable argument formats.

### 1.3 Tool Execution (Grail Backend)

| Feature | Remora (execution.py) | structured-agents | Status |
|---------|----------------------|-------------------|--------|
| ProcessPoolExecutor | `max_workers` configurable | `GrailBackendConfig.max_workers` | **Full coverage** |
| Timeout handling | `asyncio.wait_for()` | `asyncio.wait_for()` | **Full coverage** |
| Grail limits (memory, duration) | Via `grail_limits` dict | Via `GrailBackendConfig.limits` | **Full coverage** |
| Context providers | Pre-tool script execution | `tool_schema.context_providers` | **Full coverage** |
| External functions | `create_remora_externals()` | `externals_factory` callback | **Full coverage** |
| Error handling | Structured error dicts | `ToolResult(is_error=True)` | **Full coverage** |
| SnapshotManager | pause/resume support | **Not present** | **Dropped** |

**Assessment**: Full coverage except SnapshotManager, which is intentionally dropped.

### 1.4 Concurrency Model

| Feature | Remora | structured-agents | Status |
|---------|--------|-------------------|--------|
| Multi-agent concurrency | `asyncio.Semaphore(max_concurrent_agents)` | Caller's responsibility | **Remora keeps** |
| Per-turn tool concurrency | Sequential only | `ToolExecutionStrategy` (concurrent/sequential) | **Enhanced** |
| ProcessPool parallelism | `pool_workers` | `max_workers` | **Full coverage** |
| vLLM continuous batching | Natural via async calls | Same approach | **Full coverage** |

**Assessment**: structured-agents adds per-turn tool concurrency. Multi-agent orchestration stays in Remora's Coordinator.

### 1.5 Event System

| Remora Event | structured-agents Event | Translation |
|--------------|------------------------|-------------|
| `MODEL_REQUEST` | `ModelRequestEvent` | Direct mapping |
| `MODEL_RESPONSE` | `ModelResponseEvent` | Direct mapping |
| `TOOL_CALL` | `ToolCallEvent` | Direct mapping |
| `TOOL_RESULT` | `ToolResultEvent` | Direct mapping |
| `SUBMIT_RESULT` | Detected via termination callback | Bridge logic |
| `AGENT_START` | `KernelStartEvent` | Direct mapping |
| `AGENT_COMPLETE` | `KernelEndEvent` | Direct mapping |
| `AGENT_ERROR` | `Observer.on_error()` | Direct mapping |
| `TURN_COMPLETE` | `TurnCompleteEvent` | Direct mapping |
| `GRAIL_CHECK` | Not present | Remora pre-run check |
| `DISCOVERY` | Not present | Remora orchestrator |
| `WORKSPACE_*` | Not present | Remora orchestrator |

**Assessment**: Core events map directly. Some Remora-specific events (discovery, workspace) remain in orchestrator.

### 1.6 Plugin System

| Capability | FunctionGemmaPlugin | Notes |
|------------|---------------------|-------|
| Message formatting | OpenAI format | Compatible |
| Tool formatting | OpenAI function format | Compatible |
| Response parsing | Regex-based extraction | Same as Remora |
| Grammar building | EBNF/structural_tag/json_schema | Enhanced |
| `supports_ebnf` | `True` | |
| `supports_structural_tags` | `True` | |
| `supports_json_schema` | `True` | |

**Assessment**: FunctionGemmaPlugin is production-ready and matches Remora's current approach.

### 1.7 Bundle System

| Remora Subagent YAML | structured-agents bundle.yaml | Migration |
|---------------------|-------------------------------|-----------|
| `name` | `name` | Direct |
| `max_turns` | `max_turns` | Direct |
| `initial_context.system_prompt` | `initial_context.system_prompt` | Direct |
| `initial_context.node_context` | `initial_context.user_template` | Template syntax compatible |
| `tools[].tool_name` | `tools[].name` | Rename |
| `tools[].pym` | `tools[].script` (via registry) | Path resolution change |
| `tools[].tool_description` | `tools[].description` | Rename |
| `tools[].inputs_override` | `tools[].inputs_override` | Direct |
| `tools[].context_providers` | `tools[].context_providers` | Direct |
| N/A | `model.plugin` | New: defaults to "function_gemma" |
| N/A | `model.grammar` | New: grammar config |
| N/A | `termination_tool` | New: explicit termination |
| N/A | `registries` | New: registry config |

**Assessment**: Migration is straightforward with minor field renames and additions.

---

## Part 2: Functionality Not in structured-agents (Stays in Remora)

### 2.1 ContextManager / DecisionPacket (Two-Track Memory)

**Location**: `src/remora/context/manager.py`, `src/remora/context/models.py`

**What it does**:
- Maintains a `DecisionPacket` with goal, recent actions, working knowledge, error state
- Projects tool results onto the packet state
- Provides formatted context for dynamic system prompt injection
- Integrates with HubClient for external context (Phase 2)

**Integration approach**:
- `KernelRunner` creates ContextManager during initialization
- `RemoraEventBridge.on_tool_result()` calls `context_manager.apply_event()`
- `KernelRunner._provide_context()` calls `context_manager.get_prompt_context()`
- No changes needed to structured-agents

### 2.2 Dynamic System Prompt Injection

**Current behavior** (runner.py lines 170-213):
```python
def _build_system_prompt(self, prompt_context):
    # Injects: ## Current State, ## Recent Actions, ## Working Knowledge, ## Hub Context
```

**Integration approach**:
- Bundle's `initial_context.system_prompt` is the base
- `KernelRunner` provides a `context_provider` callback to `kernel.run()`
- Context provider returns dynamic context for tool execution
- System prompt injection can be done via bundle templates OR a custom message formatter

**Option A (Templates)**:
```yaml
initial_context:
  system_prompt: |
    You are a documentation agent.
    {% if prompt_context %}
    ## Current State
    Turn: {{ prompt_context.turn }}
    {% endif %}
```

**Option B (Custom Formatter)**:
- Create `RemoraMessageFormatter` that extends `FunctionGemmaMessageFormatter`
- Override `format_messages()` to inject context into system prompt
- Use ComposedModelPlugin with custom formatter

**Recommendation**: Option A (Templates) is simpler and keeps logic in configuration.

### 2.3 CST Node Discovery

**Location**: `src/remora/discovery/`

**Status**: Unchanged. Discovery happens before agent execution and feeds into `KernelRunner`.

### 2.4 Orchestrator (Multi-Agent Coordination)

**Location**: `src/remora/orchestrator.py`

**What it does**:
- Coordinates multiple operations per node
- Manages semaphore for concurrent agent execution
- Handles workspace lifecycle (create, cache, cleanup)
- Aggregates results into `NodeResult`

**Integration approach**:
- Replace `FunctionGemmaRunner` with `KernelRunner`
- Keep all orchestration logic unchanged
- Remove references to deleted modules (ProcessIsolatedExecutor, SnapshotManager)

### 2.5 Remora-Specific Grail Externals

**Location**: `src/remora/externals.py`

**What it does**:
```python
def create_remora_externals(...):
    base_externals = create_external_functions(agent_id, agent_fs, stable_fs)
    base_externals["get_node_source"] = get_node_source
    base_externals["get_node_metadata"] = get_node_metadata
    return base_externals
```

**Integration approach**:
- Pass `create_remora_externals` as `externals_factory` to `GrailBackend`
- No changes needed to structured-agents

### 2.6 Result Types

**Location**: `src/remora/results.py`

**Types**: `AgentResult`, `NodeResult`, `AnalysisResults`

**Integration approach**:
- `KernelRunner._format_result()` converts structured-agents `RunResult` → `AgentResult`
- Keep Remora's result types for orchestrator compatibility

---

## Part 3: Files to Delete

Based on analysis, these files can be safely deleted:

| File | Lines | Reason |
|------|-------|--------|
| `src/remora/runner.py` | 953 | Replaced by structured-agents kernel + KernelRunner |
| `src/remora/grammar.py` | 42 | Replaced by FunctionGemmaGrammarBuilder |
| `src/remora/tool_parser.py` | 45 | Replaced by FunctionGemmaResponseParser |
| `src/remora/execution.py` | 424 | Replaced by GrailBackend (minus SnapshotManager) |

**Total removed**: ~1,464 lines

---

## Part 4: Files to Create

### 4.1 `src/remora/kernel_runner.py` (~200 lines)

Wrapper around structured-agents that:
- Loads bundle from path
- Creates ContextManager
- Creates RemoraEventBridge
- Provides externals_factory for GrailBackend
- Implements `_provide_context()` for per-turn context
- Converts `RunResult` → `AgentResult`

### 4.2 `src/remora/event_bridge.py` (~150 lines)

Translates structured-agents events to Remora's EventEmitter:
- Implements Observer protocol
- Converts event types (KernelStartEvent → AGENT_START, etc.)
- Updates ContextManager on tool results
- Emits to Remora's EventEmitter

---

## Part 5: Files to Modify

### 5.1 `src/remora/orchestrator.py`

Changes:
- Remove: `from remora.runner import FunctionGemmaRunner, AgentError`
- Remove: `from remora.execution import ProcessIsolatedExecutor, SnapshotManager`
- Add: `from remora.kernel_runner import KernelRunner`
- Replace FunctionGemmaRunner instantiation with KernelRunner
- Remove snapshot_manager references
- Keep semaphore, workspace management, result aggregation

### 5.2 `src/remora/config.py`

Changes:
- Simplify `RunnerConfig` (remove runner-specific fields now in bundle)
- Add `agents_dir` field pointing to bundle directories
- Remove `use_grammar_enforcement` (now in bundle)

### 5.3 `src/remora/events.py`

Changes:
- Keep event names and emitter classes
- Simplify (heavy lifting now in RemoraEventBridge)

### 5.4 `pyproject.toml`

Changes:
- Add `structured-agents` dependency
- During development: `structured-agents = { path = "../structured-agents" }`

---

## Part 6: Migration Path for Bundles

### 6.1 Current Format (docstring_subagent.yaml)
```yaml
name: docstring_agent
max_turns: 15

initial_context:
  system_prompt: |
    You are a model that can do function calling...
  node_context: |
    Code to document:
    {{ node_text }}

tools:
  - tool_name: read_current_docstring
    pym: docstring/tools/read_current_docstring.pym
    tool_description: Read the existing docstring...
  - tool_name: write_docstring
    pym: docstring/tools/write_docstring.pym
    tool_description: Write or replace a docstring.
    inputs_override:
      docstring:
        description: "The docstring text to write."
    context_providers:
      - docstring/context/docstring_style.pym
```

### 6.2 New Format (bundle.yaml)
```yaml
name: docstring_agent
version: "1.0"

model:
  plugin: function_gemma
  grammar:
    mode: ebnf
    args_format: permissive

initial_context:
  system_prompt: |
    You are a model that can do function calling...
  user_template: |
    Code to document:
    {{ node_text }}

max_turns: 15
termination_tool: submit_result

tools:
  - name: read_current_docstring
    registry: grail
    description: Read the existing docstring...
  - name: write_docstring
    registry: grail
    description: Write or replace a docstring.
    inputs_override:
      docstring:
        description: "The docstring text to write."
    context_providers:
      - context/docstring_style.pym

registries:
  - type: grail
    config:
      agents_dir: tools
```

### 6.3 Migration Script

Create `scripts/migrate_bundles.py` that:
1. Reads old `*_subagent.yaml` files
2. Converts to new `bundle.yaml` format
3. Resolves relative paths
4. Backs up old files

---

## Part 7: Integration Risks & Mitigations

### 7.1 Risk: Event Timing Differences

**Issue**: structured-agents events may fire at slightly different points than current runner.

**Mitigation**: RemoraEventBridge can buffer/transform events as needed. Test with existing event consumers.

### 7.2 Risk: GrailBackend Process Pool Management

**Issue**: structured-agents GrailBackend creates its own ProcessPoolExecutor. Remora currently shares one executor across all agents.

**Mitigation**:
- Option A: Let each KernelRunner have its own backend (simpler but more pools)
- Option B: Create a shared GrailBackend in Coordinator, pass to all KernelRunners
- **Recommendation**: Option B for resource efficiency

### 7.3 Risk: Context Injection Timing

**Issue**: Current runner updates system prompt on every turn. structured-agents uses initial messages.

**Mitigation**:
- Use `context_provider` callback for per-turn context
- OR use custom MessageFormatter that re-injects context
- Test to ensure ContextManager updates propagate correctly

### 7.4 Risk: Tool Schema Differences

**Issue**: Remora filters out system-injected inputs before sending to model. structured-agents may not.

**Mitigation**:
- Bundle schema can specify which inputs are system-injected
- OR KernelRunner filters schemas before passing to kernel
- **Recommendation**: Handle in KernelRunner for backwards compatibility

---

## Part 8: Testing Strategy

### 8.1 Unit Tests

| Component | Test Focus |
|-----------|------------|
| `RemoraEventBridge` | Event translation accuracy |
| `KernelRunner._format_result()` | RunResult → AgentResult conversion |
| Bundle migration | YAML schema compatibility |

### 8.2 Integration Tests

| Test | What it validates |
|------|-------------------|
| Single agent run | Full loop: messages → model → tools → result |
| Multi-agent orchestration | Semaphore, workspace, concurrent execution |
| Event streaming | Events arrive in correct order with correct data |
| Context injection | ContextManager updates reach system prompt |

### 8.3 End-to-End Tests

```bash
# Analyze a simple file with docstring operation
uv run remora analyze tests/fixtures/sample.py --operations docstring

# Verify events are emitted correctly
uv run remora analyze tests/fixtures/sample.py --operations docstring 2>&1 | grep -E "agent_start|agent_complete"
```

---

## Part 9: Implementation Checklist

### Phase 1: Dependencies & Setup
- [ ] Add structured-agents to pyproject.toml
- [ ] Verify import: `from structured_agents import AgentKernel`
- [ ] Ensure Grail + XGrammar dependencies resolve

### Phase 2: Create Bridge Components
- [ ] Create `src/remora/event_bridge.py`
- [ ] Create `src/remora/kernel_runner.py`
- [ ] Write unit tests for both

### Phase 3: Update Orchestrator
- [ ] Modify `orchestrator.py` to use KernelRunner
- [ ] Remove references to deleted modules
- [ ] Update imports

### Phase 4: Delete Old Code
- [ ] Delete `runner.py`
- [ ] Delete `grammar.py`
- [ ] Delete `tool_parser.py`
- [ ] Delete `execution.py`
- [ ] Clean up any remaining imports

### Phase 5: Migrate Bundles
- [ ] Create migration script
- [ ] Run migration on all existing subagent YAMLs
- [ ] Update config to point to bundle directories

### Phase 6: Update Config
- [ ] Simplify RunnerConfig
- [ ] Update operation configs to use bundle paths
- [ ] Remove obsolete config fields

### Phase 7: Testing
- [ ] Run existing test suite
- [ ] Add new integration tests
- [ ] Manual end-to-end verification

### Phase 8: Cleanup
- [ ] Update __init__.py exports
- [ ] Update any documentation
- [ ] Remove test files for deleted modules

---

## Conclusion

The structured-agents library is **well-suited** for Remora's needs. Key benefits:

1. **Cleaner architecture**: Clear separation between kernel (execution) and Remora (orchestration)
2. **Enhanced grammar support**: Multiple modes, configurable args format
3. **Better tool concurrency**: Per-turn concurrent execution
4. **Extensible plugin system**: Easy to add new model types
5. **Typed interfaces**: Protocols for all extension points

The refactor removes ~1,464 lines of code and adds ~350 lines of thin wrapper code, resulting in a net reduction of ~1,100 lines while gaining:
- Better grammar modes
- Concurrent tool execution
- Cleaner module boundaries
- Shared infrastructure with other projects using structured-agents

**Estimated effort**: 2-3 focused implementation sessions following the checklist above.
