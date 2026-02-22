# Remora Refactoring Guide

## Overview
This document provides a detailed, step-by-step technical guide for executing the refactoring plan outlined in `REFACTORING_PLAN.md`. The tasks have been ordered logically to minimize rework, starting from low-level infrastructure fixes that unblock tests, moving up to architectural restructuring, and finishing with performance and cleanup tasks.

---

## Phase 1: Infrastructure & Testing (Highest ROI)

### Task 1.1: Implement `run_json_command` External
The existing sandboxed Grail scripts (`.pym` files) use brittle string parsing to interpret JSON output from CLI tools. We must move this parsing out of the sandbox to the host environment.

**File to modify:** `src/remora/externals.py`

**Action:**
Add a new external function that accepts a command, runs it, captures JSON stdout, parses it using the standard `json` module, and returns the resulting dictionary or list. Note that Grail can pass dictionaries and lists across the sandbox boundary natively.

**Code Snippet:**
```python
# In src/remora/externals.py add:
import json
import asyncio

# Inside create_remora_externals():
    async def run_json_command(cmd: str, args: list[str]) -> dict[str, Any] | list[Any]:
        """Run a command and parse its stdout as JSON."""
        from cairn.runtime.external_functions import _run_command  # Or however the base run_command is implemented
        # Note: You may need to adapt this depending on how cairn exposes subprocess execution
        proc = await asyncio.create_subprocess_exec(
            cmd,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        
        try:
            return json.loads(stdout.decode('utf-8'))
        except json.JSONDecodeError:
            # Fallback for structured error reporting
            return {
                "error": "Failed to parse JSON", 
                "stdout": stdout.decode('utf-8'), 
                "stderr": stderr.decode('utf-8'),
                "exit_code": proc.returncode
            }

    base_externals["run_json_command"] = run_json_command
```

### Task 1.2: Refactor `.pym` Scripts to use `run_json_command`
Replace the hand-rolled string parsing inside the `.pym` tool scripts.

**Files to modify:** `agents/lint/tools/run_linter.pym` (and any other relevant tools)

**Action:**
Delete `_split_json_objects`, `_find_value_start`, `_parse_string`, `_parse_number`, `_get_string`, `_get_int`, and `_extract_code`. Replace the `run_command` call with `run_json_command` where appropriate.

**Code Snippet:**
```python
# In agents/lint/tools/run_linter.pym:
from typing import Any
from grail import external

@external
async def run_json_command(cmd: str, args: list[str]) -> Any:
    ...

# Inside the main logic:
command_args = ["check", "--output-format", "json", "--select", "E,W,F", target_file]
if not check_only:
    # Ruff format json doesn't love --fix in the same command always, adapt if needed
    command_args.insert(1, "--fix") 

# This now returns a parsed list or dict natively!
issues_raw = await run_json_command(cmd="ruff", args=command_args)

# If it returns a dict indicating error from our external wrapper
if isinstance(issues_raw, dict) and "error" in issues_raw:
     # Handle error
     pass

# Otherwise, it's a list of issue dicts directly from ruff
issues = []
for issue_data in issues_raw:
    issues.append({
        "code": issue_data.get("code"),
        "line": issue_data.get("location", {}).get("row"),
        "col": issue_data.get("location", {}).get("column"),
        "message": issue_data.get("message"),
        "fixable": issue_data.get("fix") is not None
    })
```

---

## Phase 2: Kernel Runner Error Handling

### Task 2.1: Granular Exception Classes
Create specific exceptions so the Orchestrator can differentiate between types of failures.

**File to modify:** `src/remora/errors.py`

**Action:**
Add subclasses of `ExecutionError`.

**Code Snippet:**
```python
# In src/remora/errors.py
class KernelTimeoutError(ExecutionError):
    """Raised when the LLM or tool execution times out."""
    pass

class ToolExecutionError(ExecutionError):
    """Raised when a specific tool fails catastrophically."""
    pass

class ContextLengthError(ExecutionError):
    """Raised when the prompt exceeds the model's context window."""
    pass
```

### Task 2.2: Implement Granular Catching
Ensure `KernelRunner` doesn't just swallow every exception into a generic failure.

**File to modify:** `src/remora/kernel_runner.py`

**Action:**
In `KernelRunner.run()`, add granular `except` blocks. You will need to inspect the exceptions thrown by `structured_agents.AgentKernel.run()` to map them correctly.

**Code Snippet:**
```python
# In src/remora/kernel_runner.py -> KernelRunner.run()
        try:
            result = await self._kernel.run(...)
            return self._format_result(result)
        # Assuming structured_agents raises these or similar types
        except TimeoutError as exc:
            logger.exception("Timeout during KernelRunner execution for %s", self.node.node_id)
            return AgentResult(
                status=AgentStatus.FAILED,
                workspace_id=self.ctx.agent_id,
                changed_files=[],
                summary="Execution timed out.",
                error=str(exc),
                details={"error_type": "TimeoutError"}
            )
        except Exception as exc:
            logger.exception("KernelRunner failed for %s", self.node.node_id)
            return AgentResult(...)
```

---

## Phase 3: Architectural Layer Separation

### Task 3.1: Extract `ResultPresenter`
Move the result formatting logic out of `analyzer.py`.

**Action:**
1. Create `src/remora/presenter.py`.
2. Move the entire `ResultPresenter` class from `analyzer.py` into this new file.
3. Update imports in `cli.py` or wherever `ResultPresenter` is instantiated to import from `remora.presenter`.

### Task 3.2: Extract Workspace Management
Move the Cairn merging logic from `analyzer.py`.

**Action:**
1. Create `src/remora/workspace_bridge.py`.
2. Move `_workspace_db_path`, `_workspace_root`, `_project_root`, `_write_workspace_file`, `_remove_workspace_dir`, `_cairn_merge`, and `_cairn_discard` out of `RemoraAnalyzer`.
3. Encapsulate these in a class, e.g., `CairnWorkspaceBridge`.

**Code Snippet:**
```python
# In src/remora/workspace_bridge.py
from pathlib import Path
import asyncio
import shutil
from cairn.runtime.workspace_manager import WorkspaceManager

class CairnWorkspaceBridge:
    def __init__(self, workspace_manager: WorkspaceManager, project_root: Path, cache_root: Path):
        self.workspace_manager = workspace_manager
        self.project_root = project_root
        self.cache_root = cache_root

    def _workspace_db_path(self, workspace_id: str) -> Path:
        return self.cache_root / "workspaces" / workspace_id / "workspace.db"
    
    # ... move other methods here
    
    async def merge(self, workspace_id: str) -> None:
       # contents of former _cairn_merge
```

### Task 3.3: Refactor `RemoraAnalyzer`
Update `analyzer.py` to use the new classes, drastically reducing its line count.

**Code Snippet:**
```python
# In src/remora/analyzer.py
from remora.workspace_bridge import CairnWorkspaceBridge

class RemoraAnalyzer:
    def __init__(...):
        # ...
        cache_root = self.config.cairn.home or (Path.home() / ".cache" / "remora")
        self._bridge = CairnWorkspaceBridge(
            workspace_manager=self._workspace_manager,
            project_root=self.config.agents_dir.parent.resolve(),
            cache_root=cache_root
        )

    async def accept(self, node_id: str | None = None, operation: str | None = None) -> None:
        targets = self._filter_workspaces(node_id, operation, WorkspaceState.PENDING)
        for key, info in targets:
            await self._bridge.merge(info.workspace_id) # Uses bridge
            # ...
```

---

## Phase 4: Performance & Integration

### Task 4.1: Parallel Tree-sitter Discovery
Speed up parsing for large repositories.

**File to modify:** `src/remora/discovery/discoverer.py`

**Action:**
Use `asyncio.to_thread` or `concurrent.futures.ThreadPoolExecutor` to process files concurrently. Because Tree-sitter parses in C, it releases the GIL effectively.

**Code Snippet:**
```python
# In src/remora/discovery/discoverer.py -> TreeSitterDiscoverer.discover()
import concurrent.futures

    def discover(self) -> list[CSTNode]:
        # ... validation ...
        py_files = self._collect_files()
        all_nodes: list[CSTNode] = []
        
        def _parse_single(file_path):
            try:
                tree, source_bytes = self._parser.parse_file(file_path)
                return self._extractor.extract(file_path, tree, source_bytes, queries)
            except DiscoveryError:
                return []
                
        with concurrent.futures.ThreadPoolExecutor() as executor:
            results_generator = executor.map(_parse_single, py_files)
            
            for nodes in results_generator:
               all_nodes.extend(nodes)
               
        all_nodes.sort(...)
        return all_nodes
```

### Task 4.2: In-Process Hub Daemon Option
Integrate the Hub watcher natively into the orchestrator so it doesn't require a separate terminal process.

**Files to modify:** `src/remora/config.py`, `src/remora/orchestrator.py`, `src/remora/hub/daemon.py`

**Action:**
1. Add `hub_mode: Literal["in-process", "daemon", "disabled"] = "disabled"` to `RemoraConfig`.
2. Extract the loop logic in `hub/daemon.py` so it can be run as an `asyncio.Task`.
3. In `orchestrator.py` `__aenter__`, if `hub_mode == "in-process"`, spawn the Hub task. Cancel it in `__aexit__`.

---

## Phase 5: Cleanup & Security

### Task 5.1: Subagent Deprecation
Remove dead code.

**Action:**
Delete `src/remora/subagent.py` and run tests to ensure no recursive import failures occur. Search the `docs/` folder to remove any residual references.
