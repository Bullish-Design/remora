# Remora Technical Specification

## Document Overview

This document specifies the technical contracts, APIs, data schemas, and file formats for the Remora library.

## 1. Command-Line Interface (CLI)

### 1.1 `remora analyze`

Analyze Python code and generate suggestions.

**Syntax:**
```bash
remora analyze [PATHS...] [OPTIONS]
```

**Arguments:**
- `PATHS`: One or more directories or files to analyze (optional, defaults to current directory)

**Options:**
- `--operations, -o`: Comma-separated list of operations to run
  - Choices: `lint`, `test`, `docstring`, `sample_data`, `all`
  - Default: `all`
  - Example: `-o lint,test`

- `--config, -c`: Path to configuration file
  - Default: `remora.yaml` in current directory
  - Example: `-c config/remora.yaml`

- `--queries, -q`: Comma-separated list of query types
  - Choices: `function_def`, `class_def`, `file`, `all`
  - Default: `all`
  - Example: `-q function_def,class_def`

- `--auto-accept`: Auto-stage changes for configured auto-accept operations
  - Flag (no value)
  - Still requires user confirmation for merge

- `--format, -f`: Output format
  - Choices: `table`, `json`, `interactive`
  - Default: `table`

- `--max-concurrent`: Maximum concurrent agents
  - Type: Integer
  - Default: From config or 10
  - Example: `--max-concurrent 5`

- `--timeout`: Agent timeout in seconds
  - Type: Integer
  - Default: From config or 120
  - Example: `--timeout 300`

**Examples:**
```bash
# Analyze current directory with all operations
remora analyze

# Analyze specific directory with only linting
remora analyze src/ -o lint

# Analyze multiple paths with custom config
remora analyze src/ lib/ -c .remora.yaml

# Output JSON for programmatic use
remora analyze src/ -f json > results.json

# Auto-accept configured operations (still requires confirmation)
remora analyze src/ --auto-accept
```

**Exit Codes:**
- `0`: Success (all operations completed)
- `1`: Partial failure (some operations failed)
- `2`: Complete failure (no operations succeeded)
- `3`: Configuration error
- `4`: User cancelled

### 1.2 `remora watch`

Watch files and analyze on changes (reactive mode).

**Syntax:**
```bash
remora watch [PATHS...] [OPTIONS]
```

**Arguments:**
- `PATHS`: One or more directories to watch (optional, defaults to current directory)

**Options:**
- Same as `remora analyze`
- Additional:
  - `--debounce`: Debounce delay in milliseconds
    - Type: Integer
    - Default: 500
    - Example: `--debounce 1000`

**Examples:**
```bash
# Watch current directory
remora watch

# Watch specific directories with debounce
remora watch src/ tests/ --debounce 1000

# Watch with only linting enabled
remora watch src/ -o lint --auto-accept
```

**Behavior:**
- Watches for `.py` file changes
- Debounces rapid changes (avoids duplicate processing)
- Re-analyzes only modified files
- Runs until interrupted (Ctrl+C)

**Exit Codes:**
- `0`: User interrupted (clean exit)
- `1`: Watch setup failed
- `3`: Configuration error

### 1.3 `remora list-agents`

List available specialized agents.

**Syntax:**
```bash
remora list-agents [OPTIONS]
```

**Options:**
- `--format, -f`: Output format
  - Choices: `table`, `json`
  - Default: `table`

**Output:**
```
┌──────────────┬─────────────────────────────────┬──────────┐
│ Agent        │ Description                     │ Source   │
├──────────────┼─────────────────────────────────┼──────────┤
│ lint         │ Run linters and apply fixes     │ bundled  │
│ test         │ Generate unit tests             │ bundled  │
│ docstring    │ Generate/improve docstrings     │ bundled  │
│ sample_data  │ Generate example fixtures       │ bundled  │
└──────────────┴─────────────────────────────────┴──────────┘
```

### 1.4 `remora config`

Show current configuration (merged from file and defaults).

**Syntax:**
```bash
remora config [OPTIONS]
```

**Options:**
- `--format, -f`: Output format
  - Choices: `yaml`, `json`
  - Default: `yaml`

**Output:**
```yaml
root_dirs:
  - src/
queries:
  - function_def
  - class_def
  - file
operations:
  lint:
    enabled: true
    auto_accept: true
    tools:
      - ruff
  test:
    enabled: true
    auto_accept: false
    framework: pytest
# ... etc
```

## 2. Programmatic API

### 2.1 Main API: `RemoraAnalyzer`

```python
from remora import RemoraAnalyzer, Operations

class RemoraAnalyzer:
    """Main interface for programmatic analysis."""

    def __init__(
        self,
        root_dirs: list[str | Path],
        queries: list[str] | None = None,
        operations: list[Operations] | None = None,
        config_path: Path | None = None,
        config: RemoraConfig | None = None,
    ):
        """
        Initialize analyzer.

        Args:
            root_dirs: Directories to analyze
            queries: Query types (function_def, class_def, file)
            operations: Operations to run (LINT, TEST, DOCSTRING, SAMPLE_DATA)
            config_path: Path to remora.yaml
            config: RemoraConfig object (overrides config_path)
        """

    async def analyze(self) -> AnalysisResults:
        """
        Run analysis on all nodes.

        Returns:
            AnalysisResults object containing results for all nodes
        """

    async def get_results(self) -> AnalysisResults:
        """Get cached results from last analysis."""

    async def accept(
        self,
        node_id: str | None = None,
        operation: Operations | None = None,
    ) -> None:
        """
        Accept changes and merge to stable workspace.

        Args:
            node_id: Specific node to accept (None = all nodes)
            operation: Specific operation to accept (None = all operations)
        """

    async def reject(
        self,
        node_id: str,
        operation: Operations,
    ) -> None:
        """
        Reject changes for a specific node/operation.

        Args:
            node_id: Node to reject
            operation: Operation to reject
        """

    async def retry(
        self,
        node_id: str,
        operation: Operations,
        config: dict | None = None,
    ) -> OperationResult:
        """
        Retry a failed/rejected operation with optional config override.

        Args:
            node_id: Node to retry
            operation: Operation to retry
            config: Optional config overrides for this retry

        Returns:
            OperationResult for the retry attempt
        """
```

**Usage Example:**
```python
import asyncio
from remora import RemoraAnalyzer, Operations

async def main():
    # Initialize analyzer
    analyzer = RemoraAnalyzer(
        root_dirs=["src/"],
        queries=["function_def", "class_def"],
        operations=[Operations.LINT, Operations.TEST]
    )

    # Run analysis
    results = await analyzer.analyze()

    # Inspect results
    for node_result in results.nodes:
        print(f"{node_result.node_name}:")
        for op, op_result in node_result.operations.items():
            print(f"  {op}: {op_result.status}")

    # Accept specific changes
    await analyzer.accept(node_id="abc123", operation=Operations.LINT)

    # Accept all linting changes
    await analyzer.accept(operation=Operations.LINT)

    # Retry failed operation
    await analyzer.retry(
        node_id="xyz789",
        operation=Operations.TEST,
        config={"framework": "unittest"}
    )

asyncio.run(main())
```

### 2.2 Enumerations

```python
from enum import Enum

class Operations(str, Enum):
    """Available operation types."""
    LINT = "lint"
    TEST = "test"
    DOCSTRING = "docstring"
    SAMPLE_DATA = "sample_data"

class NodeType(str, Enum):
    """CST node types."""
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"

class OperationStatus(str, Enum):
    """Operation result status."""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
```

## 3. Configuration File Format

### 3.1 `remora.yaml` Schema

```yaml
root_dirs:
  - src/
  - lib/

queries:
  - function_def
  - class_def

agents_dir: agents/

server:
  base_url: "http://function-gemma-server:8000/v1"
  api_key: "EMPTY"
  timeout: 120
  default_adapter: "google/functiongemma-270m-it"

operations:
  lint:
    enabled: true
    auto_accept: true  # Still requires user confirmation
    subagent: lint/lint_subagent.yaml
    # model_id: "lint"  # Optional adapter name

  test:
    enabled: true
    auto_accept: false
    subagent: test/test_subagent.yaml

  docstring:
    enabled: true
    auto_accept: false
    subagent: docstring/docstring_subagent.yaml
    style: google

  sample_data:
    enabled: false
    subagent: sample_data/sample_data_subagent.yaml

runner:
  max_turns: 20
  max_concurrent_runners: 16
  timeout: 300

cairn:
  timeout: 120
```

### 3.2 Configuration Validation (Pydantic Schema)

```python
from pydantic import BaseModel, ConfigDict, Field
from pathlib import Path

class ServerConfig(BaseModel):
    base_url: str = "http://function-gemma-server:8000/v1"
    api_key: str = "EMPTY"
    timeout: int = 120
    default_adapter: str = "google/functiongemma-270m-it"

class RunnerConfig(BaseModel):
    max_turns: int = 20
    max_concurrent_runners: int = 16
    timeout: int = 300

class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    auto_accept: bool = False
    subagent: str
    model_id: str | None = None  # LoRA adapter name override

class CairnConfig(BaseModel):
    timeout: int = 120

class RemoraConfig(BaseModel):
    root_dirs: list[Path] = Field(default_factory=lambda: [Path(".")])
    queries: list[str] = Field(default_factory=lambda: ["function_def", "class_def"])
    agents_dir: Path = Path("agents")
    server: ServerConfig = Field(default_factory=ServerConfig)
    operations: dict[str, OperationConfig] = Field(default_factory=dict)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    cairn: CairnConfig = Field(default_factory=CairnConfig)
```

## 4. Data Schemas

### 4.1 CST Node

```python
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Literal

class CSTNode(BaseModel):
    """Represents a single CST node extracted from source code."""

    node_id: str = Field(
        description="Unique identifier (hash of file_path + node_type + name)"
    )
    node_type: Literal["file", "class", "function"]
    name: str = Field(description="Name of the node (function/class name or filename)")
    file_path: Path = Field(description="Path to source file")
    start_byte: int = Field(description="Start byte offset in file")
    end_byte: int = Field(description="End byte offset in file")
    text: str = Field(description="Source code text of the node")

    @property
    def context(self) -> str:
        """For MVP: returns the node's source text."""
        return self.text

    @property
    def location(self) -> str:
        """Human-readable location string."""
        return f"{self.file_path}::{self.name}"
```

### 4.2 Operation Result

```python
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

class OperationResult(BaseModel):
    """Result from a single specialized agent operation."""

    operation: Literal["lint", "test", "docstring", "sample_data"]
    status: Literal["success", "failed", "skipped"]
    workspace_id: str = Field(description="Cairn workspace ID for this operation")
    changed_files: list[Path] = Field(
        default_factory=list,
        description="Files modified in the workspace"
    )
    summary: str = Field(description="Human-readable summary of what was done")
    details: dict = Field(
        default_factory=dict,
        description="Operation-specific details"
    )
    error: str | None = Field(
        default=None,
        description="Error message if status=failed"
    )
    timestamp: datetime = Field(default_factory=datetime.now)

# Operation-specific details schemas

class LintDetails(BaseModel):
    """Details for lint operation."""
    issues_found: int
    issues_fixed: int
    tools_used: list[str]
    unfixable_issues: list[dict]  # List of issues that couldn't be auto-fixed

class TestDetails(BaseModel):
    """Details for test operation."""
    num_tests_generated: int
    test_file_path: Path
    coverage_estimate: int | None = None

class DocstringDetails(BaseModel):
    """Details for docstring operation."""
    action: Literal["added", "updated", "skipped"]
    style: str
    had_existing_docstring: bool

class SampleDataDetails(BaseModel):
    """Details for sample_data operation."""
    num_samples: int
    fixture_file_path: Path
    format: Literal["json", "yaml"]
```

### 4.3 Node Result

```python
from pydantic import BaseModel, Field

class NodeResult(BaseModel):
    """Aggregated results for a single node (from coordinator)."""

    node_id: str
    node_name: str
    node_type: Literal["file", "class", "function"]
    file_path: Path
    operations: dict[str, OperationResult] = Field(
        description="Map of operation name to result"
    )
    workspace_ids: list[str] = Field(
        description="All workspace IDs for this node"
    )
    errors: list[dict] = Field(
        default_factory=list,
        description="Errors encountered during processing"
    )
    timestamp: datetime = Field(default_factory=datetime.now)

    @property
    def success_count(self) -> int:
        """Number of successful operations."""
        return sum(1 for op in self.operations.values() if op.status == "success")

    @property
    def failed_count(self) -> int:
        """Number of failed operations."""
        return sum(1 for op in self.operations.values() if op.status == "failed")

    @property
    def overall_status(self) -> Literal["success", "partial", "failed"]:
        """Overall status for this node."""
        if self.failed_count == 0:
            return "success"
        elif self.success_count > 0:
            return "partial"
        else:
            return "failed"
```

### 4.4 Analysis Results

```python
from pydantic import BaseModel, Field

class AnalysisResults(BaseModel):
    """Complete results from analyzing a codebase."""

    nodes: list[NodeResult] = Field(description="Results for all nodes")
    total_nodes: int
    total_operations: int
    successful_operations: int
    failed_operations: int
    timestamp: datetime = Field(default_factory=datetime.now)
    duration_seconds: float

    @property
    def success_rate(self) -> float:
        """Percentage of successful operations."""
        if self.total_operations == 0:
            return 0.0
        return (self.successful_operations / self.total_operations) * 100

    def to_json(self) -> str:
        """Serialize to JSON."""
        return self.model_dump_json(indent=2)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return self.model_dump()
```

## 5. Tree-sitter Query Files (.scm)

### 5.1 `function_def.scm`

Extracts function definitions.

```scheme
; Capture function definitions
(function_definition
  name: (identifier) @function.name
) @function.def

; Capture async function definitions
(function_definition
  "async"
  name: (identifier) @async_function.name
) @async_function.def
```

**Captures:**
- `@function.def`: The entire function node
- `@function.name`: The function name
- `@async_function.def`: Async function node
- `@async_function.name`: Async function name

### 5.2 `class_def.scm`

Extracts class definitions.

```scheme
; Capture class definitions
(class_definition
  name: (identifier) @class.name
  body: (block) @class.body
) @class.def
```

**Captures:**
- `@class.def`: The entire class node
- `@class.name`: The class name
- `@class.body`: The class body (useful for method extraction)

### 5.3 `file.scm`

Captures file-level structure.

```scheme
; Capture module-level elements
(module) @file.module

; Capture imports
(import_statement) @file.import
(import_from_statement) @file.import_from

; Capture module docstring (first string literal)
(module
  (expression_statement
    (string) @file.docstring
  )
)
```

**Captures:**
- `@file.module`: The entire file as a module
- `@file.import`: Import statements
- `@file.import_from`: From-import statements
- `@file.docstring`: Module-level docstring

## 6. Agent Contracts

### 6.1 Coordinator Agent Contract

**Input Schema (`coordinator.pym`):**
```python
from grail import Input

# Required inputs
node_id: str = Input("node_id")
node_type: str = Input("node_type")  # "file" | "class" | "function"
node_name: str = Input("node_name")
node_text: str = Input("node_text")
file_path: str = Input("file_path")
operations: list[str] = Input("operations")  # ["lint", "test", ...]
agent_paths: dict[str, str] = Input("agent_paths")
```

**Output Schema:**
```python
{
    "node_id": str,
    "node_name": str,
    "operations": {
        "lint": {
            "status": "success" | "failed" | "skipped",
            "workspace_id": str,
            "changed_files": list[str],
            "summary": str,
            "details": dict,
            "error": str | None
        },
        # ... other operations
    },
    "workspace_ids": list[str],
    "errors": list[{
        "operation": str,
        "phase": "spawn" | "execution",
        "error": str
    }]
}
```

**External Functions (provided by orchestration layer):**
```python
@external
async def spawn_specialized_agent(agent_type: str, inputs: dict) -> str:
    """
    Spawn a specialized agent.

    Args:
        agent_type: Type of agent ("lint", "test", "docstring", "sample_data")
        inputs: Dictionary of inputs for the agent

    Returns:
        agent_id: Unique identifier for the spawned agent
    """

@external
async def wait_for_agent(agent_id: str) -> dict:
    """
    Wait for an agent to complete.

    Args:
        agent_id: Identifier from spawn_specialized_agent

    Returns:
        result: Dictionary containing agent results
    """

@external
async def log_error(message: str, error: dict) -> None:
    """
    Log an error to the orchestration layer.

    Args:
        message: Human-readable error message
        error: Error details dictionary
    """
```

### 6.2 Specialized Agent Contract

All specialized agents follow the same input contract.

**Input Schema:**
```python
from grail import Input

node_id: str = Input("node_id")
node_type: str = Input("node_type")
node_name: str = Input("node_name")
node_text: str = Input("node_text")
file_path: str = Input("file_path")
```

**Output Schema:**
```python
{
    "status": "success" | "failed" | "skipped",
    "workspace_id": str,
    "changed_files": list[str],
    "summary": str,
    "details": dict,  # Agent-specific details
    "error": str | None
}
```

**Common External Functions:**
```python
@external
async def write_file(path: str, content: str) -> None:
    """Write file to sandbox workspace."""

@external
async def read_file(path: str) -> str:
    """Read file from sandbox workspace."""

@external
async def run_command(cmd: str, args: list[str]) -> dict:
    """
    Run a command in the sandbox.

    Returns:
        {
            "stdout": str,
            "stderr": str,
            "exit_code": int
        }
    """
```

### 6.3 Lint Agent Specifics

**Additional Inputs (via operation config):**
```python
tools: list[str] = Input("tools")  # ["ruff", "pylint"]
ruff_config: str | None = Input("ruff_config")  # Path to config
```

**Output Details Schema:**
```python
{
    "issues_found": int,
    "issues_fixed": int,
    "tools_used": list[str],
    "unfixable_issues": [
        {
            "line": int,
            "column": int,
            "severity": "error" | "warning" | "info",
            "message": str,
            "rule": str
        }
    ]
}
```

### 6.4 Test Generator Agent Specifics

**Additional Inputs:**
```python
framework: str = Input("framework")  # "pytest" | "unittest"
coverage: bool = Input("coverage")
```

**Output Details Schema:**
```python
{
    "num_tests_generated": int,
    "test_file_path": str,
    "coverage_estimate": int | None,
    "test_names": list[str]
}
```

### 6.5 Docstring Agent Specifics

**Additional Inputs:**
```python
style: str = Input("style")  # "google" | "numpy" | "sphinx"
include_types: bool = Input("include_types")
include_examples: bool = Input("include_examples")
```

**Output Details Schema:**
```python
{
    "action": "added" | "updated" | "skipped",
    "style": str,
    "had_existing_docstring": bool,
    "docstring_preview": str  # First 100 chars of new docstring
}
```

### 6.6 Sample Data Agent Specifics

**Additional Inputs:**
```python
format: str = Input("format")  # "json" | "yaml"
num_samples: int = Input("num_samples")
```

**Output Details Schema:**
```python
{
    "num_samples": int,
    "fixture_file_path": str,
    "format": str,
    "sample_preview": dict  # First sample
}
```

## 7. Error Codes and Messages

### 7.1 Configuration Errors (Exit Code 3)

| Code | Message | Cause |
|------|---------|-------|
| `CONFIG_001` | Configuration file not found | `remora.yaml` doesn't exist at specified path |
| `CONFIG_002` | Invalid YAML syntax | Malformed YAML in config file |
| `CONFIG_003` | Invalid configuration schema | Config doesn't match Pydantic schema |
| `CONFIG_004` | Root directory not found | Specified root_dir doesn't exist |
| `CONFIG_005` | Invalid operation name | Unknown operation in config |
| `CONFIG_006` | Invalid query name | Unknown query type in config |

### 7.2 Server Errors (Exit Code 1)

| Code | Message | Cause |
|------|---------|-------|
| `SERVER_001` | vLLM server not reachable at startup | DNS failure or Tailscale connection offline |
| `SERVER_002` | Adapter not found on vLLM server | Requested LoRA adapter missing or misnamed |

### 7.3 Discovery Errors (Exit Code 1)

| Code | Message | Cause |
|------|---------|-------|
| `DISC_001` | Query file not found | `.scm` file doesn't exist |
| `DISC_002` | Invalid query syntax | Malformed Tree-sitter query |
| `DISC_003` | Source file parse error | Syntax error in Python file |
| `DISC_004` | No nodes discovered | No nodes matched queries |

### 7.4 Agent Errors (Exit Code 1)

| Code | Message | Cause |
|------|---------|-------|
| `AGENT_001` | Failed to spawn coordinator | Cairn unavailable or error |
| `AGENT_002` | vLLM server not reachable or adapter not found | vLLM base URL unavailable or adapter name invalid |
| `AGENT_003` | Failed to spawn specialized agent | Agent script not found or invalid |
| `AGENT_004` | Specialized agent timeout | Agent exceeded timeout |
| `AGENT_005` | Agent execution error | Runtime error in agent |
| `AGENT_006` | Invalid agent output | Agent returned invalid schema |

### 7.5 Workspace Errors (Exit Code 1)

| Code | Message | Cause |
|------|---------|-------|
| `WORK_001` | Failed to create workspace | Filesystem or permission error |
| `WORK_002` | Failed to merge workspace | Merge conflict or permission error |
| `WORK_003` | Workspace not found | Invalid workspace_id reference |

## 8. Result Output Formats

### 8.1 Table Format (Default)

```
Remora Analysis Results
═══════════════════════════════════════════════════════════

Summary:
  Total Nodes: 15
  Total Operations: 60
  Successful: 52 (86.7%)
  Failed: 5 (8.3%)
  Skipped: 3 (5.0%)
  Duration: 45.3s

Results by Node:
┌────────────────────────────────┬──────┬──────┬──────────┬──────────┐
│ Node                           │ Lint │ Test │ Docstring│ Sample   │
├────────────────────────────────┼──────┼──────┼──────────┼──────────┤
│ src/utils.py::calculate        │  ✓   │  ✓   │    ✓     │    ✓     │
│ src/utils.py::validate         │  ✓   │  ✗   │    ✓     │    -     │
│ src/models.py::User            │  ✓   │  ✓   │    ✓     │    ✓     │
│ ...                            │ ...  │ ...  │   ...    │   ...    │
└────────────────────────────────┴──────┴──────┴──────────┴──────────┘

Legend: ✓ Success | ✗ Failed | - Skipped

Failed Operations:
  • src/utils.py::validate - test: ImportError: missing module 'pytest'
  • src/api.py::handler - docstring: Timeout after 120s

Next Steps:
  1. Review results: remora review
  2. Accept changes: remora accept --operation lint
  3. Retry failed: remora retry src/utils.py::validate --operation test
```

### 8.2 JSON Format

```json
{
  "total_nodes": 15,
  "total_operations": 60,
  "successful_operations": 52,
  "failed_operations": 5,
  "timestamp": "2026-02-17T10:30:45.123456",
  "duration_seconds": 45.3,
  "nodes": [
    {
      "node_id": "abc123",
      "node_name": "calculate",
      "node_type": "function",
      "file_path": "src/utils.py",
      "operations": {
        "lint": {
          "status": "success",
          "workspace_id": "lint-abc123",
          "changed_files": ["src/utils.py"],
          "summary": "Fixed 3 linting issues",
          "details": {
            "issues_found": 3,
            "issues_fixed": 3,
            "tools_used": ["ruff"],
            "unfixable_issues": []
          },
          "timestamp": "2026-02-17T10:30:15.123456"
        },
        "test": {
          "status": "success",
          "workspace_id": "test-abc123",
          "changed_files": ["tests/test_utils.py"],
          "summary": "Generated 5 test cases",
          "details": {
            "num_tests_generated": 5,
            "test_file_path": "tests/test_utils.py",
            "coverage_estimate": 85
          },
          "timestamp": "2026-02-17T10:30:25.123456"
        }
      },
      "workspace_ids": ["lint-abc123", "test-abc123"],
      "errors": []
    }
  ]
}
```

### 8.3 Interactive Format

```
Remora Analysis Complete!

Found 15 nodes with 60 operations.

─────────────────────────────────────────────────
Node 1/15: src/utils.py::calculate
─────────────────────────────────────────────────

✓ Lint: Fixed 3 issues
  - Changed files: src/utils.py
  - View diff: [y/n]? y

  [Shows diff of changes]

  Accept changes? [y/n/skip/quit]: y
  ✓ Changes accepted and merged

✓ Test: Generated 5 test cases
  - Changed files: tests/test_utils.py
  - View diff: [y/n]? n

  Accept changes? [y/n/skip/quit]: y
  ✓ Changes accepted and merged

[Continue for all operations and nodes...]

─────────────────────────────────────────────────
Review Complete!

Accepted: 52 operations
Rejected: 3 operations
Skipped: 5 operations
```

## 9. Extension Points

### 9.1 Custom Context Provider

```python
from remora.context import ContextProvider, CSTNode

class CustomContextProvider(ContextProvider):
    """Custom context provider implementation."""

    async def get_context(self, node: CSTNode) -> str:
        """
        Provide context for a node.

        Args:
            node: The CST node to provide context for

        Returns:
            Context string to pass to agents
        """
        # Custom implementation
        # Example: include file-level imports + node text
        imports = await self._get_file_imports(node.file_path)
        return f"{imports}\n\n{node.text}"

# Register custom provider
from remora import RemoraAnalyzer

analyzer = RemoraAnalyzer(
    root_dirs=["src/"],
    context_provider=CustomContextProvider()
)
```

### 9.2 Custom Result Formatter

```python
from remora.formatters import ResultFormatter, AnalysisResults

class HTMLFormatter(ResultFormatter):
    """Format results as HTML."""

    def format(self, results: AnalysisResults) -> str:
        """
        Format analysis results.

        Args:
            results: The analysis results to format

        Returns:
            Formatted string (HTML in this case)
        """
        # Generate HTML
        html = "<html>...</html>"
        return html

# Use custom formatter
from remora import RemoraAnalyzer

analyzer = RemoraAnalyzer(root_dirs=["src/"])
results = await analyzer.analyze()

formatter = HTMLFormatter()
html_output = formatter.format(results)
```

### 9.3 Custom Specialized Agent

**1. Create custom agent script (`custom_agent.pym`):**
```python
from grail import Input, external

# Standard inputs
node_id = Input("node_id")
node_text = Input("node_text")
# ... other standard inputs

# Custom inputs
custom_param = Input("custom_param")

# Agent logic
@external
async def write_file(path: str, content: str) -> None:
    pass

# ... implement custom logic ...

await submit_result(
    summary="Custom operation completed",
    changed_files=[...],
    workspace_id=f"custom-{node_id}"
)
```

**2. Register in configuration:**
```yaml
operations:
  custom_operation:
    enabled: true
    auto_accept: false
    custom_param: "value"

agents:
  paths:
    custom_operation: /path/to/custom_agent.pym
```

**3. Use in analysis:**
```bash
remora analyze src/ --operations custom_operation
```

### 9.4 Custom LoRA Adapters

Register LoRA adapters with the vLLM server and reference them via `operations.<name>.model_id` in `remora.yaml`. This replaces the old workflow of installing custom `llm` plugins for new models.

## 10. Testing Specifications

### 10.1 Unit Tests

**Discovery Engine Tests:**
- Test query loading from `.scm` files
- Test node extraction from sample Python files
- Test handling of malformed source code
- Test node deduplication

**Configuration Tests:**
- Test YAML parsing and validation
- Test CLI override precedence
- Test default value fallbacks
- Test invalid configuration handling

**Result Formatting Tests:**
- Test table formatting
- Test JSON serialization
- Test interactive mode flow

### 10.2 Integration Tests

**End-to-End Flow:**
- Test full analysis pipeline (discovery → orchestration → execution → results)
- Test with multiple nodes and operations
- Test error handling and partial failures
- Test workspace merge workflow

**Agent Tests:**
- Test coordinator spawning and result aggregation
- Test specialized agent execution
- Test agent timeout handling
- Test agent error propagation

### 10.3 Acceptance Tests

**MVP Success Criteria:**
1. Point at Python file → get linting suggestions → accept changes → verify files updated
2. Point at function → generate tests → verify test file created
3. Point at class → add docstrings → verify docstrings added
4. Process multiple nodes concurrently → verify all results returned
5. Fail one agent → verify other agents continue
6. Run in watch mode → modify file → verify re-analysis triggered

---

**Document Version**: 1.0
**Last Updated**: 2026-02-17
**Status**: Initial Draft
