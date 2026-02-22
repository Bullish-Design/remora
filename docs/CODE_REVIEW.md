# Remora Code Review

## Executive Summary

Remora is a local orchestration layer for running structured, tool-calling code agents on Python projects. It combines tree-sitter code discovery, multi-turn LLM agent loops, sandboxed tool execution, and isolated workspace management into a cohesive pipeline for automated code analysis and enhancement.

**Overall Assessment**: Remora demonstrates solid architectural thinking and clean separation of concerns. The codebase is well-structured with clear module boundaries. However, there are concerns around complexity management, error handling consistency, incomplete features, and testing depth that should be addressed before production use.

**Rating**: 3.5/5 - Good foundation with room for improvement

---

## Part 1: Library Overview

### What is Remora?

Remora is a CLI tool and Python library that:

1. **Discovers** code nodes (files, classes, functions, methods) using tree-sitter CST parsing
2. **Orchestrates** specialized AI agents to run operations (lint, test, docstring, sample_data) against each node
3. **Executes** tools in isolated Cairn workspaces via Grail sandboxed scripts
4. **Manages** results with manual or automatic acceptance of changes

### The Tech Stack

Remora sits atop four custom libraries (in `.context/`):

| Library | Purpose |
|---------|---------|
| **structured-agents** | Agent kernel with multi-turn tool calling, grammar-constrained decoding |
| **grail** | `.pym` script execution via Monty (Rust-based Python interpreter) |
| **cairn** | Workspace/sandbox management with overlay filesystems |
| **fsdantic** | SQLite-backed virtual filesystem for workspaces |

The inference backend is an OpenAI-compatible server (currently specifically designed for vLLM) running FunctionGemma adapters.

### Core Data Flow

```
remora analyze src/
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 1. Discovery (tree-sitter)                                  │
│    Parse Python files → Extract CSTNode list                │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Orchestration (Coordinator)                              │
│    For each node × operation:                               │
│      - Create workspace                                     │
│      - Load bundle                                          │
│      - Run KernelRunner                                     │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Agent Execution (structured-agents)                      │
│    Multi-turn loop:                                         │
│      - LLM generates tool call                              │
│      - Tool executes in Grail sandbox                       │
│      - Result added to context                              │
│      - Repeat until submit_result or max_turns              │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Results + Review                                         │
│    - Aggregate NodeResults                                  │
│    - Display table/json                                     │
│    - Accept/reject workspace changes                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Part 2: How to Use Remora

### Installation

```bash
# Clone the repository
git clone https://github.com/Bullish-Design/remora.git
cd remora

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Prerequisites

1. **vLLM Server**: Remora requires an OpenAI-compatible inference server running FunctionGemma:
   ```bash
   # See server/README.md for Docker setup
   docker-compose -f server/docker-compose.yml up
   ```

2. **Configuration**: Create `remora.yaml` in your project root:
   ```yaml
   server:
     base_url: http://localhost:8000/v1
     default_adapter: google/functiongemma-270m-it

   operations:
     lint:
       enabled: true
       subagent: lint
     docstring:
       enabled: true
       subagent: docstring
     test:
       enabled: false  # Disable if not needed
   ```

### Basic Usage

**Analyze code**:
```bash
# Analyze current directory
remora analyze .

# Analyze specific path with operations
remora analyze src/mymodule.py --operations lint,docstring

# Output as JSON
remora analyze . --format json

# Auto-accept all successful changes
remora analyze . --auto-accept
```

**Watch mode** (continuous analysis):
```bash
remora watch src/ --operations lint --debounce 1000
```

**Inspect configuration**:
```bash
remora config --format yaml
remora list-agents
```

### Programmatic API

```python
import asyncio
from pathlib import Path
from remora.analyzer import RemoraAnalyzer
from remora.config import load_config

async def main():
    config = load_config()
    analyzer = RemoraAnalyzer(config)

    results = await analyzer.analyze(
        paths=[Path("src/")],
        operations=["lint", "docstring"]
    )

    print(f"Analyzed {results.total_nodes} nodes")
    print(f"Success: {results.successful_operations}")
    print(f"Failed: {results.failed_operations}")

    # Accept all successful changes
    await analyzer.bulk_accept()

asyncio.run(main())
```

### Agent Bundle Structure

Each operation is defined as a bundle in `agents/<op>/`:

```
agents/lint/
├── bundle.yaml       # Agent manifest
├── tools/            # Grail .pym scripts
│   ├── run_linter.pym
│   ├── apply_fix.pym
│   └── submit_result.pym
└── context/          # Optional context providers
    └── ruff_config.pym
```

**bundle.yaml** defines:
- Model adapter and grammar settings
- System/user prompt templates
- Tool catalog with descriptions
- Termination tool (typically `submit_result`)

---

## Part 3: Code Review

### Strengths

#### 1. Clean Architecture with Clear Boundaries

The codebase demonstrates excellent separation of concerns:

- **Discovery** is isolated in `remora/discovery/` with pure tree-sitter logic
- **Orchestration** handles coordination without knowing tool internals
- **Kernel execution** wraps structured-agents cleanly
- **Event emission** is protocol-based and pluggable

This modularity enables testing each layer independently.

#### 2. Strong Typing with Pydantic

Configuration and data models use Pydantic throughout:

```python
# config.py
class RemoraConfig(BaseModel):
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    operations: dict[str, OperationConfig] = Field(default_factory=_default_operations)
```

This provides runtime validation, serialization, and excellent IDE support.

#### 3. Comprehensive Event System

The event bridge (`event_bridge.py`) translates structured-agents events to Remora's format, enabling:

- JSONL event streams for dashboards
- Human-readable conversation logs
- Context manager updates for prompt injection

The composite emitter pattern allows multiple outputs without coupling.

#### 4. Well-Designed Context Management

The Decision Packet system (`context/manager.py`) provides intelligent context compression:

```python
class ContextManager:
    MAX_RECENT_ACTIONS = 10

    def apply_event(self, event: dict[str, Any]) -> None:
        # Routes events to appropriate handlers
        # Maintains bounded recent_actions list
        # Tracks knowledge_delta from tools
```

This prevents prompt bloat while preserving recent context.

#### 5. Graceful Shutdown Handling

Signal handling in `orchestrator.py` is well-implemented:

```python
def _setup_signal_handlers(self) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, self._request_shutdown)
        except NotImplementedError:
            pass  # Windows fallback
```

Running tasks are tracked and cancelled cleanly on shutdown.

---

### Concerns

#### 1. Inconsistent Error Handling Strategy

**Problem**: Error handling varies between modules without a unified strategy.

**Examples**:

```python
# config.py - Custom exception
class ConfigError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

# tool_registry.py - Different custom exception
class ToolRegistryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        # Same pattern, different class

# kernel_runner.py - Silent exception swallowing
except Exception as exc:
    logger.exception("KernelRunner failed for %s", self.node.node_id)
    return AgentResult(status=AgentStatus.FAILED, ...)
```

The error codes in `errors.py` are defined but not consistently used:

```python
# errors.py
CONFIG_003 = "REMORA-CONFIG-003"
CONFIG_004 = "REMORA-CONFIG-004"
AGENT_001 = "REMORA-AGENT-001"
# Only 3 codes defined, yet many error scenarios exist
```

**Recommendation**: Create a unified error hierarchy with proper error codes covering all failure modes:

```python
class RemoraError(Exception):
    """Base exception for all Remora errors."""
    code: str = "REMORA-UNKNOWN"
    recoverable: bool = False

class ConfigurationError(RemoraError):
    code = "REMORA-CONFIG"

class DiscoveryError(RemoraError):
    code = "REMORA-DISCOVERY"

class ExecutionError(RemoraError):
    code = "REMORA-EXEC"
    recoverable = True  # Can retry
```

---

#### 2. Missing Abstractions for Testability

**Problem**: Several components are hard to test in isolation due to concrete dependencies.

**Example** - `KernelRunner` directly instantiates `GrailBackend`:

```python
# kernel_runner.py
def _build_kernel(self) -> AgentKernel:
    backend_config = GrailBackendConfig(...)
    self._backend = GrailBackend(  # Hard-coded concrete class
        config=backend_config,
        externals_factory=self._create_externals,
    )
```

**Example** - `TreeSitterDiscoverer` creates its own components:

```python
# discoverer.py
def __init__(self, ...):
    self._parser = SourceParser()  # No injection
    self._loader = QueryLoader()   # No injection
    self._extractor = MatchExtractor()  # No injection
```

**Recommendation**: Use dependency injection or factory patterns:

```python
class KernelRunner:
    def __init__(
        self,
        ...,
        backend_factory: Callable[[GrailBackendConfig], GrailBackend] | None = None,
    ):
        self._backend_factory = backend_factory or GrailBackend
```

---

#### 3. Incomplete Feature Implementation

**Problem**: Several features are stubbed or incomplete.

**Interactive mode not implemented**:
```python
# analyzer.py:434
def _display_interactive(self, results: AnalysisResults) -> None:
    """Display results interactively (placeholder)."""
    self.console.print("[yellow]Interactive mode not yet implemented...[/yellow]")
    self._display_table(results)
```

**Diff not implemented in review**:
```python
# analyzer.py:476
elif choice == "d":
    self.console.print("  [dim](Diff not yet implemented)[/dim]")
```

**Hub integration partially complete**:
```python
# context/manager.py:117
except Exception:
    pass  # Silent failure on Hub context pull
```

**Recommendation**: Either complete these features or remove them from the public API. Stub features create confusion and technical debt.

---

#### 4. Configuration Complexity

**Problem**: Configuration has grown complex with many nested options and implicit defaults.

```python
# config.py - 8 config classes, 50+ settings
class RemoraConfig(BaseModel):
    discovery: DiscoveryConfig
    agents_dir: Path
    server: ServerConfig
    operations: dict[str, OperationConfig]
    runner: RunnerConfig
    cairn: CairnConfig
    event_stream: EventStreamConfig
    llm_log: LlmLogConfig
    watch: WatchConfig
```

Many settings interact in non-obvious ways:
- `cairn.home` vs `agents_dir` vs workspace paths
- `runner.max_turns` vs `bundle.max_turns`
- `server.default_adapter` vs `operations.*.model_id` vs `bundle.model.adapter`

**Recommendation**:
1. Document configuration precedence clearly
2. Add validation for conflicting settings
3. Implement a simplified "profiles" system for common configurations

---

#### 5. Tight Coupling to FunctionGemma

**Problem**: The codebase assumes FunctionGemma throughout, limiting flexibility.

**Examples**:
```yaml
# bundle.yaml - hardcoded plugin
model:
  plugin: function_gemma
  adapter: google/functiongemma-270m-it
```

```python
# config.py
default_adapter: str = "google/functiongemma-270m-it"
```

**Recommendation**: The plugin system in structured-agents supports other models. Expose this flexibility in Remora's configuration rather than hardcoding FunctionGemma.

---

#### 6. Synchronous Discovery in Async Context

**Problem**: Discovery is synchronous but called from async code without proper handling.

```python
# analyzer.py
async def analyze(self, paths, operations):
    # ... async setup ...
    self._nodes = discoverer.discover()  # Synchronous call blocking event loop
```

The docstring acknowledges this but doesn't fix it:
```python
# discoverer.py
"""Note:
    Discovery is synchronous; use ``asyncio.to_thread`` if calling from
    an async workflow.
"""
```

**Recommendation**: Either make discovery async or wrap it properly:

```python
async def analyze(self, paths, operations):
    self._nodes = await asyncio.to_thread(discoverer.discover)
```

---

#### 7. Resource Leak Potential in Workspaces

**Problem**: Workspace cleanup depends on proper context manager usage, but error paths may leave orphaned workspaces.

```python
# orchestrator.py
workspace_path = workspace_root / "workspaces" / agent_id
workspace_path.mkdir(parents=True, exist_ok=True)

try:
    runner = KernelRunner(...)
except Exception as exc:
    # Workspace directory was created but may not be cleaned up
    errors.append(...)
```

**Recommendation**: Use a more robust cleanup strategy:

```python
@contextlib.asynccontextmanager
async def managed_workspace(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        if path.exists():
            await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)
```

---

#### 8. Insufficient Test Coverage for Critical Paths

**Problem**: While there are 25+ test files, critical integration paths have gaps.

**Missing coverage**:
- End-to-end workspace merge/discard operations
- Concurrent operation execution and race conditions
- Error recovery and retry behavior
- Hub daemon lifecycle and recovery

**Test anti-patterns observed**:
```python
# test_cli.py - Heavy mocking obscures real behavior
monkeypatch.setattr(cli, "load_config", lambda *_args, **_kwargs: config)
monkeypatch.setattr(cli, "_fetch_models", lambda *_args, **_kwargs: {"demo"})
monkeypatch.setattr(cli, "load_subagent_definition", lambda *_args, **_kwargs: fake_definition)
```

**Recommendation**:
1. Add integration tests with a mock vLLM server
2. Test workspace operations against real filesystem
3. Add property-based tests for parsers and formatters

---

#### 9. Documentation Drift

**Problem**: Documentation doesn't always match implementation.

**Example** - `subagent.py` defines `InitialContext` differently than bundles use it:

```python
# subagent.py
class InitialContext(BaseModel):
    system_prompt: str
    node_context: str  # Expected field
```

But bundle.yaml uses:
```yaml
initial_context:
  system_prompt: '...'
  user_template: '...'  # Different field name!
```

This is because `subagent.py` appears to be a deprecated/parallel implementation alongside `structured-agents/bundles/`.

**Recommendation**: Remove or consolidate duplicate implementations. Ensure documentation matches code.

---

#### 10. Magic Strings and Constants

**Problem**: Many magic strings are scattered throughout:

```python
# Various files
"submit_result"  # Termination tool name
".remora"        # Config directory
"hub.db"         # Database filename
"lint,test,docstring"  # Default operations
```

**Recommendation**: Centralize constants:

```python
# constants.py
TERMINATION_TOOL = "submit_result"
CONFIG_DIR = ".remora"
HUB_DB_NAME = "hub.db"
DEFAULT_OPERATIONS = ["lint", "test", "docstring"]
```

---

### Security Considerations

#### Positive

1. **Sandboxed execution**: Grail tools run in Monty's sandboxed interpreter
2. **Path validation**: `externals.py` validates paths to prevent traversal
3. **Resource limits**: CPU, memory, and time limits are enforced

#### Concerns

None, The combination of Grail and Cairn/FSdantic provide excellent security for the use case. 

---

### Performance Observations

#### Positive

1. **Concurrent execution**: Semaphore-based concurrency control allows parallel agent runs
2. **Workspace caching**: LRU cache prevents repeated workspace creation overhead
3. **Debounced watch mode**: Prevents thrashing on rapid file changes

#### Concerns

1. **Synchronous discovery**: Blocks event loop during tree-sitter parsing
2. **No streaming results**: All results collected before display
3. **Per-node workspace creation**: Heavy I/O for large codebases

---

### Code Quality Metrics

| Metric | Observation |
|--------|-------------|
| **Type coverage** | Good - Strict mypy config, most code typed |
| **Docstrings** | Mixed - Core classes documented, utilities sparse |
| **Line length** | Good - 120 char limit enforced |
| **Complexity** | Moderate - Some methods exceed 30 lines |
| **Import organization** | Good - Consistent `from __future__ import annotations` |

---

## Part 4: Recommendations

### High Priority

1. **Unify error handling**: Create a proper exception hierarchy with error codes
2. **Fix sync/async mismatch**: Wrap synchronous operations in `to_thread`
3. **Complete or remove stubs**: Interactive mode, diff view, etc.
4. **Add integration tests**: Test real workflows without excessive mocking

### Medium Priority

5. **Refactor for testability**: Add dependency injection for backends
6. **Simplify configuration**: Document precedence, add validation
7. **Centralize constants**: Eliminate magic strings
8. **Improve cleanup**: Use context managers for all resources

### Low Priority

9. **Model flexibility**: Allow non-FunctionGemma models
10. **Documentation sync**: Ensure docs match implementation
11. **Performance profiling**: Identify bottlenecks in large codebases

---

## Part 5: Conclusion

Remora is an ambitious project that successfully integrates multiple complex subsystems (tree-sitter, LLM agents, sandboxed execution, workspace management) into a coherent tool. The architecture is sound and the code quality is generally good.

The main risks are:
- **Complexity**: Many moving parts increase the surface area for bugs
- **Incomplete features**: Stub implementations may confuse users
- **Testing gaps**: Critical paths lack integration test coverage

For production use, I recommend:
1. Completing the error handling unification
2. Adding integration tests for workspace operations
3. Resolving the sync/async mismatch in discovery

The underlying libraries (structured-agents, grail, cairn) are well-designed and provide a solid foundation. With the recommended improvements, Remora could become a powerful tool for automated code analysis and enhancement.

---

*Review conducted: 2026-02-21*
*Remora version: 0.1.0*
*Reviewer: Code Review Agent*
