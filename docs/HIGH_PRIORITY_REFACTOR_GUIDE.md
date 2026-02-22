# Remora High Priority Refactor Guide

This guide provides step-by-step instructions for junior developers to complete the **High Priority** refactoring tasks identified in the Remora code review. Our goal is to achieve the cleanest, most elegant architecture possible. **Backwards compatibility is not a concern.**

Please follow this guide sequentially. After completing each step, ensure the accompanying testing instructions are fully satisfied before returning to the next step.

---

## Step 1: Unify Error Handling Strategy

**Objective**: Create a unified exception hierarchy using standard error codes across the entire Remora library, and eliminate silent exception swallowing.

### 1.1 Create the Base Error Hierarchy
**File location**: `src/remora/errors.py`

Replace the standalone error code strings with a proper object-oriented hierarchy. 
Add the following base class and subclasses:

```python
# src/remora/errors.py

class RemoraError(Exception):
    """Base exception for all Remora errors."""
    code: str = "REMORA-UNKNOWN"
    recoverable: bool = False
    
    def __init__(self, message: str, code: str | None = None, recoverable: bool | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code
        if recoverable is not None:
            self.recoverable = recoverable

class ConfigurationError(RemoraError):
    code = "REMORA-CONFIG"

class DiscoveryError(RemoraError):
    code = "REMORA-DISCOVERY"

class ExecutionError(RemoraError):
    code = "REMORA-EXEC"
    recoverable = True

class SubagentError(RemoraError):
    code = "REMORA-AGENT"
```

### 1.2 Update Existing Custom Exceptions
Update the existing exception classes throughout the codebase to inherit from our new hierarchy rather than `RuntimeError`.

**1. `src/remora/config.py`**
```python
from remora.errors import ConfigurationError

class ConfigError(ConfigurationError):
    pass 
```

**2. `src/remora/discovery/models.py`**
```python
from remora.errors import DiscoveryError as BaseDiscoveryError

class DiscoveryError(BaseDiscoveryError):
    pass
```

**3. `src/remora/tool_registry.py`**
```python
from remora.errors import SubagentError

class ToolRegistryError(SubagentError):
    pass
```

**4. `src/remora/subagent.py`**
```python
from remora.errors import SubagentError as BaseSubagentError

class SubagentError(BaseSubagentError):
    pass
```

### 1.3 Fix Silent Exception Swallowing and Bare Excepts
**Objective:** Decide between bubbling up exceptions or recording them based on the context, and eliminate all `except Exception:` blocks where possible.

**Recommendation:**
*   **Core Orchestration & Discovery (`analyzer.py`, `discoverer.py`, `orchestrator.py`, `kernel_runner.py`)**: These are higher-level control flows. When an error occurs here (e.g., an agent strictly fails or a tree fails to parse), it is generally better to **record** the error in an `AgentResult` or an error collection list and allow the rest of the batch process to continue, rather than crashing the entire run. 
*   **Low-Level Utilities & Configuration (`config.py`, `tool_registry.py`, `subagent.py`, `hub/*.py`)**: These should **bubble up** `RemoraError` exceptions (like `ConfigurationError` or `SubagentError`). If the configuration is broken or a tool is invalid, the system should fail fast and loudly rather than trying to proceed with corrupted state. Let the orchestrator catch it or let it crash the CLI.

**Action Items across the codebase:**

1.  **`src/remora/kernel_runner.py`**: Find the `except Exception as exc:` block (around line 180 and 235). Stop swallowing unknowns. Record it as an `ExecutionError` in the `AgentResult`:
    ```python
            except Exception as exc:
                from remora.errors import ExecutionError
                logger.exception("KernelRunner failed for %s", self.node.node_id)
                return AgentResult(
                    status=AgentStatus.FAILED,
                    summary=f"KernelRunner failed with {type(exc).__name__}: {str(exc)}"
                )
    ```
2.  **`src/remora/orchestrator.py`**: Look at lines ~243 and ~258. The orchestrator catches `Exception` and logs it, but it needs to ensure these are captured and bubbled or recorded properly in the final `NodeResult` rather than just printing to console.
3.  **`src/remora/events.py`**: The `JsonlEventEmitter` catches flat `Exception` during json serialization (lines ~119, ~126). This should at least be narrowed down to `(TypeError, ValueError)`, and perhaps bubble up a serialization error or log vividly instead of passing silently.
4.  **`src/remora/hub/daemon.py` and `src/remora/watcher.py`**: Both contain generic `except Exception:` blocks for background tasks. It's often reasonable to catch broad exceptions in long-running watchers to prevent the daemon from crashing, but they must be logged completely with `logger.exception` and should possibly increment a failure counter.
5.  **`src/remora/context/manager.py`**: Look at `pull_hub_context` (line ~117 & ~193). The stub uses `except Exception: pass`. (See Step 3.2 for the fix).
6.  **`src/remora/discovery/query_loader.py`**: Line ~104 has a bare `except Exception as exc: raise DiscoveryError...`. Make sure this is preserving the original traceback by using `raise DiscoveryError(...) from exc`.

### 🧪 Testing for Step 1
1. **Unit Testing**: Run `uv run pytest tests/` to verify that imports and inheritance changes haven't intrinsically broken the test suite. 
2. **Verify Error Bubbling**: Temporarily insert a `raise ValueError("test error")` inside the `KernelRunner.run` loop. Verify that the system handles it via the new `ExecutionError` format or produces an `AgentResult` stating the `Execution error`, instead of silently dismissing it.

---

## Step 2: Fix Sync/Async Mismatch in Discovery

**Objective**: Ensure that synchronous tree-sitter operations do not block the `asyncio` event loop.

### 2.1 Wrap `discoverer.discover()` in `asyncio.to_thread`
**File location**: `src/remora/analyzer.py`

Modify `RemoraAnalyzer.analyze` so that the heavy tree-sitter discovery offloads to a separate thread.

**Change from:**
```python
        self._nodes = discoverer.discover()
```

**Change to:**
```python
        # Ensure we wrap the synchronous blocking call
        self._nodes = await asyncio.to_thread(discoverer.discover)
```

### 🧪 Testing for Step 2
1. **Basic Execution**: Run the analyzer via CLI `remora analyze .`. Ensure that discovery still succeeds and files are properly discovered. 
2. **Concurrency Verification**: Add an `await asyncio.sleep(1)` inside another concurrent async task while `analyze` is running on a large directory. Validate that the event loop isn't blocked by standard logging timestamps.

---

## Step 3: Complete or Remove Stubs

**Objective**: Eliminate half-implemented features from the API to clarify developer intent and avoid confusing the end user.

### 3.1 Implement Interactive Analyzer MVP
**File location**: `src/remora/analyzer.py`

The interactive mode is currently just printing a stub message. We need to implement a functional MVP. The MVP should iterate through the pending workspaces and prompt the user to accept, reject, skip, or quit.

1.  Remove the stub print `self.console.print("[yellow]Interactive mode not yet implemented...[/yellow]")` from `_display_interactive`.
2.  Implement the MVP logic in `interactive_review`. It's already mostly structured, but we need to ensure it integrates correctly with the actual `Analyzer` state.

```python
    async def interactive_review(
        self,
        analyzer: RemoraAnalyzer,
        results: AnalysisResults,
    ) -> None:
        """Run interactive review session MVP."""
        self.console.print("\n[bold]Interactive Review Mode[/bold]\n")
        self.console.print("Commands: [a]ccept, [r]eject, [s]kip, [d]iff (stub), [q]uit\n")

        for node in results.nodes:
            for op_name, result in node.operations.items():
                if result.status != AgentStatus.SUCCESS:
                    continue

                self.console.print(f"\n[cyan]{node.file_path.name}::{node.node_name}[/cyan]")
                self.console.print(f"  {op_name}: {result.summary}")

                while True:
                    choice = input("  [a/r/s/d/q]? ").lower().strip()

                    if choice == "a":
                        await analyzer.accept(node.node_id, op_name)
                        self.console.print("  [green]✓ Accepted[/green]")
                        break
                    elif choice == "r":
                        await analyzer.reject(node.node_id, op_name)
                        self.console.print("  [red]✓ Rejected[/red]")
                        break
                    elif choice == "s":
                        self.console.print("  [yellow]Skipped[/yellow]")
                        break
                    elif choice == "d":
                        self.console.print("  [dim](Diff not yet implemented, proceeding to next command prompt)[/dim]")
                        # In the future, this would print the diff and loop back to the input prompt
                    elif choice == "q":
                        return
                    else:
                        self.console.print("  [yellow]Invalid choice. Please enter a, r, s, d, or q.[/yellow]")
```

### 3.2 Fix Hub Discovery Stub & Propagate Errors
**File location**: `src/remora/context/manager.py`

The `pull_hub_context` method fails silently (`except Exception: pass`). As we prepare for the complete Hub implementation, we want to propagate these errors upwards.

**Change the `except` block to:**
```python
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Failed to pull hub context")
            # We want to bubble this error up so the system knows the hub is failing.
            # Do not swallow it.
            raise RuntimeError(f"Hub context pull failed: {e}") from e
```

### 🧪 Testing for Step 3
1. **CLI Validation**: Verify that running `remora analyze . --format interactive` fails with an explicit "Unknown format" error instead of continuing on a stub function.
2. **Mock Hub Failure**: Force `pull_hub_context` to raise an exception by changing its endpoint or mocking it to throw. Ensure a warning log prints, but doesn't fatally crash the app (since it's an optional context pull).

---

## Step 4: Add Real Integration Tests

**Objective**: Complement our mocked unit tests by adding real end-to-end integration tests that cover the CLI and workspaces without relying on `monkeypatch` for critical app flows.

### 4.1 Remove CLI Monkeypatching
**File location**: `tests/test_cli.py`

Currently, `test_cli.py` heavily relies on `monkeypatch` to bypass `load_config`, `_fetch_models`, and `load_subagent_definition`. 
This defeats the purpose of an end-to-end CLI test. 

1. Remove the `test_list_agents_outputs_table` test from `test_cli.py` completely, or completely rewrite it. 
2. Instead, create a true integration test that points the CLI to a real, albeit temporary, configuration and agent directory without patching the internal functions.

### 4.2 Write Full System Integration Tests
**File location**: `tests/integration/test_system_e2e.py` (Create this file)

Write tests that interact with the real filesystem and invoke the CLI via `CliRunner` without mocking Remora components. We will use `pytest` fixtures to set up the environment.

```python
import pytest
from pathlib import Path
from typer.testing import CliRunner
from remora.cli import app

def test_cli_analyze_e2e(tmp_path: Path):
    """End-to-End test of the CLI analyze command."""
    
    # 1. Setup real project dir
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "target.py").write_text("def hello(): pass")
    
    # 2. Setup Config File
    config_file = tmp_path / "remora.yaml"
    config_file.write_text(f"""
    agents_dir: {project_dir}
    operations:
      lint:
        enabled: true
        subagent: lint
    """, encoding="utf-8")
    
    # 3. Create a fake agent bundle so the system doesn't fail loading
    agent_dir = project_dir / "lint"
    agent_dir.mkdir()
    (agent_dir / "bundle.yaml").write_text("name: lint\nversion: 1.0", encoding="utf-8")

    # 4. Invoke the CLI
    runner = CliRunner()
    
    # We pass the custom config path via environment variable or CLI flag if supported, 
    # Otherwise set the working directory to where the config is.
    result = runner.invoke(app, ["analyze", str(project_dir), "--config", str(config_file)])
    
    # Note: Depending on whether you have a mock vLLM server running or configured in 
    # the test environment, you may expect this to fail gracefully with a connection error
    # instead of a success. The goal is to ensure the pipeline executes up to the server call.
    assert result.exit_code in (0, 1, 2) # Adjust based on expected output if server implies fail
    # assert "Total nodes: 1" in result.output
```

### 4.3 Write Workspaces Integration Test
**File location**: `tests/integration/test_workspace_ops.py` (Create this file)

Write a test that interact with the actual Cairn overlay to verify `accept` and `reject` merges.

```python
import pytest
import asyncio
from pathlib import Path
from remora.config import load_config
from remora.analyzer import RemoraAnalyzer

@pytest.mark.asyncio
async def test_real_workspace_lifecycle(tmp_path: Path):
    """Test full cycle of creating a workspace, mocking a result, and merging it over Cairn overlay to disk."""
    
    # 1. Setup real project dir
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "target.py").write_text("def hello(): pass")
    
    # 2. Setup Config
    # Assuming config allows programmatic overrides for tests
    config = load_config()
    config.agents_dir = project_dir 
    config.cairn.home = tmp_path / "cairn_home"
    
    analyzer = RemoraAnalyzer(config)
    
    # 3. Analyze 
    results = await analyzer.analyze(paths=[project_dir], operations=["lint"])
    assert results.total_nodes > 0
    
    # Verify the workspace database was actually created on disk
    workspace_id = list(analyzer._workspaces.values())[0].workspace_id
    workspace_db = analyzer._workspace_db_path(workspace_id)
    assert workspace_db.exists()
    
    # 4. Accept
    await analyzer.accept()
    
    # Workspace should be cleaned up
    assert not workspace_db.exists()
```

### 🧪 Testing for Step 4
1. **Run Integration Tests**: Run `uv run pytest tests/integration/`. 
2. **Verify Code Coverage**: Use `uv run pytest --cov=src/remora tests/integration/` to ensure the new tests hit the `analyzer.py` code paths (excluding the actual LLM call which might be stubbed at the HTTP boundary).
