# Implementation Guide for Step 9: Rewrite .pym Scripts

## Overview

This step converts all 22 `.pym` scripts from the old `@external` pattern to the new pure-function pattern with `Input()` and virtual filesystem. This implements **Idea 8** from the design document.

**Goal:** Scripts use `Input()` for data injection, return structured result dicts, and have no `@external` for file operations.

## Contract Touchpoints
- Grail `.pym` scripts must follow Grail rules (imports only from `grail`, `typing`, `__future__`).
- `Input()` declarations must match variable names and are populated via `CairnDataProvider`/Grail `files`.
- `@external` is reserved for `ask_user` or true external services.

## Done Criteria
- [ ] All `.pym` tools use `Input()` for inputs and return structured dicts.
- [ ] `ask_user` is the only built-in external, wired through EventBus.
- [ ] `grail check` passes for each script (no E00x errors).

---

## 1. Understanding the New Pattern

### OLD Pattern (Current)

```python
# agents/lint/tools/read_file.pym
from grail import external

@external
async def read_file(path: str) -> str: ...

content = await read_file("src/foo.py")
# Script does I/O during execution
```

### NEW Pattern (Proposed)

```python
# agents/lint/tools/analyze_code.pym
from grail import Input

# Data flows IN via Input() - populated by CairnDataProvider
source_code: str = Input("source_code")
file_path: str = Input("file_path")

# Pure computation
issues = []
for i, line in enumerate(source_code.split("\n")):
    if len(line) > 120:
        issues.append({"line": i + 1, "issue": "line too long"})

# Return structured result - host persists mutations
result = {
    "file_path": file_path,
    "issues": issues,
    "suggested_fix": "...",
}
```

### Key Differences

| Aspect | OLD Pattern | NEW Pattern |
|--------|-------------|-------------|
| Data source | `@external` calls during execution | `Input()` populated before execution |
| Side effects | Scripts write files, run commands | Scripts return dicts; host persists |
| Coupling | Tight to I/O mechanism | Loose - scripts don't know how data arrives |
| `@external` use | File I/O, commands | `ask_user` only (human-in-the-loop) |

---

## 2. Architecture Components

### CairnDataProvider

Populates the virtual filesystem before script execution:

```python
# src/remora/workspace.py
class CairnDataProvider:
    """Populates Grail virtual FS from a Cairn workspace."""
    
    def __init__(self, workspace: CairnWorkspace):
        self._ws = workspace
    
    async def load_files(self, node: CSTNode) -> dict[str, str]:
        """Read the target file + related files from the workspace."""
        files = {}
        files[node.file_path] = await self._ws.read(node.file_path)
        # Add related files based on node metadata
        return files
```

### ResultHandler

Persists script results after execution:

```python
# src/remora/workspace.py
class CairnResultHandler:
    """Writes script results back to the Cairn workspace."""
    
    async def handle(self, result: dict, workspace: CairnWorkspace) -> None:
        if "written_file" in result:
            await workspace.write(result["file_path"], result["written_file"])
        if "lint_fixes" in result:
            # Apply fixes to workspace
            ...
```

---

## 3. Implementation Steps

### Step 3.1: Identify All .pym Scripts

Find all scripts in the agents directories:

```bash
find agents/ -name "*.pym" | sort
```

Expected locations:
- `agents/lint/tools/*.pym`
- `agents/docstring/tools/*.pym`
- `agents/test/tools/*.pym`
- `agents/sample_data/tools/*.pym`
- `agents/harness/tools/*.pym`

### Step 3.2: Analyze Each Script's Purpose

For each script, identify:
1. What data does it need? (source code, config, tests, etc.)
2. What does it compute?
3. What does it return?
4. What external calls does it make?

### Step 3.3: Rewrite Using Input()

Replace `@external` declarations with `Input()` declarations at the top of each script.

**Example - Lint Bundle:**

| Old Script | New Script | Inputs | Output |
|------------|-------------|--------|--------|
| `read_file.pym` | Removed | N/A | Data provided via DataProvider |
| `run_linter.pym` | `analyze_code.pym` | `source_code`, `file_path` | `{"issues": [...]}` |
| `apply_fix.pym` | `apply_fix.pym` | `source_code`, `fixes` | `{"fixed_code": "..."}` |
| `ruff_config.pym` | Removed | N/A | Config loaded by DataProvider |

### Step 3.4: Define DataProvider Per Bundle

Create a DataProvider class for each bundle that pre-loads all required files:

```python
# src/remora/workspace.py - Lint bundle example
class LintDataProvider(CairnDataProvider):
    """DataProvider for the lint bundle."""
    
    async def load_files(self, node: CSTNode) -> dict[str, str]:
        files = {}
        
        # Main file to lint
        files["target.py"] = await self._ws.read(node.file_path)
        
        # Config file
        try:
            files["ruff.toml"] = await self._ws.read("ruff.toml")
        except FileNotFoundError:
            pass
        
        # Pyproject.toml if exists
        try:
            files["pyproject.toml"] = await self._ws.read("pyproject.toml")
        except FileNotFoundError:
            pass
        
        return files
```

### Step 3.5: Define ResultHandler Per Bundle

Create a ResultHandler class for each bundle:

```python
# src/remora/workspace.py - Lint bundle example
class LintResultHandler(CairnResultHandler):
    """ResultHandler for the lint bundle."""
    
    async def handle(self, result: dict, workspace: CairnWorkspace) -> None:
        # Handle code fixes
        if result.get("fixed_code"):
            file_path = result.get("file_path", "target.py")
            await workspace.write(file_path, result["fixed_code"])
        
        # Handle lint report
        if result.get("report"):
            await workspace.write(".remora/lint-report.json", json.dumps(result["report"]))
```

---

## 4. Per-Bundle Rewrite Guide

### 4.1 Lint Bundle (`agents/lint/`)

**Purpose:** Analyze code for style issues and apply fixes.

**Scripts to rewrite:**

| Old Script | New Script | Input Keys | Output Keys |
|------------|------------|------------|-------------|
| `read_file.pym` | REMOVED | N/A | N/A |
| `run_linter.pym` | `analyze_code.pym` | `source_code`, `file_path` | `issues`, `file_path` |
| `apply_fix.pym` | `apply_fix.pym` | `source_code`, `fixes` | `fixed_code`, `file_path` |
| `ruff_config.pym` | REMOVED | N/A | N/A |

**DataProvider:**
```python
async def load_files(self, node: CSTNode) -> dict[str, str]:
    files = {}
    files["target.py"] = await self._ws.read(node.file_path)
    for config in ["ruff.toml", "pyproject.toml"]:
        try:
            files[config] = await self._ws.read(config)
        except FileNotFoundError:
            pass
    return files
```

**ResultHandler:**
```python
async def handle(self, result: dict, workspace: CairnWorkspace) -> None:
    if result.get("fixed_code"):
        await workspace.write(result["file_path"], result["fixed_code"])
```

### 4.2 Docstring Bundle (`agents/docstring/`)

**Purpose:** Read, analyze, and write docstrings.

**Scripts to rewrite:**

| Old Script | New Script | Input Keys | Output Keys |
|------------|------------|------------|-------------|
| `docstring_style.pym` | REMOVED | N/A | N/A |
| `read_current_docstring.pym` | `read_current_docstring.pym` | `source_code` | `docstring` |
| `read_type_hints.pym` | `read_type_hints.pym` | `source_code` | `hints` |
| `write_docstring.pym` | `write_docstring.pym` | `source_code`, `docstring` | `fixed_code` |

**DataProvider:**
```python
async def load_files(self, node: CSTNode) -> dict[str, str]:
    files = {}
    files["target.py"] = await self._ws.read(node.file_path)
    return files
```

### 4.3 Test Bundle (`agents/test/`)

**Purpose:** Analyze function signatures and generate tests.

**Scripts to rewrite:**

| Old Script | New Script | Input Keys | Output Keys |
|------------|------------|------------|-------------|
| `pytest_config.pym` | REMOVED | N/A | N/A |
| `analyze_signature.pym` | `analyze_signature.pym` | `source_code` | `signature` |
| `read_existing_tests.pym` | `read_existing_tests.pym` | `source_code`, `test_file` | `tests` |
| `write_test_file.pym` | `write_test_file.pym` | `source_code`, `tests` | `written_file`, `content` |

**DataProvider:**
```python
async def load_files(self, node: CSTNode) -> dict[str, str]:
    files = {}
    files["target.py"] = await self._ws.read(node.file_path)
    # Try to read existing test file
    test_path = node.file_path.replace(".py", "_test.py")
    try:
        files["test_target.py"] = await self._ws.read(test_path)
    except FileNotFoundError:
        pass
    return files
```

### 4.4 Sample Data Bundle (`agents/sample_data/`)

**Purpose:** Generate sample data for functions.

**Scripts to rewrite:**

Similar pattern - Input data in, structured result out.

**DataProvider:**
```python
async def load_files(self, node: CSTNode) -> dict[str, str]:
    files = {}
    files["target.py"] = await self._ws.read(node.file_path)
    return files
```

### 4.5 Harness Bundle (`agents/harness/`)

**Purpose:** Simple test cases for development.

**Scripts to rewrite:**

Typically contains simple tools for testing. Follow the same pattern.

---

## 5. Verification

### 5.1 Syntax Check

Run grail check on each script:

```bash
grail check agents/lint/tools/analyze_code.pym
grail check agents/docstring/tools/read_current_docstring.pym
# ... etc
```

### 5.2 Unit Tests

Test each DataProvider + script + ResultHandler flow:

```python
# tests/test_workspace.py
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_lint_bundle():
    # Create mock workspace
    workspace = AsyncMock()
    workspace.read = AsyncMock(return_value="x = 1\n" * 200)
    
    # Create DataProvider
    provider = LintDataProvider(workspace)
    files = await provider.load_files(mock_node)
    
    # Run script
    result = await grail.run(
        "analyze_code.pym",
        inputs={"source_code": files["target.py"], "file_path": "test.py"},
        files=files,
    )
    
    # Verify result
    assert "issues" in result
    assert len(result["issues"]) > 0
```

### 5.3 Integration Tests

Test the full execution pipeline with real bundles.

---

## 6. Common Pitfalls

### Pitfall 1: Missing Data

**Problem:** Script needs data that DataProvider didn't load.

**Solution:** Update the DataProvider to load the required file. This is a DataProvider bug, not a script limitation.

### Pitfall 2: Wrong Result Format

**Problem:** Script returns format that ResultHandler doesn't expect.

**Solution:** Ensure the script's output keys match what the ResultHandler expects. Document the contract.

### Pitfall 3: Still Using @external

**Problem:** Script still has `@external` for file operations.

**Solution:** Remove all `@external` declarations except `ask_user`. Move all file I/O to Input().

### Pitfall 4: Ad-hoc Reads

**Problem:** Script tries to read files during execution using `open()`.

**Solution:** All data must be pre-loaded. Use Input() at the top of the script, not `open()` calls.

---

## 7. Files to Create/Modify

### Create

- `src/remora/workspace.py` - CairnDataProvider and CairnResultHandler base classes and per-bundle implementations

### Modify

- All 22 .pym scripts in `agents/*/tools/`
- `agents/*/bundle.yaml` - May need updates for structured-agents v0.3 format

### Remove

- `agents/*/tools/read_file.pym` - Data provided via Input
- `agents/*/tools/ruff_config.pym` - Data provided via Input
- `agents/*/tools/pytest_config.pym` - Data provided via Input
- `agents/*/tools/docstring_style.pym` - Data provided via Input

---

## 8. Dependencies

- **grail** - `Input` class for data injection
- **grail** - `external` for `ask_user` only (human-in-the-loop)
- **cairn** - Workspace for file isolation

---

## 9. What to Preserve

- Sandboxed execution (Grail's Monty runtime)
- Type-safe inputs (`Input()` with type annotations)
- Output validation (output_model on run())
- The ability to use `@external` for genuine external services (ask_user)

---

## 10. Summary Checklist

- [ ] Identify all 22 .pym scripts
- [ ] Analyze each script's inputs and outputs
- [ ] Rewrite each script using Input() pattern
- [ ] Create DataProvider for each bundle
- [ ] Create ResultHandler for each bundle
- [ ] Remove obsolete scripts (read_file, config files)
- [ ] Run grail check on each script
- [ ] Write unit tests for DataProvider + script + ResultHandler
- [ ] Verify no @external for file operations remain (except ask_user)
