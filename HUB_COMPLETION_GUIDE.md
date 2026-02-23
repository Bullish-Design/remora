# Hub Completion Guide

> **Status**: Implementation Guide
> **Author**: Claude Opus 4.5
> **Date**: 2026-02-22
> **Purpose**: Complete the Hub daemon to "first-class" status in Remora

---

## Table of Contents

1. [Current State Assessment](#1-current-state-assessment)
2. [Architecture Overview](#2-architecture-overview)
3. [Phase 1: Configuration Integration](#3-phase-1-configuration-integration)
4. [Phase 2: Cross-File Analysis](#4-phase-2-cross-file-analysis)
5. [Phase 3: Complexity Metrics](#5-phase-3-complexity-metrics)
6. [Phase 4: Import Analysis](#6-phase-4-import-analysis)
7. [Phase 5: Test Discovery](#7-phase-5-test-discovery)
8. [Phase 6: Enhanced Testing](#8-phase-6-enhanced-testing)
9. [Phase 7: Observability](#9-phase-7-observability)
10. [Verification Checklist](#10-verification-checklist)

---

## 1. Current State Assessment

### 1.1 What's Fully Implemented (No Work Needed)

| Component | File | Status |
|-----------|------|--------|
| HubDaemon | `src/remora/hub/daemon.py` | Complete (355 lines) |
| HubClient | `src/remora/context/hub_client.py` | Complete (206 lines) |
| NodeStateStore | `src/remora/hub/store.py` | Complete (276 lines) |
| RulesEngine | `src/remora/hub/rules.py` | Complete (217 lines) |
| FileWatcher | `src/remora/hub/watcher.py` | Complete (133 lines) |
| SimpleIndexer | `src/remora/hub/indexer.py` | Complete (196 lines) |
| CLI | `src/remora/hub/cli.py` | Complete (181 lines) |
| Grail Script | `.grail/hub/extract_signatures.pym` | Complete (158 lines) |
| Core Models | `src/remora/hub/models.py` | Partial (see below) |

### 1.2 What Needs Implementation

| Feature | Priority | Effort | Description |
|---------|----------|--------|-------------|
| **Hub Configuration** | P0 | 1 day | Add `hub:` section to remora.yaml |
| **Cross-File Analysis** | P1 | 3 days | Populate `callers`, `callees` fields |
| **Complexity Metrics** | P1 | 1 day | Compute cyclomatic complexity |
| **Import Analysis** | P2 | 1 day | Populate `imports` field |
| **Test Discovery** | P2 | 2 days | Populate `related_tests` field |
| **Enhanced Testing** | P2 | 2 days | Daemon lifecycle, stress tests |
| **Observability** | P3 | 1 day | Metrics, logging improvements |

**Total Estimated Effort**: 11 days

### 1.3 NodeState Fields Status

```python
# src/remora/hub/models.py - Current field population status

class NodeState(VersionedKVRecord):
    # POPULATED (working):
    key: str                          # node:file:name
    file_path: str                    # Absolute path
    node_name: str                    # Function/class name
    node_type: str                    # "function" | "class" | "module"
    source_hash: str                  # SHA256 of node source
    file_hash: str                    # SHA256 of file
    signature: str                    # Function/class signature
    docstring: str | None             # First docstring
    decorators: list[str]             # @decorator list
    line_count: int                   # Node line count
    has_type_hints: bool              # Type hints detected
    update_source: str                # How node was updated
    created_at: datetime
    updated_at: datetime

    # NOT POPULATED (always None/empty):
    imports: list[str]                # [] - needs implementation
    callers: list[str] | None         # None - needs cross-file analysis
    callees: list[str] | None         # None - needs cross-file analysis
    complexity: int | None            # None - needs computation
    related_tests: list[str] | None   # None - needs test discovery
    docstring_outdated: bool | None   # None - needs comparison logic
```

---

## 2. Architecture Overview

### 2.1 Data Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   File System   │────>│    HubWatcher    │────>│    HubDaemon    │
│   (*.py files)  │     │  (watchfiles)    │     │  (orchestrator) │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                        ┌─────────────────────────────────┼───────────────────────────────┐
                        │                                 │                               │
                        ▼                                 ▼                               ▼
               ┌─────────────────┐              ┌─────────────────┐              ┌─────────────────┐
               │  RulesEngine    │              │  Grail Script   │              │  SimpleIndexer  │
               │  (routing)      │              │  (extraction)   │              │  (fallback)     │
               └────────┬────────┘              └────────┬────────┘              └────────┬────────┘
                        │                                │                                │
                        └────────────────────────────────┼────────────────────────────────┘
                                                         │
                                                         ▼
                                                 ┌─────────────────┐
                                                 │ NodeStateStore  │
                                                 │ (FSdantic DB)   │
                                                 └────────┬────────┘
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │   HubClient     │──────> Agents
                                                 │   (read-only)   │
                                                 └─────────────────┘
```

### 2.2 Key Files Reference

```
src/remora/
├── hub/
│   ├── __init__.py
│   ├── daemon.py          # HubDaemon - main background process
│   ├── store.py           # NodeStateStore - FSdantic CRUD
│   ├── models.py          # NodeState, FileIndex, HubStatus
│   ├── rules.py           # RulesEngine, UpdateAction
│   ├── watcher.py         # HubWatcher - file monitoring
│   ├── indexer.py         # index_file_simple() fallback
│   └── cli.py             # remora-hub command
├── context/
│   ├── hub_client.py      # HubClient - agent access
│   └── manager.py         # ContextManager.pull_hub_context()
├── config.py              # RemoraConfig (needs hub section)
└── constants.py           # HUB_DB_NAME = "hub.db"

.grail/
└── hub/
    └── extract_signatures.pym  # Grail extraction script
```

---

## 3. Phase 1: Configuration Integration

**Goal**: Add a `hub:` configuration section to remora.yaml and RemoraConfig.

### 3.1 Define HubConfig Model

**File**: `src/remora/config.py`

Add after `WatchConfig`:

```python
class HubConfig(BaseModel):
    """Configuration for the Node State Hub daemon."""

    # Enable/disable modes
    mode: Literal["in-process", "daemon", "disabled"] = "disabled"

    # Database location (relative to project root)
    db_path: Path | None = None  # Default: .remora/hub.db

    # Indexing behavior
    index_on_startup: bool = True
    watch_for_changes: bool = True

    # Freshness thresholds
    stale_threshold_seconds: float = 5.0
    max_adhoc_files: int = 5

    # Ignore patterns (in addition to watch.ignore_patterns)
    additional_ignore_patterns: list[str] = Field(default_factory=list)

    # Cross-file analysis (Phase 2)
    enable_cross_file_analysis: bool = False
    cross_file_analysis_depth: int = 2  # How many hops to follow

    # Performance tuning
    batch_size: int = 50  # Files to index per batch
    index_delay_ms: int = 100  # Delay between batches

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
```

### 3.2 Update RemoraConfig

**File**: `src/remora/config.py`

Replace `hub_mode` field:

```python
class RemoraConfig(BaseModel):
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    agents_dir: Path = Path("agents")
    server: ServerConfig = Field(default_factory=ServerConfig)
    operations: dict[str, OperationConfig] = Field(default_factory=_default_operations)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    cairn: CairnConfig = Field(default_factory=CairnConfig)
    event_stream: EventStreamConfig = Field(default_factory=EventStreamConfig)
    llm_log: LlmLogConfig = Field(default_factory=LlmLogConfig)
    watch: WatchConfig = Field(default_factory=WatchConfig)
    hub: HubConfig = Field(default_factory=HubConfig)  # NEW

    # Remove: hub_mode: Literal["in-process", "daemon", "disabled"] = "disabled"
```

### 3.3 Update remora.yaml Example

**File**: `remora.yaml`

Add after `llm_log:` section:

```yaml
hub:
  mode: disabled  # "in-process" | "daemon" | "disabled"
  # db_path: .remora/hub.db  # default
  index_on_startup: true
  watch_for_changes: true
  stale_threshold_seconds: 5.0
  max_adhoc_files: 5
  enable_cross_file_analysis: false
  # cross_file_analysis_depth: 2
  # batch_size: 50
  # index_delay_ms: 100
  log_level: INFO
```

### 3.4 Update HubClient to Use Config

**File**: `src/remora/context/hub_client.py`

Replace hardcoded constants:

```python
# Before:
STALE_THRESHOLD_SECONDS = 5.0
MAX_ADHOC_FILES = 5

# After:
from remora.config import HubConfig

class HubClient:
    def __init__(
        self,
        db_path: Path | None = None,
        config: HubConfig | None = None,
    ):
        self._db_path = db_path
        self._config = config or HubConfig()
        self._workspace: fsdantic.Workspace | None = None

    @property
    def stale_threshold(self) -> float:
        return self._config.stale_threshold_seconds

    @property
    def max_adhoc_files(self) -> int:
        return self._config.max_adhoc_files
```

### 3.5 Verification

**Test**: `tests/unit/test_config.py`

```python
def test_hub_config_defaults():
    config = RemoraConfig()
    assert config.hub.mode == "disabled"
    assert config.hub.stale_threshold_seconds == 5.0
    assert config.hub.max_adhoc_files == 5
    assert config.hub.enable_cross_file_analysis is False


def test_hub_config_from_yaml(tmp_path):
    yaml_content = """
hub:
  mode: daemon
  stale_threshold_seconds: 10.0
  enable_cross_file_analysis: true
"""
    config_file = tmp_path / "remora.yaml"
    config_file.write_text(yaml_content)
    # Create agents dir
    (tmp_path / "agents").mkdir()

    config = load_config(config_file)
    assert config.hub.mode == "daemon"
    assert config.hub.stale_threshold_seconds == 10.0
    assert config.hub.enable_cross_file_analysis is True
```

---

## 4. Phase 2: Cross-File Analysis

**Goal**: Populate `callers` and `callees` fields by analyzing function call graphs.

### 4.1 Create Call Graph Analyzer

**File**: `src/remora/hub/call_graph.py` (NEW)

```python
"""
src/remora/hub/call_graph.py

Cross-file call graph analysis for populating callers/callees fields.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.hub.store import NodeStateStore


@dataclass
class CallSite:
    """A single function call site."""
    caller_node_id: str  # node:file:func that makes the call
    callee_name: str     # Name being called (may be unresolved)
    line_number: int
    is_method_call: bool = False


@dataclass
class CallGraphBuilder:
    """Builds a call graph from indexed nodes."""

    store: "NodeStateStore"
    project_root: Path

    # Internal state
    _name_to_node_id: dict[str, list[str]] = field(default_factory=dict)
    _call_sites: list[CallSite] = field(default_factory=list)

    async def build(self) -> dict[str, dict[str, list[str]]]:
        """
        Build the call graph and return updates.

        Returns:
            Dict mapping node_id -> {"callers": [...], "callees": [...]}
        """
        # Step 1: Build name -> node_id index
        await self._build_name_index()

        # Step 2: Extract call sites from all function nodes
        await self._extract_call_sites()

        # Step 3: Resolve and aggregate
        return await self._resolve_graph()

    async def _build_name_index(self) -> None:
        """Build a mapping from function/class names to node IDs."""
        self._name_to_node_id.clear()

        all_nodes = await self.store.list_all_nodes()
        for node_id in all_nodes:
            node = await self.store.get(node_id)
            if node is None:
                continue

            name = node.node_name
            if name not in self._name_to_node_id:
                self._name_to_node_id[name] = []
            self._name_to_node_id[name].append(node_id)

    async def _extract_call_sites(self) -> None:
        """Extract all function calls from each node's source."""
        self._call_sites.clear()

        all_nodes = await self.store.list_all_nodes()
        for node_id in all_nodes:
            node = await self.store.get(node_id)
            if node is None or node.node_type != "function":
                continue

            # Read the source file and extract the node's AST
            file_path = Path(node.file_path)
            if not file_path.exists():
                continue

            try:
                source = file_path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError):
                continue

            # Find the function definition
            for item in ast.walk(tree):
                if isinstance(item, ast.FunctionDef) and item.name == node.node_name:
                    # Extract calls within this function
                    for call_node in ast.walk(item):
                        if isinstance(call_node, ast.Call):
                            call_info = self._extract_call_info(call_node)
                            if call_info:
                                self._call_sites.append(CallSite(
                                    caller_node_id=node_id,
                                    callee_name=call_info[0],
                                    line_number=call_node.lineno,
                                    is_method_call=call_info[1],
                                ))
                    break

    def _extract_call_info(self, call: ast.Call) -> tuple[str, bool] | None:
        """Extract the name being called and whether it's a method call."""
        func = call.func

        if isinstance(func, ast.Name):
            # Direct call: foo()
            return (func.id, False)
        elif isinstance(func, ast.Attribute):
            # Method call: obj.method() - extract just the method name
            return (func.attr, True)

        return None

    async def _resolve_graph(self) -> dict[str, dict[str, list[str]]]:
        """Resolve call sites to actual node IDs."""
        # Initialize result for all nodes
        result: dict[str, dict[str, list[str]]] = {}

        all_nodes = await self.store.list_all_nodes()
        for node_id in all_nodes:
            result[node_id] = {"callers": [], "callees": []}

        # Process call sites
        for site in self._call_sites:
            # Resolve callee name to node IDs
            callee_ids = self._name_to_node_id.get(site.callee_name, [])

            for callee_id in callee_ids:
                # Add caller -> callee relationship
                if callee_id not in result[site.caller_node_id]["callees"]:
                    result[site.caller_node_id]["callees"].append(callee_id)

                # Add callee <- caller relationship
                if site.caller_node_id not in result[callee_id]["callers"]:
                    result[callee_id]["callers"].append(site.caller_node_id)

        return result


async def update_call_graph(store: "NodeStateStore", project_root: Path) -> int:
    """
    Run call graph analysis and update all nodes.

    Returns:
        Number of nodes updated.
    """
    builder = CallGraphBuilder(store=store, project_root=project_root)
    graph = await builder.build()

    updated = 0
    for node_id, relationships in graph.items():
        node = await store.get(node_id)
        if node is None:
            continue

        # Check if update needed
        if node.callers != relationships["callers"] or node.callees != relationships["callees"]:
            node.callers = relationships["callers"] if relationships["callers"] else None
            node.callees = relationships["callees"] if relationships["callees"] else None
            await store.set(node)
            updated += 1

    return updated
```

### 4.2 Integrate with HubDaemon

**File**: `src/remora/hub/daemon.py`

Add call graph update after cold start indexing:

```python
from remora.hub.call_graph import update_call_graph

class HubDaemon:
    async def _cold_start_index(self) -> None:
        # ... existing indexing code ...

        # After indexing all files, run cross-file analysis if enabled
        if self._config and self._config.enable_cross_file_analysis:
            logger.info("Running cross-file call graph analysis...")
            updated = await update_call_graph(self._store, self._project_root)
            logger.info(f"Call graph analysis complete: {updated} nodes updated")

    async def _handle_file_change(self, path: Path, change_type: str) -> None:
        # ... existing handling code ...

        # After processing file change, update call graph
        if self._config and self._config.enable_cross_file_analysis:
            # Incremental update: only re-analyze affected files
            await self._incremental_call_graph_update(path)
```

### 4.3 Verification

**Test**: `tests/hub/test_call_graph.py`

```python
import pytest
from pathlib import Path
from remora.hub.call_graph import CallGraphBuilder, update_call_graph


@pytest.fixture
def sample_project(tmp_path):
    """Create a sample project with cross-file calls."""
    # File 1: utils.py
    utils = tmp_path / "utils.py"
    utils.write_text('''
def helper():
    """A helper function."""
    return 42

def another_helper():
    return helper() + 1
''')

    # File 2: main.py
    main = tmp_path / "main.py"
    main.write_text('''
from utils import helper

def process():
    """Main processing function."""
    result = helper()
    return result * 2
''')

    return tmp_path


@pytest.mark.asyncio
async def test_call_graph_extraction(sample_project, mock_store):
    """Test that call graph correctly identifies callers/callees."""
    # Index the files first
    # ... setup mock_store with nodes ...

    builder = CallGraphBuilder(store=mock_store, project_root=sample_project)
    graph = await builder.build()

    # Verify relationships
    utils_helper_id = "node:utils.py:helper"
    utils_another_id = "node:utils.py:another_helper"
    main_process_id = "node:main.py:process"

    # helper is called by another_helper and process
    assert utils_another_id in graph[utils_helper_id]["callers"]
    assert main_process_id in graph[utils_helper_id]["callers"]

    # another_helper calls helper
    assert utils_helper_id in graph[utils_another_id]["callees"]

    # process calls helper
    assert utils_helper_id in graph[main_process_id]["callees"]
```

---

## 5. Phase 3: Complexity Metrics

**Goal**: Compute cyclomatic complexity for each function.

### 5.1 Create Complexity Analyzer

**File**: `src/remora/hub/complexity.py` (NEW)

```python
"""
src/remora/hub/complexity.py

Cyclomatic complexity calculation for Python functions.
"""

from __future__ import annotations

import ast
from pathlib import Path


def calculate_complexity(source: str) -> int:
    """
    Calculate cyclomatic complexity of a Python function/method.

    Complexity = 1 + number of decision points

    Decision points:
    - if, elif
    - for, while
    - except
    - and, or (boolean operators)
    - conditional expressions (ternary)
    - comprehension filters (if in list/dict/set comp)
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 1  # Unparseable = base complexity

    complexity = 1  # Base complexity

    for node in ast.walk(tree):
        # Control flow statements
        if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
            complexity += 1

        # elif counts as additional branch
        elif isinstance(node, ast.If) and hasattr(node, 'orelse'):
            for item in node.orelse:
                if isinstance(item, ast.If):
                    complexity += 1

        # Boolean operators
        elif isinstance(node, ast.BoolOp):
            # Each 'and' or 'or' adds a decision point
            complexity += len(node.values) - 1

        # Conditional expressions (ternary)
        elif isinstance(node, ast.IfExp):
            complexity += 1

        # Comprehension filters
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for generator in node.generators:
                complexity += len(generator.ifs)

        # Assert statements (can branch on failure)
        elif isinstance(node, ast.Assert):
            complexity += 1

    return complexity


def calculate_complexity_for_node(file_path: Path, node_name: str) -> int | None:
    """
    Calculate complexity for a specific function in a file.

    Returns:
        Complexity score, or None if node not found.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    for item in ast.walk(tree):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name == node_name:
                # Extract just this function's source
                func_source = ast.get_source_segment(source, item)
                if func_source:
                    return calculate_complexity(func_source)
        elif isinstance(item, ast.ClassDef):
            if item.name == node_name:
                # For classes, sum complexity of all methods
                total = 0
                for body_item in item.body:
                    if isinstance(body_item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_source = ast.get_source_segment(source, body_item)
                        if method_source:
                            total += calculate_complexity(method_source)
                return total if total > 0 else 1

    return None
```

### 5.2 Integrate with Extract Signatures

**File**: `.grail/hub/extract_signatures.pym`

Add complexity calculation:

```python
# Add to existing script after extracting function/class data

# Near the top, add helper function
def calculate_complexity(source_lines: list[str]) -> int:
    """Calculate cyclomatic complexity."""
    source = "\n".join(source_lines)
    complexity = 1

    # Simple pattern matching (full AST not available in Grail)
    import re

    # Decision points
    patterns = [
        r'\bif\b',
        r'\belif\b',
        r'\bfor\b',
        r'\bwhile\b',
        r'\bexcept\b',
        r'\band\b',
        r'\bor\b',
        r'\bif\s+.*\s+else\s+',  # ternary
        r'\bassert\b',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, source)
        complexity += len(matches)

    return complexity


# In the function extraction section, add:
for func in functions:
    # ... existing extraction ...
    func_data["complexity"] = calculate_complexity(func_source_lines)
```

### 5.3 Update NodeState Processing

**File**: `src/remora/hub/daemon.py`

Ensure complexity is stored:

```python
async def _process_extraction_result(
    self,
    file_path: Path,
    result: dict[str, Any],
) -> None:
    for node_data in result.get("nodes", []):
        node = NodeState(
            # ... existing fields ...
            complexity=node_data.get("complexity"),  # Add this
        )
        await self._store.set(node)
```

### 5.4 Verification

**Test**: `tests/hub/test_complexity.py`

```python
import pytest
from remora.hub.complexity import calculate_complexity


def test_simple_function():
    source = '''
def simple():
    return 42
'''
    assert calculate_complexity(source) == 1


def test_if_statement():
    source = '''
def with_if(x):
    if x > 0:
        return "positive"
    return "non-positive"
'''
    assert calculate_complexity(source) == 2


def test_if_elif_else():
    source = '''
def classify(x):
    if x > 0:
        return "positive"
    elif x < 0:
        return "negative"
    else:
        return "zero"
'''
    assert calculate_complexity(source) == 3


def test_loop_and_condition():
    source = '''
def process(items):
    for item in items:
        if item.valid:
            yield item
'''
    assert calculate_complexity(source) == 3  # 1 + for + if


def test_boolean_operators():
    source = '''
def check(a, b, c):
    if a and b or c:
        return True
    return False
'''
    assert calculate_complexity(source) == 4  # 1 + if + and + or


def test_comprehension_with_filter():
    source = '''
def filter_even(items):
    return [x for x in items if x % 2 == 0]
'''
    assert calculate_complexity(source) == 2  # 1 + if in comprehension
```

---

## 6. Phase 4: Import Analysis

**Goal**: Populate the `imports` field for each node.

### 6.1 Create Import Analyzer

**File**: `src/remora/hub/imports.py` (NEW)

```python
"""
src/remora/hub/imports.py

Import extraction for Python files.
"""

from __future__ import annotations

import ast
from pathlib import Path


def extract_imports(file_path: Path) -> list[str]:
    """
    Extract all imports from a Python file.

    Returns:
        List of import strings (e.g., ["os", "pathlib.Path", "typing.TYPE_CHECKING"])
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if module:
                    imports.append(f"{module}.{alias.name}")
                else:
                    imports.append(alias.name)

    return sorted(set(imports))


def extract_node_imports(file_path: Path, node_name: str) -> list[str]:
    """
    Extract imports used by a specific function/class.

    This is more precise: only returns imports that are actually
    referenced within the node's body.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    # First, get all imports in the file
    file_imports = {}  # name -> full import path
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                file_imports[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local_name = alias.asname or alias.name
                if module:
                    file_imports[local_name] = f"{module}.{alias.name}"
                else:
                    file_imports[local_name] = alias.name

    # Find the target node
    target_node = None
    for item in ast.walk(tree):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if item.name == node_name:
                target_node = item
                break

    if target_node is None:
        return []

    # Find all names used in the node
    used_names: set[str] = set()
    for child in ast.walk(target_node):
        if isinstance(child, ast.Name):
            used_names.add(child.id)
        elif isinstance(child, ast.Attribute):
            # Get the root name of attribute chains
            current = child
            while isinstance(current, ast.Attribute):
                current = current.value
            if isinstance(current, ast.Name):
                used_names.add(current.id)

    # Match used names to imports
    node_imports = []
    for name in used_names:
        if name in file_imports:
            node_imports.append(file_imports[name])

    return sorted(set(node_imports))
```

### 6.2 Integrate with Indexing

**File**: `src/remora/hub/indexer.py`

Update `index_file_simple` to include imports:

```python
from remora.hub.imports import extract_node_imports

def index_file_simple(
    file_path: Path,
    store: NodeStateStore,
) -> list[str]:
    # ... existing code ...

    for node in functions + classes:
        # ... existing extraction ...

        # Add import extraction
        node_imports = extract_node_imports(file_path, node.name)

        node_state = NodeState(
            # ... existing fields ...
            imports=node_imports,  # Add this
        )
        # ...
```

### 6.3 Verification

**Test**: `tests/hub/test_imports.py`

```python
import pytest
from pathlib import Path
from remora.hub.imports import extract_imports, extract_node_imports


def test_extract_imports(tmp_path):
    source = '''
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

def foo():
    pass
'''
    file = tmp_path / "test.py"
    file.write_text(source)

    imports = extract_imports(file)
    assert "os" in imports
    assert "sys" in imports
    assert "pathlib.Path" in imports
    assert "typing.TYPE_CHECKING" in imports
    assert "typing.Optional" in imports


def test_extract_node_imports(tmp_path):
    source = '''
import os
from pathlib import Path
from typing import Optional

def uses_path():
    return Path.cwd()

def uses_os():
    return os.getcwd()

def uses_nothing():
    return 42
'''
    file = tmp_path / "test.py"
    file.write_text(source)

    # uses_path should only have pathlib.Path
    imports = extract_node_imports(file, "uses_path")
    assert imports == ["pathlib.Path"]

    # uses_os should only have os
    imports = extract_node_imports(file, "uses_os")
    assert imports == ["os"]

    # uses_nothing should have no imports
    imports = extract_node_imports(file, "uses_nothing")
    assert imports == []
```

---

## 7. Phase 5: Test Discovery

**Goal**: Populate `related_tests` field by finding tests that exercise each node.

### 7.1 Create Test Discovery Module

**File**: `src/remora/hub/test_discovery.py` (NEW)

```python
"""
src/remora/hub/test_discovery.py

Discover which tests exercise which code nodes.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.hub.store import NodeStateStore


def is_test_file(path: Path) -> bool:
    """Check if a file is a test file."""
    name = path.name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "/tests/" in str(path)
        or "/test/" in str(path)
    )


def extract_test_targets(file_path: Path) -> dict[str, list[str]]:
    """
    Extract which functions/classes each test function targets.

    Returns:
        Dict mapping test_node_id -> list of target names
    """
    if not is_test_file(file_path):
        return {}

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return {}

    results: dict[str, list[str]] = {}

    # Find all test functions
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                test_node_id = f"node:{file_path}:{node.name}"
                targets = _extract_targets_from_test(node, source)
                results[test_node_id] = targets

    return results


def _extract_targets_from_test(test_func: ast.FunctionDef, source: str) -> list[str]:
    """Extract target function/class names from a test function."""
    targets: set[str] = set()

    # Strategy 1: Parse function name (test_foo tests foo)
    if test_func.name.startswith("test_"):
        potential_target = test_func.name[5:]  # Remove "test_" prefix
        if potential_target:
            targets.add(potential_target)

    # Strategy 2: Look for function calls in the test body
    for node in ast.walk(test_func):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                # Direct call: foo()
                targets.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                # Method call: obj.method()
                targets.add(node.func.attr)

    # Strategy 3: Look for imports used in the test
    # (Already covered by call extraction)

    # Filter out common test utilities
    test_utilities = {
        "assert", "assertEqual", "assertTrue", "assertFalse",
        "assertRaises", "assertIsNone", "assertIsNotNone",
        "patch", "Mock", "MagicMock", "fixture",
        "pytest", "mark", "parametrize",
    }
    targets -= test_utilities

    return sorted(targets)


async def update_test_relationships(
    store: "NodeStateStore",
    project_root: Path,
) -> int:
    """
    Scan test files and update related_tests for all nodes.

    Returns:
        Number of nodes updated.
    """
    # Step 1: Build name -> node_id index
    name_to_ids: dict[str, list[str]] = {}
    all_nodes = await store.list_all_nodes()

    for node_id in all_nodes:
        node = await store.get(node_id)
        if node:
            name = node.node_name
            if name not in name_to_ids:
                name_to_ids[name] = []
            name_to_ids[name].append(node_id)

    # Step 2: Scan all test files
    test_files = list(project_root.rglob("test_*.py"))
    test_files.extend(project_root.rglob("*_test.py"))

    # node_id -> list of test node IDs
    node_to_tests: dict[str, list[str]] = {nid: [] for nid in all_nodes}

    for test_file in test_files:
        test_targets = extract_test_targets(test_file)

        for test_node_id, targets in test_targets.items():
            for target_name in targets:
                target_ids = name_to_ids.get(target_name, [])
                for target_id in target_ids:
                    if test_node_id not in node_to_tests[target_id]:
                        node_to_tests[target_id].append(test_node_id)

    # Step 3: Update nodes
    updated = 0
    for node_id, test_ids in node_to_tests.items():
        node = await store.get(node_id)
        if node is None:
            continue

        new_related_tests = test_ids if test_ids else None
        if node.related_tests != new_related_tests:
            node.related_tests = new_related_tests
            await store.set(node)
            updated += 1

    return updated
```

### 7.2 Integrate with HubDaemon

**File**: `src/remora/hub/daemon.py`

Add test discovery after call graph analysis:

```python
from remora.hub.test_discovery import update_test_relationships

class HubDaemon:
    async def _cold_start_index(self) -> None:
        # ... existing indexing code ...

        # Cross-file analysis
        if self._config and self._config.enable_cross_file_analysis:
            logger.info("Running cross-file call graph analysis...")
            updated = await update_call_graph(self._store, self._project_root)
            logger.info(f"Call graph analysis complete: {updated} nodes updated")

            logger.info("Running test discovery...")
            updated = await update_test_relationships(self._store, self._project_root)
            logger.info(f"Test discovery complete: {updated} nodes updated")
```

### 7.3 Verification

**Test**: `tests/hub/test_test_discovery.py`

```python
import pytest
from pathlib import Path
from remora.hub.test_discovery import extract_test_targets, is_test_file


def test_is_test_file():
    assert is_test_file(Path("test_foo.py"))
    assert is_test_file(Path("foo_test.py"))
    assert is_test_file(Path("tests/test_bar.py"))
    assert not is_test_file(Path("foo.py"))
    assert not is_test_file(Path("testing.py"))


def test_extract_test_targets(tmp_path):
    source = '''
from mymodule import calculate, validate

def test_calculate():
    result = calculate(1, 2)
    assert result == 3

def test_validate_success():
    assert validate("good") is True

def test_complex():
    x = calculate(1, 2)
    y = validate(str(x))
    assert y
'''
    test_file = tmp_path / "test_mymodule.py"
    test_file.write_text(source)

    targets = extract_test_targets(test_file)

    # test_calculate should target "calculate"
    test_calc_id = f"node:{test_file}:test_calculate"
    assert "calculate" in targets[test_calc_id]

    # test_validate_success should target "validate"
    test_val_id = f"node:{test_file}:test_validate_success"
    assert "validate" in targets[test_val_id]

    # test_complex should target both
    test_complex_id = f"node:{test_file}:test_complex"
    assert "calculate" in targets[test_complex_id]
    assert "validate" in targets[test_complex_id]
```

---

## 8. Phase 6: Enhanced Testing

**Goal**: Add comprehensive tests for daemon lifecycle, stress testing, and edge cases.

### 8.1 Daemon Lifecycle Tests

**File**: `tests/hub/test_daemon_lifecycle.py` (NEW)

```python
"""
tests/hub/test_daemon_lifecycle.py

Comprehensive daemon lifecycle testing.
"""

import asyncio
import pytest
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from remora.hub.daemon import HubDaemon
from remora.hub.models import HubStatus


@pytest.fixture
def project_with_files(tmp_path):
    """Create a project with multiple Python files."""
    src = tmp_path / "src"
    src.mkdir()

    (src / "main.py").write_text('''
def main():
    """Entry point."""
    return 0
''')

    (src / "utils.py").write_text('''
def helper():
    """A helper function."""
    return 42
''')

    (src / "models.py").write_text('''
class User:
    """User model."""
    def __init__(self, name):
        self.name = name
''')

    return tmp_path


@pytest.mark.asyncio
async def test_daemon_cold_start(project_with_files, mock_grail_executor):
    """Test daemon indexes all files on cold start."""
    daemon = HubDaemon(
        project_root=project_with_files,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    # Run for a short time then stop
    async def run_briefly():
        task = asyncio.create_task(daemon.run())
        await asyncio.sleep(0.5)
        daemon._shutdown_event.set()
        await task

    await run_briefly()

    # Verify files were indexed
    status = await daemon._store.get_status()
    assert status is not None
    assert status.indexed_files >= 3
    assert status.indexed_nodes >= 3


@pytest.mark.asyncio
async def test_daemon_graceful_shutdown(project_with_files, mock_grail_executor):
    """Test daemon shuts down gracefully on SIGTERM."""
    daemon = HubDaemon(
        project_root=project_with_files,
        standalone=True,  # Will set up signal handlers
        grail_executor=mock_grail_executor,
    )

    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(0.2)

    # Simulate SIGTERM
    daemon._shutdown_event.set()
    await asyncio.wait_for(task, timeout=5.0)

    # Verify clean shutdown
    status = await daemon._store.get_status()
    assert status is None or status.running is False


@pytest.mark.asyncio
async def test_daemon_file_change_handling(project_with_files, mock_grail_executor):
    """Test daemon processes file changes correctly."""
    daemon = HubDaemon(
        project_root=project_with_files,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(0.5)  # Let cold start complete

    # Modify a file
    (project_with_files / "src" / "main.py").write_text('''
def main():
    """Updated entry point."""
    return 1

def new_function():
    """A new function."""
    pass
''')

    # Wait for change to be processed
    await asyncio.sleep(1.0)

    daemon._shutdown_event.set()
    await task

    # Verify new function was indexed
    all_nodes = await daemon._store.list_all_nodes()
    node_names = [n.split(":")[-1] for n in all_nodes]
    assert "new_function" in node_names


@pytest.mark.asyncio
async def test_daemon_restart_recovery(project_with_files, mock_grail_executor):
    """Test daemon recovers state correctly on restart."""
    # First run
    daemon1 = HubDaemon(
        project_root=project_with_files,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    task1 = asyncio.create_task(daemon1.run())
    await asyncio.sleep(0.5)
    daemon1._shutdown_event.set()
    await task1

    initial_nodes = await daemon1._store.list_all_nodes()

    # Second run (restart)
    daemon2 = HubDaemon(
        project_root=project_with_files,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    task2 = asyncio.create_task(daemon2.run())
    await asyncio.sleep(0.3)
    daemon2._shutdown_event.set()
    await task2

    # Verify state persisted
    recovered_nodes = await daemon2._store.list_all_nodes()
    assert set(recovered_nodes) == set(initial_nodes)
```

### 8.2 Stress Tests

**File**: `tests/hub/test_stress.py` (NEW)

```python
"""
tests/hub/test_stress.py

Stress testing for Hub daemon with large codebases.
"""

import asyncio
import pytest
from pathlib import Path

from remora.hub.daemon import HubDaemon


@pytest.fixture
def large_project(tmp_path):
    """Create a project with many files."""
    src = tmp_path / "src"
    src.mkdir()

    # Create 100 modules with 5 functions each
    for i in range(100):
        module = src / f"module_{i:03d}.py"
        functions = "\n\n".join([
            f'''
def function_{j}():
    """Function {j} in module {i}."""
    return {i * 100 + j}
'''
            for j in range(5)
        ])
        module.write_text(functions)

    return tmp_path


@pytest.mark.asyncio
@pytest.mark.slow
async def test_large_codebase_indexing(large_project, mock_grail_executor):
    """Test daemon can index a large codebase efficiently."""
    daemon = HubDaemon(
        project_root=large_project,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    import time
    start = time.monotonic()

    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(10.0)  # Allow time for indexing
    daemon._shutdown_event.set()
    await task

    elapsed = time.monotonic() - start

    # Verify all nodes indexed
    status = await daemon._store.get_status()
    assert status.indexed_files == 100
    assert status.indexed_nodes == 500  # 100 files * 5 functions

    # Performance assertion: should index in reasonable time
    assert elapsed < 60.0, f"Indexing took {elapsed:.1f}s, expected < 60s"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_concurrent_file_changes(large_project, mock_grail_executor):
    """Test daemon handles many concurrent file changes."""
    daemon = HubDaemon(
        project_root=large_project,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(5.0)  # Initial indexing

    # Modify 20 files concurrently
    async def modify_file(i):
        path = large_project / "src" / f"module_{i:03d}.py"
        content = path.read_text()
        path.write_text(content + f"\n\ndef added_func_{i}(): pass\n")

    await asyncio.gather(*[modify_file(i) for i in range(20)])

    # Wait for processing
    await asyncio.sleep(3.0)

    daemon._shutdown_event.set()
    await task

    # Verify new functions indexed
    all_nodes = await daemon._store.list_all_nodes()
    added_funcs = [n for n in all_nodes if "added_func" in n]
    assert len(added_funcs) == 20
```

### 8.3 Edge Case Tests

**File**: `tests/hub/test_edge_cases.py` (NEW)

```python
"""
tests/hub/test_edge_cases.py

Edge case handling for Hub daemon.
"""

import pytest
from pathlib import Path

from remora.hub.indexer import index_file_simple


def test_syntax_error_file(tmp_path, mock_store):
    """Test handling of files with syntax errors."""
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def broken(\n")  # Syntax error

    # Should not raise, should return empty
    indexed = index_file_simple(bad_file, mock_store)
    assert indexed == []


def test_binary_file(tmp_path, mock_store):
    """Test handling of binary files."""
    binary_file = tmp_path / "binary.py"
    binary_file.write_bytes(b"\x00\x01\x02\x03")

    indexed = index_file_simple(binary_file, mock_store)
    assert indexed == []


def test_empty_file(tmp_path, mock_store):
    """Test handling of empty files."""
    empty_file = tmp_path / "empty.py"
    empty_file.write_text("")

    indexed = index_file_simple(empty_file, mock_store)
    assert indexed == []


def test_very_long_function(tmp_path, mock_store):
    """Test handling of very long functions."""
    long_func = tmp_path / "long.py"
    body = "\n".join([f"    x = {i}" for i in range(1000)])
    long_func.write_text(f"def very_long():\n{body}\n    return x\n")

    indexed = index_file_simple(long_func, mock_store)
    assert len(indexed) == 1
    # Should handle without memory issues


def test_unicode_content(tmp_path, mock_store):
    """Test handling of Unicode in source code."""
    unicode_file = tmp_path / "unicode.py"
    unicode_file.write_text('''
def greeting():
    """Returns a greeting."""
    return "Hello, World!"
''', encoding="utf-8")

    indexed = index_file_simple(unicode_file, mock_store)
    assert len(indexed) == 1


def test_nested_functions(tmp_path, mock_store):
    """Test handling of nested function definitions."""
    nested_file = tmp_path / "nested.py"
    nested_file.write_text('''
def outer():
    """Outer function."""
    def inner():
        """Inner function."""
        return 42
    return inner
''')

    indexed = index_file_simple(nested_file, mock_store)
    # Should index outer, behavior for inner is implementation-defined
    assert "outer" in indexed[0] if indexed else True
```

---

## 9. Phase 7: Observability

**Goal**: Add metrics, logging, and monitoring capabilities.

### 9.1 Hub Metrics Module

**File**: `src/remora/hub/metrics.py` (NEW)

```python
"""
src/remora/hub/metrics.py

Metrics collection for Hub daemon observability.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HubMetrics:
    """Collects and exposes Hub daemon metrics."""

    # Counters
    files_indexed: int = 0
    nodes_extracted: int = 0
    files_failed: int = 0
    file_changes_processed: int = 0

    # Timing (seconds)
    total_index_time: float = 0.0
    last_index_duration: float = 0.0
    cold_start_duration: float = 0.0

    # Gauges
    current_node_count: int = 0
    current_file_count: int = 0
    workspace_size_bytes: int = 0

    # Internal
    _start_times: dict[str, float] = field(default_factory=dict)

    def start_timer(self, name: str) -> None:
        """Start a named timer."""
        self._start_times[name] = time.monotonic()

    def stop_timer(self, name: str) -> float:
        """Stop a timer and return elapsed seconds."""
        if name not in self._start_times:
            return 0.0
        elapsed = time.monotonic() - self._start_times.pop(name)
        return elapsed

    def record_file_indexed(self, nodes: int, duration: float) -> None:
        """Record a successful file index."""
        self.files_indexed += 1
        self.nodes_extracted += nodes
        self.total_index_time += duration
        self.last_index_duration = duration

    def record_file_failed(self) -> None:
        """Record a failed file index."""
        self.files_failed += 1

    def record_file_change(self) -> None:
        """Record a file change event processed."""
        self.file_changes_processed += 1

    def to_dict(self) -> dict[str, Any]:
        """Export metrics as dictionary."""
        return {
            "counters": {
                "files_indexed": self.files_indexed,
                "nodes_extracted": self.nodes_extracted,
                "files_failed": self.files_failed,
                "file_changes_processed": self.file_changes_processed,
            },
            "timing": {
                "total_index_time_seconds": round(self.total_index_time, 3),
                "last_index_duration_seconds": round(self.last_index_duration, 3),
                "cold_start_duration_seconds": round(self.cold_start_duration, 3),
                "avg_index_time_seconds": round(
                    self.total_index_time / max(self.files_indexed, 1), 3
                ),
            },
            "gauges": {
                "current_node_count": self.current_node_count,
                "current_file_count": self.current_file_count,
                "workspace_size_bytes": self.workspace_size_bytes,
            },
        }


# Global metrics instance
_metrics: HubMetrics | None = None


def get_metrics() -> HubMetrics:
    """Get or create the global metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = HubMetrics()
    return _metrics


def reset_metrics() -> None:
    """Reset metrics (for testing)."""
    global _metrics
    _metrics = None
```

### 9.2 Integrate Metrics with Daemon

**File**: `src/remora/hub/daemon.py`

Add metrics collection:

```python
from remora.hub.metrics import get_metrics

class HubDaemon:
    def __init__(self, ...):
        # ... existing init ...
        self._metrics = get_metrics()

    async def _cold_start_index(self) -> None:
        self._metrics.start_timer("cold_start")

        # ... existing indexing ...

        self._metrics.cold_start_duration = self._metrics.stop_timer("cold_start")

    async def _index_file(self, file_path: Path) -> None:
        self._metrics.start_timer(f"index:{file_path}")

        try:
            # ... existing indexing ...
            nodes = len(result.get("nodes", []))
            duration = self._metrics.stop_timer(f"index:{file_path}")
            self._metrics.record_file_indexed(nodes, duration)

        except Exception:
            self._metrics.stop_timer(f"index:{file_path}")
            self._metrics.record_file_failed()
            raise

    async def _handle_file_change(self, ...):
        self._metrics.record_file_change()
        # ... existing handling ...
```

### 9.3 Add Metrics CLI Command

**File**: `src/remora/hub/cli.py`

Add metrics subcommand:

```python
@cli.command()
def metrics():
    """Show Hub daemon metrics."""
    from remora.hub.metrics import get_metrics

    metrics = get_metrics()
    data = metrics.to_dict()

    click.echo("=== Hub Metrics ===")
    click.echo()
    click.echo("Counters:")
    for key, value in data["counters"].items():
        click.echo(f"  {key}: {value}")

    click.echo()
    click.echo("Timing:")
    for key, value in data["timing"].items():
        click.echo(f"  {key}: {value}")

    click.echo()
    click.echo("Gauges:")
    for key, value in data["gauges"].items():
        click.echo(f"  {key}: {value}")
```

### 9.4 Enhanced Logging

**File**: `src/remora/hub/daemon.py`

Add structured logging:

```python
import logging
import json

logger = logging.getLogger("remora.hub")

class HubDaemon:
    def _log_index_event(
        self,
        file_path: Path,
        nodes: int,
        duration: float,
        success: bool,
    ) -> None:
        """Emit structured log for indexing events."""
        event = {
            "event": "file_indexed",
            "file": str(file_path),
            "nodes": nodes,
            "duration_ms": round(duration * 1000, 2),
            "success": success,
        }
        logger.info(json.dumps(event))
```

---

## 10. Verification Checklist

Use this checklist to verify Hub completion:

### Configuration (Phase 1)

- [ ] `HubConfig` class added to `config.py`
- [ ] `hub:` section documented in `remora.yaml`
- [ ] `hub_mode` field removed (replaced by `hub.mode`)
- [ ] HubClient uses config values instead of hardcoded constants
- [ ] Unit tests pass for config loading

### Cross-File Analysis (Phase 2)

- [ ] `call_graph.py` module created
- [ ] `CallGraphBuilder` extracts call relationships
- [ ] HubDaemon runs call graph analysis after cold start
- [ ] `callers` and `callees` fields populated
- [ ] Integration tests verify relationships

### Complexity Metrics (Phase 3)

- [ ] `complexity.py` module created
- [ ] `calculate_complexity()` handles all decision points
- [ ] Grail script updated to compute complexity
- [ ] `complexity` field populated in NodeState
- [ ] Unit tests cover edge cases

### Import Analysis (Phase 4)

- [ ] `imports.py` module created
- [ ] `extract_imports()` handles all import forms
- [ ] `extract_node_imports()` filters to used imports
- [ ] `imports` field populated in NodeState
- [ ] Unit tests verify extraction

### Test Discovery (Phase 5)

- [ ] `test_discovery.py` module created
- [ ] `is_test_file()` identifies test files
- [ ] `extract_test_targets()` finds test targets
- [ ] HubDaemon runs test discovery
- [ ] `related_tests` field populated
- [ ] Integration tests verify relationships

### Enhanced Testing (Phase 6)

- [ ] Daemon lifecycle tests added
- [ ] Stress tests with large codebase
- [ ] Edge case tests (syntax errors, binary, unicode)
- [ ] All tests pass in CI

### Observability (Phase 7)

- [ ] `metrics.py` module created
- [ ] `HubMetrics` collects counters and timing
- [ ] Daemon integrates metrics collection
- [ ] `remora-hub metrics` command works
- [ ] Structured logging implemented

### Final Verification

- [ ] `remora-hub start` starts daemon successfully
- [ ] `remora-hub status` shows indexed counts
- [ ] Agents receive populated `hub_context`
- [ ] No regressions in existing tests
- [ ] Documentation updated

---

## Appendix A: FSdantic Reference

The Hub uses FSdantic for persistence. Key patterns:

```python
# Opening a workspace
import fsdantic
workspace = fsdantic.Workspace(path=".remora/hub.db")

# Writing a record
from remora.hub.models import NodeState
node = NodeState(key="node:file.py:func", ...)
await workspace.set(node.key, node.model_dump())

# Reading a record
data = await workspace.get("node:file.py:func")
if data:
    node = NodeState.model_validate(data)

# Listing keys by prefix
keys = await workspace.list_keys(prefix="node:")

# Closing
await workspace.close()
```

---

## Appendix B: File Change Event Types

The watcher emits these change types:

| Event | Meaning | Hub Action |
|-------|---------|------------|
| `added` | New file created | Index file |
| `modified` | File content changed | Re-index file |
| `deleted` | File removed | Remove nodes |

---

*End of Hub Completion Guide*
