# Implementation Guide: Step 15 — Cleanup

## Overview

This step finalizes the Remora v1.0 refactor by removing all deprecated code, updating project configuration, and verifying the new architecture works correctly.

**Estimated Time:** 30-45 minutes  
**Prerequisites:** Steps 1-14 complete, all new modules implemented and tested

---

## What This Step Does

The cleanup step performs final housekeeping:

1. **Removes deprecated files** — Deletes old code that's been replaced by the new architecture
2. **Updates configuration** — Aligns `pyproject.toml` with the new module structure and dependencies
3. **Verifies integrity** — Runs type checking, linting, and tests to ensure everything works
4. **Documents migration** — Creates an optional guide for users upgrading from v0.3

---

## Step 1: Verify Current State

Before deleting anything, verify what files currently exist in the project:

```bash
# Check the current src/remora/ structure
ls -la src/remora/

# Check if any old files still exist
ls -la src/remora/agent_graph.py 2>/dev/null && echo "EXISTS" || echo "Already removed"
ls -la src/remora/workspace.py 2>/dev/null && echo "EXISTS" || echo "Already removed"
```

**Expected state at this point:**
- Old files from the original architecture should still exist
- New files from the refactor should be in place
- Both cannot coexist — we need to remove the old

---

## Step 2: Delete Deprecated Core Files

Remove the core files that have been replaced by the new architecture:

```bash
# Remove deprecated core files
rm -v src/remora/agent_graph.py
rm -v src/remora/agent_state.py
rm -v src/remora/constants.py
rm -v src/remora/backend.py
```

**What each file contained (for reference):**
| File | Replaced By |
|------|-------------|
| `agent_graph.py` | `graph.py` + `executor.py` |
| `agent_state.py` | Cairn workspace integration |
| `constants.py` | `config.py` defaults |
| `backend.py` | `Agent.from_bundle()` in executor |

---

## Step 3: Delete Deprecated Packages

Remove entire packages that have been replaced:

```bash
# Discovery package - consolidated into discovery.py
rm -rf src/remora/discovery/

# Context package - consolidated into context.py
rm -rf src/remora/context/

# Interactive package - replaced by event-based IPC
rm -rf src/remora/interactive/

# Hub package - split into indexer/ and dashboard/
rm -rf src/remora/hub/

# Frontend package - absorbed into dashboard/
rm -rf src/remora/frontend/
```

**What each package contained (for reference):**

| Package | Files | Replaced By |
|---------|-------|-------------|
| `discovery/` | 5 files | `discovery.py` |
| `context/` | 5 files | `context.py` |
| `interactive/` | 2 files | Event-based IPC in `events.py` + `event_bus.py` |
| `hub/` | 14 files | `indexer/` + `dashboard/` packages |
| `frontend/` | 3 files | `dashboard/` package |

---

## Step 4: Delete Old Workspace Module

The old `workspace.py` (not to be confused with the new workspace wrappers) is replaced by Cairn:

```bash
# Old workspace abstractions replaced by Cairn
rm -v src/remora/workspace.py
```

**Verification:** Confirm the new `workspace.py` doesn't exist yet (or will be created as Cairn wrappers):

```bash
ls -la src/remora/workspace.py 2>/dev/null && echo "WARNING: Old workspace.py still exists" || echo "OK: workspace.py removed or doesn't exist"
```

---

## Step 5: Verify New Structure Exists

Before updating configuration, confirm the new modules are in place:

```bash
# Check new core modules exist
ls -la src/remora/discovery.py
ls -la src/remora/graph.py
ls -la src/remora/executor.py
ls -la src/remora/events.py
ls -la src/remora/event_bus.py
ls -la src/remora/context.py
ls -la src/remora/config.py
ls -la src/remora/workspace.py  # Cairn wrappers

# Check new packages exist
ls -la src/remora/indexer/
ls -la src/remora/dashboard/
```

**If any new modules are missing:** Return to the appropriate step in the implementation guide and create them first.

---

## Step 6: Update pyproject.toml

Update the project configuration to reflect the new architecture:

### Read Current Configuration

```bash
cat pyproject.toml
```

### Update the Configuration

Replace the `[project]`, `[project.scripts]`, and `[project.optional-dependencies]` sections:

```toml
[project]
name = "remora"
version = "1.0.0"
description = "AI-powered code analysis and transformation framework"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [
    { name = "Remora Team", email = "team@remora.dev" }
]

dependencies = [
    "typer>=0.9.0",
    "rich>=13.0.0",
    "pydantic>=2.0.0",
    "pyyaml>=6.0.0",
    "jinja2>=3.1.0",
    "tree-sitter>=0.20.0",
    "fsdantic>=0.1.0",
    "grail>=3.0.0",
    "cairn>=1.0.0",
    "structured-agents>=0.3.0",
    "starlette>=0.27.0",
    "datastar-py>=0.1.0",
    "uvicorn>=0.23.0",
    "httpx>=0.24.0",
    "watchfiles>=0.21.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.1.0",
    "mypy>=1.5.0",
    "pre-commit>=3.4.0",
]
indexer = [
    "watchfiles>=0.21.0",
]
dashboard = [
    "starlette>=0.27.0",
    "datastar-py>=0.1.0",
    "uvicorn>=0.23.0",
]
all = [
    "remora[indexer]",
    "remora[dashboard]",
    "remora[dev]",
]

[project.scripts]
remora = "remora.cli:app"
remora-index = "remora.indexer.cli:app"
remora-dashboard = "remora.dashboard.cli:app"

[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM"]
ignore = ["E501"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = false
disallow_incomplete_defs = false
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_configs = true
disallow_untyped_calls = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

---

## Step 7: Update __init__.py

Update the main package `__init__.py` to export the new public API:

```python
"""Remora v1.0 — AI-powered code analysis and transformation framework."""

__version__ = "1.0.0"

from remora.discovery import CSTNode, discover
from remora.graph import AgentNode, build_graph
from remora.executor import GraphExecutor, ExecutorState
from remora.events import (
    GraphStartEvent,
    GraphCompleteEvent,
    AgentStartEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
    RemoraEvent,
)
from remora.event_bus import EventBus
from remora.context import ContextBuilder
from remora.config import RemoraConfig, load_config
from remora.workspace import CairnDataProvider, CairnResultHandler
from remora.checkpoint import CheckpointManager
from remora.errors import RemoraError, DiscoveryError, ExecutionError

__all__ = [
    # Version
    "__version__",
    # Discovery
    "CSTNode",
    "discover",
    # Graph
    "AgentNode",
    "build_graph",
    # Execution
    "GraphExecutor",
    "ExecutorState",
    # Events
    "RemoraEvent",
    "GraphStartEvent",
    "GraphCompleteEvent",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    # Event Bus
    "EventBus",
    # Context
    "ContextBuilder",
    # Configuration
    "RemoraConfig",
    "load_config",
    # Workspace
    "CairnDataProvider",
    "CairnResultHandler",
    # Checkpointing
    "CheckpointManager",
    # Errors
    "RemoraError",
    "DiscoveryError",
    "ExecutionError",
]
```

---

## Step 8: Run Type Checking

Run mypy to verify type annotations are correct:

```bash
cd /home/andrew/Documents/Projects/remora
mypy src/remora/
```

### Common Type Errors and Fixes

**1. Missing imports:**
```
error: Cannot find implementation or library stub for module
```
→ Add the module to dependencies in `pyproject.toml`

**2. Missing type annotations:**
```
error: Function is missing return type annotation
```
→ Add return type annotations to functions

**3. Any types remaining from old code:**
```
error: Implicitly returning "Any"
```
→ Replace `Any` with proper types or use `Unknown` from typing

**4. Import errors from deleted files:**
```
error: Cannot import name 'AgentGraph' from 'remora'
```
→ Update imports to use new module names

---

## Step 9: Run Linting

Run ruff to check code style:

```bash
cd /home/andrew/Documents/Projects/remora
ruff check src/remora/
```

### Common Lint Issues and Fixes

**1. Unused imports:**
```
F401 imported but unused
```
→ Remove unused imports

**2. Undefined names:**
```
F821 undefined name 'foo'
```
→ Check for typos or missing imports

**3. Missing docstrings (optional):**
```
D100 Missing docstring in public module
```
→ Add docstrings or add to ignored rules in pyproject.toml

**4. Long lines:**
```
E501 line too long
```
→ Break lines or adjust line-length in config

---

## Step 10: Run Tests

Run the test suite to verify everything works:

```bash
cd /home/andrew/Documents/Projects/remora
pytest tests/ -v
```

### Test Structure Verification

Ensure tests are organized:

```
tests/
├── test_discovery.py      # CSTNode, discover()
├── test_graph.py         # AgentNode, build_graph()
├── test_executor.py      # GraphExecutor
├── test_events.py        # Event types, EventBus
├── test_context.py       # ContextBuilder
├── test_config.py        # RemoraConfig
├── test_workspace.py     # Cairn wrappers
├── test_indexer/         # Indexer package tests
├── test_dashboard/       # Dashboard package tests
└── conftest.py           # Shared fixtures
```

### If Tests Fail

1. **Import errors:** Check `__init__.py` exports
2. **Missing fixtures:** Check `conftest.py`
3. **Assertion failures:** Review the implementation in the relevant module
4. **Async issues:** Ensure async tests use `@pytest.mark.asyncio`

---

## Step 11: Verify Imports

Test that the package imports correctly:

```bash
cd /home/andrew/Documents/Projects/remora
python -c "import remora; print('Import OK')"
python -c "from remora import discover, build_graph, GraphExecutor; print('Core OK')"
python -c "from remora.indexer import daemon; print('Indexer OK')"
python -c "from remora.dashboard import app; print('Dashboard OK')"
```

---

## Step 12: Verify CLI Entry Points

Test that the CLI commands are registered:

```bash
cd /home/andrew/Documents/Projects/remora

# Install the package in editable mode
pip install -e .

# Test main CLI
remora --help

# Test indexer CLI
remora-index --help

# Test dashboard CLI
remora-dashboard --help
```

---

## Step 13: Create Migration Guide (Optional)

If you want to document the changes for users upgrading from v0.3, create `MIGRATION_GUIDE.md`:

```markdown
# Migration Guide: v0.3 to v1.0

## Overview

Remora v1.0 is a complete ground-up refactor. This guide helps you migrate from v0.3.

## Breaking Changes

### Module Reorganization

| v0.3 | v1.0 |
|------|------|
| `remora.agent_graph` | `remora.graph` + `remora.executor` |
| `remora.workspace` | `remora.workspace` (Cairn wrappers) |
| `remora.discovery` | `remora.discovery` (consolidated) |
| `remora.context` | `remora.context` (simplified) |
| `remora.hub` | `remora.indexer` + `remora.dashboard` |

### Configuration

**Old (v0.3):**
```yaml
server:
  host: "0.0.0.0"
  port: 8420
runner:
  max_concurrency: 4
```

**New (v1.0):**
```yaml
dashboard:
  host: "0.0.0.0"
  port: 8420
  
execution:
  max_concurrency: 4
```

### CLI Commands

| v0.3 | v1.0 |
|------|------|
| `python -m remora` | `remora` |
| (no separate command) | `remora-index` |
| (no separate command) | `remora-dashboard` |

### API Changes

- `AgentGraph` → Removed (use `build_graph()` function)
- `GraphExecutor` → Still available, simplified API
- `WorkspaceKV`, `GraphWorkspace`, `WorkspaceManager` → Replaced by Cairn
- `EventBus` → Still available, unified with structured-agents Observer

### Bundle Format

Bundles now use structured-agents v0.3 format:

```yaml
name: lint_agent
model: qwen
grammar: ebnf
limits: default
system_prompt: |
  You are a linting agent...
tools:
  - tools/*.pym
termination: submit_result
max_turns: 8

# Remora extensions
node_types: [function, class]
priority: 10
requires_context: true
```

## Migration Steps

1. Update `pyproject.toml` dependencies
2. Move bundle configuration to `bundle.yaml` format
3. Update `remora.yaml` to new structure
4. Replace workspace imports with Cairn
5. Update CLI invocations

## New Features

- **Event-based IPC** — Human-in-the-loop via events, not file polling
- **Cairn-native workspace** — Copy-on-write isolation
- **Unified events** — All events flow through EventBus
- **Separate indexer** — Background file indexing as standalone service
```

---

## Step 14: Final Verification

Run a complete verification:

```bash
cd /home/andrew/Documents/Projects/remora

# 1. Check file count reduction
echo "=== Old file count ==="
find src/remora -name "*.py" | wc -l

# 2. Verify no deprecated files remain
echo "=== Checking for deprecated files ==="
for f in agent_graph.py agent_state.py constants.py backend.py workspace.py; do
    if [ -f "src/remora/$f" ]; then
        echo "WARNING: $f still exists"
    else
        echo "OK: $f removed"
    fi
done

# 3. Check packages
echo "=== Checking packages ==="
for pkg in discovery context interactive hub frontend; do
    if [ -d "src/remora/$pkg" ]; then
        echo "WARNING: $pkg/ still exists"
    else
        echo "OK: $pkg/ removed"
    fi
done

# 4. Verify new structure
echo "=== New structure ==="
ls src/remora/*.py | head -20
ls -d src/remora/indexer/ src/remora/dashboard/ 2>/dev/null && echo "OK: New packages exist"

# 5. Run tests one more time
echo "=== Running tests ==="
pytest tests/ -v --tb=short
```

---

## Troubleshooting

### "ModuleNotFoundError" After Cleanup

Some old modules may still be imported elsewhere. Check:
- Test files may import old modules
- Example scripts may reference old code
- CI configuration may reference old paths

### Type Errors in New Code

The refactor may have introduced new type issues. Fix each error:
1. Run `mypy src/remora/`
2. Fix errors in order
3. Re-run until clean

### Import Errors After Deleting Files

Some code may still reference deleted modules. Find references:

```bash
grep -r "from remora import.*hub" src/
grep -r "from remora.discovery" src/
grep -r "from remora.context" src/
```

### Test Failures After Cleanup

If tests fail after deleting files:
1. Check test imports are updated
2. Verify test fixtures reference new modules
3. Look for hardcoded paths to deleted files

---

## Summary Checklist

- [ ] Deleted `agent_graph.py`
- [ ] Deleted `agent_state.py`
- [ ] Deleted `constants.py`
- [ ] Deleted `backend.py`
- [ ] Deleted `workspace.py`
- [ ] Deleted `discovery/` package
- [ ] Deleted `context/` package
- [ ] Deleted `interactive/` package
- [ ] Deleted `hub/` package
- [ ] Deleted `frontend/` package
- [ ] Updated `pyproject.toml`
- [ ] Updated `__init__.py`
- [ ] Type checking passes (`mypy`)
- [ ] Linting passes (`ruff`)
- [ ] Tests pass (`pytest`)
- [ ] Imports work (`python -c "import remora"`)
- [ ] CLI commands work (`remora --help`)

---

## Next Steps

With cleanup complete, the refactor is finished! You now have:

- **56% fewer Python files** (~50 → ~22)
- **43% fewer packages** (7 → 4)
- **Modern architecture** using Cairn, structured-agents v0.3, and event-based IPC
- **Clear module boundaries** — each file has a single responsibility

The system is ready for development, testing, and production use.
