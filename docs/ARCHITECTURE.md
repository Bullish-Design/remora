# Remora Architecture

## System Overview

Remora is a code analysis and enhancement system built around **custom-trained FunctionGemma subagents** — tiny locally-running language models that reason about code in a multi-turn tool calling loop. Each specialized operation (lint, test, docstring, sample_data) is handled by a domain-fine-tuned 270M parameter model that runs entirely on the developer's machine with no network dependency.

The system layers three established components — **Pydantree** for CST node extraction, **Cairn** for sandboxed tool execution, and **llama-cpp-python** for local model inference — under a new orchestration layer that coordinates the FunctionGemma runner loop.

### Core Principles

1. **Local-First Execution**: All inference runs locally via GGUF models; no API keys or data egress
2. **Multi-Turn Reasoning**: Each subagent iterates through tool calls until it decides the task is complete
3. **Node-Level Isolation**: Each CST node is processed independently with its own workspace set
4. **Workspace Sandboxing**: All tool execution happens in isolated Cairn copy-on-write workspaces
5. **Human Authority**: Changes must be explicitly accepted before merging to the stable workspace
6. **Fail-Safe Processing**: Individual agent failures are logged but never halt overall analysis

---

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
│  │ Node Discovery  │  │ Coordinator     │  │ Result      │ │
│  │ (Pydantree)     │  │                 │  │ Presenter   │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  FunctionGemma Runner Layer                                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ FunctionGemmaRunner (one per operation per node)        ││
│  │  - Loads subagent YAML definition                       ││
│  │  - Initializes GGUF model via llama-cpp-python          ││
│  │  - Builds initial context from CSTNode                  ││
│  │  - Runs multi-turn tool calling loop                    ││
│  │  - Dispatches tool calls + context providers            ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Cairn Execution Layer                                       │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Tool .pym scripts execute in Cairn workspace sandboxes  ││
│  │  lint/tools/        test/tools/                         ││
│  │  docstring/tools/   sample_data/tools/                  ││
│  │  context_providers/ (.pym, per-tool)                    ││
│  └─────────────────────────────────────────────────────────┘│
│  Copy-on-Write Workspaces (one per operation per node)       │
└─────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Application Layer

#### CLI Interface (`remora.cli`)

Built with **Typer**; Rich for terminal output. Commands:
- `remora analyze <paths>` — run analysis pipeline on target paths
- `remora watch <paths>` — run in reactive watch mode
- `remora config` — display merged configuration
- `remora list-agents` — list available subagent definitions

#### Configuration Manager (`remora.config`)

Built with **Pydantic**. Loads `remora.yaml`, merges CLI overrides, validates all fields.

```python
class RemoraConfig(BaseModel):
    root_dirs: list[Path]
    queries: list[str]           # function_def, class_def, file
    operations: dict[str, OperationConfig]
    agents_dir: Path             # Root of agents/ directory
    cairn: CairnConfig
    runner: RunnerConfig         # FunctionGemmaRunner settings

class RunnerConfig(BaseModel):
    max_turns: int = 20          # Per-run turn limit
    max_concurrent_runners: int = 4
    timeout: int = 300           # Seconds per runner
```

#### File Watcher (`remora.watcher`)

Uses **watchfiles** for reactive monitoring. Debounces changes, triggers incremental re-analysis on modified files.

---

### 2. Orchestration Layer

#### Node Discovery Engine (`remora.discovery`)

Uses **Pydantree** with `.scm` Tree-sitter query files to extract `CSTNode` objects.

```
remora/queries/
├── function_def.scm
├── class_def.scm
└── file.scm
```

```python
class CSTNode(BaseModel):
    node_id: str        # hash(file_path + node_type + name)
    node_type: Literal["file", "class", "function"]
    name: str
    file_path: Path
    start_byte: int
    end_byte: int
    text: str
```

#### Coordinator (`remora.orchestrator`)

The coordinator is now a thin Python class (not a `.pym` script). It receives a `CSTNode` and the list of operations, then spawns a `FunctionGemmaRunner` for each operation:

```python
async def process_node(node: CSTNode, operations: list[str]) -> NodeResult:
    runners = {}
    for op in operations:
        definition_path = agents_dir / op / f"{op}_subagent.yaml"
        runners[op] = FunctionGemmaRunner(
            definition=load_subagent_def(definition_path),
            node=node,
            workspace_id=f"{op}-{node.node_id}",
            cairn_client=cairn,
        )

    results = await asyncio.gather(*[
        runner.run() for runner in runners.values()
    ], return_exceptions=True)

    return NodeResult(
        node_id=node.node_id,
        operations={op: result for op, result in zip(operations, results)},
    )
```

The coordinator no longer needs to be a Cairn `.pym` script. The `FunctionGemmaRunner` handles the Cairn workspace for its own tool calls.

---

### 3. FunctionGemma Runner Layer

#### FunctionGemmaRunner (`remora.runner`)

The central new component. One instance per (operation, node) pair.

**Initialization:**
```python
@dataclass
class FunctionGemmaRunner:
    definition: SubagentDefinition  # Parsed YAML
    node: CSTNode
    workspace_id: str
    cairn_client: CairnClient

    def __post_init__(self):
        self.model = Llama(
            model_path=str(self.definition.model_path),
            n_ctx=4096,
            n_threads=2,
        )
        self.messages: list[dict] = []
        self.turn_count: int = 0
```

**Multi-Turn Loop:**
```python
async def run(self) -> AgentResult:
    self._build_initial_messages()

    while self.turn_count < self.definition.max_turns:
        response = self.model.create_chat_completion(
            messages=self.messages,
            tools=self.definition.tool_schemas,
            tool_choice="auto",
        )

        choice = response["choices"][0]
        self.messages.append(choice["message"])
        self.turn_count += 1

        if choice["finish_reason"] == "stop":
            # Model produced plain text — task complete
            return self._extract_result()

        if choice["finish_reason"] == "tool_calls":
            tool_calls = choice["message"]["tool_calls"]
            for tc in tool_calls:
                result = await self._dispatch_tool(tc)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result),
                })

                if tc["function"]["name"] == "submit_result":
                    return AgentResult(**result)

    raise RunnerTurnLimitError(self.definition.name, self.turn_count)
```

**Tool Dispatch:**
```python
async def _dispatch_tool(self, tool_call: dict) -> dict:
    tool_name = tool_call["function"]["name"]
    tool_args = json.loads(tool_call["function"]["arguments"])
    tool_def = self.definition.tools[tool_name]

    # 1. Run context providers (inject into messages before dispatching)
    for provider_pym in tool_def.context_providers:
        ctx = await self.cairn_client.run_pym(
            provider_pym, self.workspace_id, inputs={}
        )
        self.messages.append({
            "role": "user",
            "content": f"[Context] {ctx}"
        })

    # 2. Execute the tool's .pym script
    return await self.cairn_client.run_pym(
        tool_def.pym, self.workspace_id, inputs=tool_args
    )
```

---

### 4. Subagent Definition System

#### YAML Definition Format

Every subagent is described by a YAML file at `agents/{name}/{name}_subagent.yaml`:

```yaml
name: lint_agent
model: agents/lint/models/lint_functiongemma_q8.gguf
max_turns: 15

initial_context:
  system_prompt: |
    You are a Python linting specialist. Your job is to analyze the provided
    code for style violations, apply safe auto-fixes, and report any issues
    that require manual attention. Be conservative: only apply fixes that
    are guaranteed to preserve semantics.
  node_context: |
    Code to analyze:
    ```python
    {{ node_text }}
    ```

tools:
  - name: run_linter
    pym: agents/lint/tools/run_linter.pym
    description: >
      Run the configured linter on the current code and return a list of
      issues with their line numbers and codes.
    parameters:
      type: object
      properties:
        check_only:
          type: boolean
          description: "If true, report issues without applying fixes."
      additionalProperties: false
    context_providers:
      - agents/lint/context/ruff_config.pym

  - name: apply_fix
    pym: agents/lint/tools/apply_fix.pym
    description: >
      Apply a fix for a specific lint issue. Only call this for issues the
      linter confirmed are auto-fixable.
    parameters:
      type: object
      properties:
        issue_code: { type: string }
        line_number: { type: integer }
      required: [issue_code, line_number]
      additionalProperties: false

  - name: read_current_file
    pym: agents/lint/tools/read_file.pym
    description: Read the current state of the file being analyzed.
    parameters:
      type: object
      properties: {}
      additionalProperties: false

  - name: submit_result
    pym: agents/lint/tools/submit.pym
    description: >
      Submit the final linting results and end the task.
    parameters:
      type: object
      properties:
        summary: { type: string }
        issues_fixed: { type: integer }
        issues_remaining: { type: integer }
        changed_files:
          type: array
          items: { type: string }
      required: [summary, issues_fixed, issues_remaining, changed_files]
      additionalProperties: false
```

All tool schemas use strict mode (`additionalProperties: false`) to guarantee reliable dispatch to `.pym` scripts.

#### Pydantic Model

```python
class ToolDefinition(BaseModel):
    name: str
    pym: Path
    description: str
    parameters: dict    # JSON Schema
    context_providers: list[Path] = []

class InitialContext(BaseModel):
    system_prompt: str
    node_context: str   # Jinja2 template with {{ node_text }} etc.

class SubagentDefinition(BaseModel):
    name: str
    model: Path
    max_turns: int = 20
    initial_context: InitialContext
    tools: list[ToolDefinition]

    @property
    def tool_schemas(self) -> list[dict]:
        """Build OpenAI-style tool schema list for llama.cpp."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                    "strict": True,
                }
            }
            for t in self.tools
        ]
```

---

### 5. Tool Scripts and Context Providers

#### Tool Layout per Subagent

```
agents/
├── lint/
│   ├── lint_subagent.yaml
│   ├── models/
│   │   └── lint_functiongemma_q8.gguf
│   ├── tools/
│   │   ├── run_linter.pym      # Runs ruff/pylint, returns issue list
│   │   ├── apply_fix.pym       # Applies a single auto-fix
│   │   ├── read_file.pym       # Reads current file state
│   │   └── submit.pym          # Terminal tool, writes result schema
│   └── context/
│       └── ruff_config.pym     # Reads ruff.toml → injects as context
│
├── test/
│   ├── test_subagent.yaml
│   ├── models/
│   │   └── test_functiongemma_q8.gguf
│   ├── tools/
│   │   ├── analyze_signature.pym     # Extracts function signature + type hints
│   │   ├── read_existing_tests.pym   # Reads existing test file if present
│   │   ├── write_test_file.pym       # Writes test cases to test file
│   │   ├── run_tests.pym             # Runs pytest, returns pass/fail
│   │   └── submit.pym
│   └── context/
│       └── pytest_config.pym         # Reads pytest.ini/pyproject.toml
│
├── docstring/
│   ├── docstring_subagent.yaml
│   ├── models/
│   │   └── docstring_functiongemma_q8.gguf
│   ├── tools/
│   │   ├── read_current_docstring.pym  # Reads existing docstring if any
│   │   ├── read_type_hints.pym         # Extracts type annotations
│   │   ├── write_docstring.pym         # Injects docstring into source
│   │   └── submit.pym
│   └── context/
│       └── docstring_style.pym         # Reads project docstring style config
│
└── sample_data/
    ├── sample_data_subagent.yaml
    ├── models/
    │   └── sample_data_functiongemma_q8.gguf
    ├── tools/
    │   ├── analyze_signature.pym       # Extracts function signature
    │   ├── write_fixture_file.pym      # Writes JSON/YAML fixture file
    │   └── submit.pym
    └── context/
        └── existing_fixtures.pym       # Reads any existing fixture files
```

#### Standard Tool Output Contract

Every `.pym` tool returns a JSON-serializable dict. The `submit.pym` tool in each subagent must return:

```python
{
    "status": "success" | "failed" | "skipped",
    "workspace_id": str,
    "changed_files": list[str],
    "summary": str,
    "details": dict,  # Operation-specific payload
    "error": str | None
}
```

All other tools return domain-specific payloads appropriate to their function.

---

### 6. Training Pipeline (`training/`)

The custom FunctionGemma models are produced by a fine-tuning pipeline in `training/`:

```
training/
├── lint/
│   ├── generate_examples.py    # Generates synthetic multi-turn training data
│   ├── examples/               # JSONL output (conversation format)
│   └── fine_tune.py            # Fine-tuning script (Unsloth/PEFT)
├── test/
│   ├── generate_examples.py
│   ├── examples/
│   └── fine_tune.py
├── docstring/
│   └── ...
├── sample_data/
│   └── ...
└── shared/
    ├── base_model.py           # FunctionGemma base model loader
    ├── conversation_schema.py  # Shared training format schemas
    └── gguf_export.py          # Convert fine-tuned model → GGUF
```

**Training Data Format (JSONL):**

Each training example is a full conversation:
```json
{
  "messages": [
    {"role": "system", "content": "You are a Python linting specialist..."},
    {"role": "user", "content": "Code to analyze:\n```python\ndef foo(x):\n    return x+1\n```"},
    {"role": "assistant", "tool_calls": [{"id": "tc1", "function": {"name": "run_linter", "arguments": "{\"check_only\": true}"}}]},
    {"role": "tool", "tool_call_id": "tc1", "content": "{\"issues\": [{\"code\": \"E225\", \"line\": 2}]}"},
    {"role": "assistant", "tool_calls": [{"id": "tc2", "function": {"name": "apply_fix", "arguments": "{\"issue_code\": \"E225\", \"line_number\": 2}"}}]},
    {"role": "tool", "tool_call_id": "tc2", "content": "{\"success\": true}"},
    {"role": "assistant", "tool_calls": [{"id": "tc3", "function": {"name": "submit_result", "arguments": "{\"summary\": \"Fixed 1 spacing issue\", \"issues_fixed\": 1, \"issues_remaining\": 0, \"changed_files\": [\"src/utils.py\"]}"}}]}
  ]
}
```

---

## Workspace Management

### Workspace Layout

```
.agentfs/
├── stable.db                              # Original codebase (read-only during runs)
├── coordinator-{node-id}.db               # Coordinator state (minimal writes)
├── lint-{node-id}.db                      # lint subagent workspace
│   └── (all run_linter.pym + apply_fix.pym writes land here)
├── test-{node-id}.db                      # test subagent workspace
├── docstring-{node-id}.db                 # docstring subagent workspace
└── sample_data-{node-id}.db               # sample_data subagent workspace
```

### Workspace Lifecycle

1. **Creation**: Cairn creates a copy-on-write workspace when the runner starts
2. **Execution**: Each `.pym` tool call in the multi-turn loop writes into the workspace
3. **Completion**: Runner calls `submit_result`; workspace enters REVIEWING state
4. **Review**: User inspects workspace diff
5. **Accept**: Cairn merges workspace into stable
6. **Reject**: Workspace discarded; stable unchanged

---

## Data Flow: End-to-End

```
1. User: remora analyze src/ --operations lint,test,docstring

2. Config loaded and validated (RemoraConfig)

3. Node Discovery:
   Pydantree extracts CSTNode list from src/

4. For each node (concurrent, up to max_concurrent):
   Coordinator spawns FunctionGemmaRunner for each operation

5. FunctionGemmaRunner (one per operation per node):
   a. Load subagent YAML definition
   b. Initialize GGUF model via llama-cpp-python
   c. Build initial messages from system_prompt + node.text
   d. Multi-turn loop:
      - Model produces tool_calls
      - Context providers inject per-tool context if configured
      - .pym tool executes in Cairn workspace
      - Tool result appended to messages
      - Loop continues until submit_result or turn limit
   e. Return AgentResult to coordinator

6. Coordinator aggregates NodeResult from all runners

7. Result Presenter displays table/JSON output

8. User reviews workspace diffs; accepts/rejects/retries per operation
```

---

## Concurrency Model

### Node-Level Concurrency

```python
# All nodes processed in parallel, up to max_concurrent_runners
semaphore = asyncio.Semaphore(config.runner.max_concurrent_runners)

async def process_with_limit(node):
    async with semaphore:
        return await coordinator.process_node(node, operations)

results = await asyncio.gather(*[
    process_with_limit(node) for node in nodes
])
```

### Operation-Level Concurrency (within a node)

Within a single node, all operation runners start simultaneously:

```python
results = await asyncio.gather(*[
    FunctionGemmaRunner(op_def, node, ...).run()
    for op_def in operation_definitions
], return_exceptions=True)
```

### Model Loading Strategy

To avoid loading each 288MB model multiple times, runners cache loaded `Llama` instances by model path:

```python
class ModelCache:
    _instances: dict[str, Llama] = {}

    @classmethod
    def get(cls, model_path: str) -> Llama:
        if model_path not in cls._instances:
            cls._instances[model_path] = Llama(model_path=model_path, ...)
        return cls._instances[model_path]
```

---

## Error Handling

| Failure Mode | Recovery | User Impact |
|---|---|---|
| Node discovery failure (bad query) | Skip node, log `DISC_002` | Warning for affected file |
| Subagent YAML invalid | Skip operation, log `AGENT_001` | Error shown for operation |
| GGUF model not found | Skip operation, log `AGENT_002` | Error shown for operation |
| Runner turn limit hit | Mark operation failed, log `AGENT_003` | Partial result returned |
| `.pym` tool execution error | Tool returns error dict; model decides to retry or submit | Included in agent result |
| Workspace merge conflict | Rollback, preserve workspace | User prompted to resolve manually |

### Error Schema

```python
class AgentError(BaseModel):
    node_id: str
    operation: str
    phase: Literal["init", "model_load", "loop", "tool", "merge"]
    error_code: str
    message: str
    traceback: Optional[str]
    timestamp: datetime
```

---

## Configuration System

### remora.yaml

```yaml
root_dirs:
  - src/
  - lib/

queries:
  - function_def
  - class_def

agents_dir: agents/   # Root of the agents/ directory

operations:
  lint:
    enabled: true
    auto_accept: false
    subagent: lint/lint_subagent.yaml   # Relative to agents_dir

  test:
    enabled: true
    auto_accept: false
    subagent: test/test_subagent.yaml

  docstring:
    enabled: true
    auto_accept: false
    style: google          # Passed to docstring subagent at init

  sample_data:
    enabled: false

runner:
  max_turns: 20
  max_concurrent_runners: 4
  timeout: 300

cairn:
  timeout: 120
```

### Configuration Precedence

```
1. CLI flags (highest)
2. remora.yaml in project root
3. Default values (lowest)
```

---

## Technology Stack

| Layer | Component | Technology |
|---|---|---|
| Application | CLI | Typer |
| Application | Config | Pydantic |
| Application | Terminal UI | Rich |
| Application | File Watching | watchfiles |
| Orchestration | Node Discovery | Pydantree + Tree-sitter |
| Orchestration | Async Runtime | AsyncIO |
| Runner | Model Inference | llama-cpp-python |
| Runner | Model Format | GGUF (Q8 quantization) |
| Runner | Template Rendering | Jinja2 |
| Execution | Sandboxed Tool Scripts | Cairn (.pym) |
| Execution | Workspace Isolation | Cairn Copy-on-Write |
| Training | Base Model | FunctionGemma 270M (Google) |
| Training | Fine-tuning | Unsloth / HuggingFace PEFT |
| Training | Quantization | llama.cpp gguf conversion |

---

**Document Version**: 2.0
**Last Updated**: 2026-02-17
**Status**: FunctionGemma Rework
