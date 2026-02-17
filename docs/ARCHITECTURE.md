# Remora Architecture

## System Overview

Remora is a code analysis and enhancement system that combines **Pydantree** (CST node extraction) with **Cairn** (sandboxed agent orchestration) to automatically analyze and enhance Python code at the node level.

### Core Principles

1. **Node-Level Isolation**: Each CST node (file, class, function) is processed independently
2. **One Coordinator Per Node**: Each node gets its own coordinator agent instance
3. **Workspace Isolation**: All agent operations happen in isolated Cairn workspaces
4. **User Confirmation Required**: Changes must be explicitly accepted by users before merging to stable workspace
5. **Fail-Safe Processing**: Agent failures are logged but don't halt overall processing

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│  Application Layer                                           │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ CLI         │  │ Config Mgr   │  │ File Watcher     │   │
│  │ (Typer)     │  │ (Pydantic)   │  │ (watchfiles)     │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Orchestration Layer                                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │ Node Discovery  │  │ Cairn Interface │  │ Result      │ │
│  │ (Pydantree)     │  │                 │  │ Presenter   │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Execution Layer (Cairn)                                     │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ coordinator.pym (per node)                              ││
│  │  ├─→ lint_agent.pym                                     ││
│  │  ├─→ test_generator_agent.pym                           ││
│  │  ├─→ docstring_agent.pym                                ││
│  │  └─→ sample_data_agent.pym                              ││
│  └─────────────────────────────────────────────────────────┘│
│  Copy-on-Write Workspaces (per agent)                       │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Application Layer

#### CLI Interface (`remora.cli`)
- Built with **Typer** for command-line parsing
- Commands: `analyze`, `watch`, `config`, `list-agents`
- Rich terminal output via **Rich** library
- Handles user input and displays results

**Key Responsibilities:**
- Parse command-line arguments
- Load and merge configuration (file + CLI overrides)
- Invoke orchestration layer
- Present results to user
- Handle interactive review workflow

#### Configuration Manager (`remora.config`)
- Built with **Pydantic** for validation
- Loads `remora.yaml` from project root or specified path
- Merges CLI flags (CLI takes precedence)
- Validates operation settings, queries, and Cairn parameters

**Configuration Schema:**
```python
class RemoraConfig(BaseModel):
    root_dirs: list[Path]
    queries: list[str]  # Query names: function_def, class_def, file
    operations: dict[str, OperationConfig]
    context_scope: Literal["node"] = "node"  # MVP only supports "node"
    cairn: CairnConfig
```

#### File Watcher (`remora.watcher`)
- Uses **watchfiles** for reactive file monitoring
- Debounces file changes to avoid duplicate processing
- Triggers node discovery and analysis on file modifications
- Optional component (watch mode only)

### 2. Orchestration Layer

#### Node Discovery Engine (`remora.discovery`)

**Purpose:** Extract CST nodes from Python source files using Pydantree

**Components:**
- `NodeDiscoverer`: Main class for discovering nodes
- Query loader: Loads `.scm` Tree-sitter query files
- Node extractor: Runs queries and extracts node metadata

**Query Files (bundled):**
```
remora/queries/
├── function_def.scm    # Captures function definitions
├── class_def.scm       # Captures class definitions
└── file.scm            # Captures file-level structure
```

**Node Discovery Flow:**
```python
# 1. Load queries
queries = load_queries(["function_def", "class_def", "file"])

# 2. Discover nodes in source files
nodes = await discoverer.discover(
    root_dirs=["src/", "lib/"],
    queries=queries
)

# 3. Returns list of CSTNode objects
# Each CSTNode contains:
#   - node_id: str (unique identifier)
#   - node_type: Literal["file", "class", "function"]
#   - name: str
#   - file_path: Path
#   - start_byte: int
#   - end_byte: int
#   - text: str (node source code)
```

**Data Model:**
```python
class CSTNode(BaseModel):
    node_id: str  # hash of file_path + node_type + name
    node_type: Literal["file", "class", "function"]
    name: str
    file_path: Path
    start_byte: int
    end_byte: int
    text: str

    @property
    def context(self) -> str:
        """For MVP: returns self.text"""
        return self.text
```

#### Cairn Interface (`remora.orchestrator`)

**Purpose:** Interface between Remora and Cairn for agent orchestration

**Key Responsibilities:**
- Spawn coordinator agents (one per node)
- Manage agent lifecycle
- Collect agent results
- Handle workspace operations

**Coordinator Spawning Flow:**
```python
# For each discovered node, spawn a coordinator
async def process_node(node: CSTNode, operations: list[str]) -> NodeResult:
    # 1. Prepare coordinator inputs
    inputs = {
        "node_id": node.node_id,
        "node_type": node.node_type,
        "node_name": node.name,
        "node_text": node.text,
        "file_path": str(node.file_path),
        "operations": operations,
        "agent_paths": config.agent_paths,
    }

    # 2. Spawn coordinator via Cairn
    coordinator_agent = await cairn.spawn_agent(
        agent_script="coordinator.pym",
        inputs=inputs,
        workspace_id=f"coordinator-{node.node_id}"
    )

    # 3. Wait for completion
    result = await coordinator_agent.wait()

    # 4. Return structured result
    return NodeResult(
        node_id=node.node_id,
        node_name=node.name,
        operations=result.operations,
        workspace_ids=result.workspace_ids,
        errors=result.errors
    )
```

**Concurrency:**
```python
# Process multiple nodes concurrently
results = await asyncio.gather(*[
    process_node(node, operations)
    for node in nodes
])
```

#### Result Presenter (`remora.results`)

**Purpose:** Format and display analysis results to users

**Key Responsibilities:**
- Aggregate results from all nodes
- Format output (table, JSON, or interactive)
- Present workspace changes for review
- Handle accept/reject/retry workflows

**Display Modes:**
- **Table Mode**: Rich table showing node × operation results
- **JSON Mode**: Machine-readable output for programmatic use
- **Interactive Mode**: Step-through review with accept/reject prompts

### 3. Execution Layer (Cairn Agents)

#### Coordinator Agent (`coordinator.pym`)

**Purpose:** Meta-agent that spawns and manages specialized agents for a single node

**Inputs:**
```python
# Defined at top of coordinator.pym
node_id = Input("node_id")           # str
node_type = Input("node_type")       # "file" | "class" | "function"
node_name = Input("node_name")       # str
node_text = Input("node_text")       # str (source code)
file_path = Input("file_path")       # str
operations = Input("operations")     # list[str]
agent_paths = Input("agent_paths")   # dict[str, str]
```

**External Functions:**
```python
@external
async def spawn_specialized_agent(
    agent_type: str,
    inputs: dict
) -> str:
    """Spawn a specialized agent, returns agent_id"""

@external
async def wait_for_agent(agent_id: str) -> dict:
    """Wait for agent completion, returns result"""

@external
async def log_error(message: str, error: dict) -> None:
    """Log errors to orchestration layer"""
```

**Coordinator Logic Flow:**
```python
# 1. Initialize result tracking
results = {}
errors = []
workspace_ids = []

# 2. Spawn specialized agents
agent_ids = []
for op in operations:
    try:
        agent_id = await spawn_specialized_agent(
            agent_type=op,  # "lint", "test", "docstring", "sample_data"
            inputs={
                "node_id": node_id,
                "node_type": node_type,
                "node_name": node_name,
                "node_text": node_text,
                "file_path": file_path,
            }
        )
        agent_ids.append((op, agent_id))
    except Exception as e:
        await log_error(f"Failed to spawn {op} agent", {"error": str(e)})
        errors.append({"operation": op, "phase": "spawn", "error": str(e)})

# 3. Gather results (concurrent wait)
for op, agent_id in agent_ids:
    try:
        result = await wait_for_agent(agent_id)
        results[op] = result
        workspace_ids.append(result["workspace_id"])
    except Exception as e:
        await log_error(f"{op} agent failed", {"error": str(e)})
        errors.append({"operation": op, "phase": "execution", "error": str(e)})

# 4. Submit aggregated results
await submit_result(
    summary=f"Processed {node_name} with {len(results)}/{len(operations)} successful operations",
    results=results,
    workspace_ids=workspace_ids,
    errors=errors
)
```

**Output:**
```python
{
    "node_id": "abc123",
    "node_name": "calculate",
    "operations": {
        "lint": {
            "status": "success",
            "workspace_id": "lint-abc123",
            "changed_files": ["src/utils.py"],
            "summary": "Fixed 3 linting issues"
        },
        "test": {
            "status": "success",
            "workspace_id": "test-abc123",
            "changed_files": ["tests/test_utils.py"],
            "summary": "Generated 5 test cases"
        }
    },
    "workspace_ids": ["lint-abc123", "test-abc123"],
    "errors": []
}
```

#### Specialized Agents

Each specialized agent is a separate `.pym` script with focused responsibility.

##### 1. Lint Agent (`lint_agent.pym`)

**Purpose:** Run linters and suggest/apply fixes

**Inputs:**
```python
node_id = Input("node_id")
node_type = Input("node_type")
node_name = Input("node_name")
node_text = Input("node_text")
file_path = Input("file_path")
```

**Logic:**
```python
# 1. Write node to sandbox workspace
await write_file(file_path, node_text)

# 2. Run linters (ruff, pylint, etc.)
lint_results = await run_linter("ruff", file_path)

# 3. Apply auto-fixes in sandbox
await apply_fixes(lint_results)

# 4. Submit results
await submit_result(
    summary=f"Fixed {len(lint_results)} issues",
    changed_files=[file_path],
    workspace_id=f"lint-{node_id}"
)
```

##### 2. Test Generator Agent (`test_generator_agent.pym`)

**Purpose:** Generate unit tests for functions/classes

**Logic:**
```python
# 1. Analyze node structure
test_cases = await analyze_and_generate_tests(node_text, node_type)

# 2. Create test file
test_file_path = generate_test_path(file_path)
test_content = format_test_file(test_cases)

# 3. Write to sandbox
await write_file(test_file_path, test_content)

# 4. Submit results
await submit_result(
    summary=f"Generated {len(test_cases)} test cases",
    changed_files=[test_file_path],
    workspace_id=f"test-{node_id}"
)
```

##### 3. Docstring Agent (`docstring_agent.pym`)

**Purpose:** Generate or improve docstrings

**Logic:**
```python
# 1. Extract existing docstring (if any)
existing_docstring = extract_docstring(node_text)

# 2. Generate new/improved docstring
new_docstring = await generate_docstring(
    node_text,
    node_type,
    style="google"  # From config
)

# 3. Inject into source
updated_source = inject_docstring(node_text, new_docstring)

# 4. Write to sandbox
await write_file(file_path, updated_source)

# 5. Submit results
await submit_result(
    summary=f"{'Updated' if existing_docstring else 'Added'} docstring",
    changed_files=[file_path],
    workspace_id=f"docstring-{node_id}"
)
```

##### 4. Sample Data Agent (`sample_data_agent.pym`)

**Purpose:** Generate example data/fixtures

**Logic:**
```python
# 1. Analyze function/class signature
fixtures = await generate_fixtures(node_text, node_type)

# 2. Create fixture file
fixture_path = f"fixtures/{node_name}_fixtures.json"
fixture_content = json.dumps(fixtures, indent=2)

# 3. Write to sandbox
await write_file(fixture_path, fixture_content)

# 4. Submit results
await submit_result(
    summary=f"Generated {len(fixtures)} fixture examples",
    changed_files=[fixture_path],
    workspace_id=f"sample-data-{node_id}"
)
```

## Workspace Management

### Cairn Overlay Pattern

Each agent operates in an isolated copy-on-write workspace:

```
.agentfs/
├── stable.db                              # Original codebase
│
├── coordinator-{node-id}.db               # Coordinator workspace (per node)
│   └── (minimal - coordinator doesn't modify files)
│
└── specialized-{operation}-{node-id}.db   # Specialized agent workspaces
    ├── lint-function-calculate.db         # Linting changes
    ├── test-function-calculate.db         # Generated tests
    ├── docstring-function-calculate.db    # Docstring updates
    └── sample-data-function-calculate.db  # Generated fixtures
```

### Workspace Lifecycle

1. **Creation**: Workspace created when agent spawns
2. **Execution**: Agent modifies files in its workspace
3. **Completion**: Agent submits results, workspace persists
4. **Review**: User reviews changes via workspace diff
5. **Accept/Reject**: User decision triggers workspace merge or discard
6. **Cleanup**: (Post-MVP) Workspaces cleaned up after merge/discard

### Merge Strategy

**Auto-Accept = False (Default):**
```
User reviews → Selects workspace → Cairn merges to stable
```

**Auto-Accept = True:**
```
Agent completes → Changes staged → User confirms → Cairn merges to stable
```

**Note:** Even with `auto_accept: true`, user confirmation is required before merging to stable workspace.

## Data Flow

### End-to-End Flow

```
1. User triggers analysis
   $ remora analyze src/ --operations lint,test,docstring

2. Application layer loads config
   - Load remora.yaml
   - Merge CLI flags (CLI overrides)
   - Validate configuration

3. Orchestration layer discovers nodes
   - Use Pydantree to extract CST nodes
   - Filter by queries (function_def, class_def, file)
   - Returns list[CSTNode]

4. For each node, spawn coordinator (concurrent)
   - Cairn creates coordinator workspace
   - Coordinator.pym receives node data

5. Coordinator spawns specialized agents (concurrent within node)
   - Each specialized agent gets its own workspace
   - Agents process node independently
   - Failures logged, don't halt other agents

6. Agents complete and submit results
   - Results include workspace_id, changed_files, summary
   - Coordinator aggregates results

7. Orchestration layer collects all results
   - Aggregate results from all nodes
   - Format for presentation

8. Application layer presents results
   - Display table/JSON output
   - Show workspace diffs
   - Prompt for accept/reject

9. User reviews and accepts changes
   - Select workspaces to merge
   - Cairn merges to stable workspace
   - Changes applied to source code

10. Workspaces persist for potential re-review
```

## Concurrency Model

### Multi-Level Parallelism

**Level 1: Node-Level Concurrency**
```python
# Multiple nodes processed in parallel
results = await asyncio.gather(*[
    process_node(node, operations)
    for node in nodes
])
```

**Level 2: Operation-Level Concurrency (within coordinator)**
```python
# Within a single node, operations run in parallel
# Coordinator spawns all specialized agents concurrently
for op in operations:
    agent_ids.append(spawn_specialized_agent(op, inputs))

# Wait for all to complete
results = await gather_results(agent_ids)
```

### Concurrency Limits

Configured via `remora.yaml`:
```yaml
cairn:
  max_concurrent_agents: 10  # Total concurrent agents across all nodes
  timeout: 120               # Agent timeout in seconds
```

## Error Handling

### Failure Modes and Recovery

**1. Node Discovery Failure**
- **Cause**: Invalid `.scm` query, syntax error in source file
- **Recovery**: Log error, skip node, continue with other nodes
- **User Impact**: Warning displayed, partial results returned

**2. Coordinator Spawn Failure**
- **Cause**: Cairn unavailable, resource exhaustion
- **Recovery**: Log error, skip node, continue with other nodes
- **User Impact**: Error displayed for affected node

**3. Specialized Agent Spawn Failure**
- **Cause**: Invalid agent path, agent script error
- **Recovery**: Log error in coordinator, continue with other operations
- **User Impact**: Partial results for node (some operations succeed)

**4. Specialized Agent Execution Failure**
- **Cause**: Tool crash (linter error, test generation failure)
- **Recovery**: Log error in coordinator, mark operation as failed
- **User Impact**: Operation marked as failed, other operations proceed

**5. Workspace Merge Failure**
- **Cause**: Merge conflict, file permission error
- **Recovery**: Rollback merge, preserve workspace for manual resolution
- **User Impact**: Error displayed, user can manually resolve

### Error Reporting

**Error Schema:**
```python
class AgentError(BaseModel):
    node_id: str
    operation: str
    phase: Literal["spawn", "execution", "merge"]
    error: str
    traceback: Optional[str]
    timestamp: datetime
```

**Error Display:**
```
✗ src/utils.py::calculate
  ✓ lint: Fixed 3 issues
  ✗ test: Agent execution failed - ImportError: missing module 'pytest'
  ✓ docstring: Added Google-style docstring
```

## Configuration System

### Configuration Precedence

```
1. CLI flags (highest priority)
2. remora.yaml in project root
3. Default values (lowest priority)
```

### Configuration Loading

```python
def load_config(config_path: Optional[Path], cli_overrides: dict) -> RemoraConfig:
    # 1. Load defaults
    config = RemoraConfig.defaults()

    # 2. Load YAML if exists
    if config_path and config_path.exists():
        yaml_config = yaml.safe_load(config_path.read_text())
        config = config.merge(yaml_config)

    # 3. Apply CLI overrides
    config = config.merge(cli_overrides)

    # 4. Validate
    config.validate()

    return config
```

### Agent Path Resolution

```python
class AgentPathResolver:
    def resolve(self, agent_name: str, config: RemoraConfig) -> Path:
        # 1. Check config for custom path
        if agent_name in config.agent_paths:
            return Path(config.agent_paths[agent_name])

        # 2. Fall back to bundled agents
        return BUNDLED_AGENTS_DIR / f"{agent_name}.pym"
```

**MVP Bundled Agents:**
```
remora/agents/
├── coordinator.pym
├── lint_agent.pym
├── test_generator_agent.pym
├── docstring_agent.pym
└── sample_data_agent.pym
```

## Extension Points

### Future Enhancements

**1. Custom Specialized Agents**
- Users can provide custom `.pym` scripts
- Registered via configuration
- Coordinator dynamically spawns based on config

**2. Context Providers (Pluggable)**
```python
class ContextProvider(Protocol):
    async def get_context(self, node: CSTNode) -> str:
        """Return context for node"""

# MVP: NodeOnlyContextProvider
# Future: FileContextProvider, DependencyContextProvider
```

**3. Custom Queries**
- Users can provide custom `.scm` queries
- Loaded from configurable paths
- Enables extraction of custom node types

**4. Result Formatters (Pluggable)**
```python
class ResultFormatter(Protocol):
    def format(self, results: list[NodeResult]) -> str:
        """Format results for display"""

# Implementations: TableFormatter, JSONFormatter, HTMLFormatter
```

**5. Agent Communication (Post-MVP)**
- Shared context between agents
- Example: test agent uses lint results to avoid generating tests for broken code
- Requires coordinator orchestration changes

## Performance Considerations

### Optimization Strategies

**1. Lazy Node Discovery**
- Only discover nodes for requested operations
- Cache query results for watch mode

**2. Result Caching (Future)**
- Cache agent results keyed by (node_id, operation, node_hash)
- Skip re-analysis if node unchanged

**3. Incremental Analysis (Future)**
- Track file changes in watch mode
- Only re-analyze modified nodes

**4. Parallel Agent Spawning**
- Spawn all agents concurrently (within concurrency limits)
- Use asyncio.gather for parallel execution

**5. Workspace Cleanup (Future)**
- Periodic cleanup of old/merged workspaces
- Configurable retention policy

## Technology Stack

| Layer | Component | Technology |
|-------|-----------|------------|
| Application | CLI | Typer |
| Application | Config | Pydantic |
| Application | Terminal UI | Rich |
| Application | File Watching | watchfiles |
| Orchestration | Node Discovery | Pydantree |
| Orchestration | Parsing | Tree-sitter |
| Orchestration | Async Runtime | AsyncIO |
| Execution | Agent Orchestration | Cairn |
| Execution | Workspace Isolation | Cairn Overlays |
| Execution | Agent Scripts | Grail (.pym) |

## Security Considerations

### Sandboxing

- All agent execution isolated in Cairn sandboxes
- Agents cannot access parent filesystem directly
- Workspace operations copy-on-write (no direct modification)

### Input Validation

- All configuration validated via Pydantic
- Source code parsed via Tree-sitter (safe parser)
- Agent inputs sanitized before passing to Cairn

### User Confirmation

- All changes require explicit user acceptance
- No automatic merges to stable workspace (even with auto_accept)
- Clear diff display before merge

---

**Document Version**: 1.0
**Last Updated**: 2026-02-17
**Status**: Initial Draft
