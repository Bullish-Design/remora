# MVP Demo Implementation Guide

> **Status**: Implementation Guide
> **Author**: Claude Opus 4.5
> **Date**: 2026-02-22
> **Approach**: Neovim + Cairn Workspace Views + Tree-sitter Integration

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Workspace Structure](#3-workspace-structure)
4. [Prerequisites](#4-prerequisites)
5. [Phase 1: Workspace Manager](#5-phase-1-workspace-manager)
6. [Phase 2: Neovim Plugin Core](#6-phase-2-neovim-plugin-core)
7. [Phase 3: Workspace View Panel](#7-phase-3-workspace-view-panel)
8. [Phase 4: Tree-sitter Integration](#8-phase-4-tree-sitter-integration)
9. [Phase 5: Live File Watching](#9-phase-5-live-file-watching)
10. [Phase 6: Context Providers](#10-phase-6-context-providers)
11. [Phase 7: Demo Polish](#11-phase-7-demo-polish)
12. [Demo Script](#12-demo-script)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Executive Summary

### Why This MVP?

The **Cairn Workspace View** demo creates maximum "wow factor" by making agent reasoning *physically visible*:

| Advantage | Explanation |
|-----------|-------------|
| **Visible Reasoning** | Watch files appear in workspace as agent thinks |
| **Physical Evidence** | Context searches, drafts, evaluations are all files |
| **REM Alignment** | Each node is a true Recursive Environment |
| **Interactive** | Browse workspace like a file tree mid-execution |
| **Persistent** | Workspace survives restarts, can be resumed |

### Demo Story

> "Watch as Remora creates a dedicated environment for each code node. The agent researches your codebase, pulls documentation, evaluates options—and you can see every file it creates in real-time. This isn't a black box. This is transparent AI reasoning."

### Demo Flow (45 seconds)

1. Open Python file in Neovim
2. `vaf` → select around function (tree-sitter text object)
3. `:RemoraAnalyze docstring` → creates workspace for this node
4. **Side panel slides in** showing live workspace:
   ```
   .remora/workspaces/calculate_total/
   ├── context/
   │   ├── related_functions.md      ← Agent found these
   │   ├── library_docs.md           ← Pulled from knowledge graph
   │   └── existing_docstrings.md    ← Pattern examples
   ├── scratch/
   │   ├── draft_1.py                ← First attempt
   │   ├── evaluation.md             ← Self-critique
   │   └── draft_2.py                ← Refined version
   ├── output/
   │   └── proposed_change.py        ← Final proposal
   └── status.json                   ← Live status updates
   ```
5. Files appear in real-time as agent works
6. `:RemoraAccept` → merge `output/` to source file

### Effort Estimate

| Phase | Effort | Description |
|-------|--------|-------------|
| Phase 1 | 2 days | Workspace manager (create, watch, structure) |
| Phase 2 | 2 days | Neovim plugin core (commands, state) |
| Phase 3 | 3 days | Workspace view panel (side panel, file tree) |
| Phase 4 | 1 day | Tree-sitter integration for node selection |
| Phase 5 | 2 days | Live file watching and auto-refresh |
| Phase 6 | 2 days | Context providers (docs, knowledge graph) |
| Phase 7 | 1 day | Demo polish and scripted walkthrough |

**Total: ~13 days**

---

## 2. Architecture Overview

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              NEOVIM                                     │
│                                                                         │
│  ┌────────────────────────┐          ┌────────────────────────────────┐ │
│  │     Source Buffer      │          │     Workspace View Panel       │ │
│  │     (Python file)      │          │     (Side Panel)               │ │
│  │                        │          │                                │ │
│  │  def calculate_total(  │          │  📁 calculate_total/           │ │
│  │      items,            │ ◄──────► │  ├── 📁 context/               │ │
│  │      tax_rate,         │  Sync    │  │   ├── 📄 related_funcs.md   │ │
│  │      discount          │          │  │   └── 📄 library_docs.md    │ │
│  │  ):                    │          │  ├── 📁 scratch/               │ │
│  │      ...               │          │  │   ├── 📄 draft_1.py         │ │
│  │                        │          │  │   └── 📄 evaluation.md      │ │
│  └────────────────────────┘          │  └── 📁 output/                │ │
│            │                         │      └── 📄 proposed.py        │ │
│            │ :RemoraAnalyze          └─────────────┬──────────────────┘ │
│            ▼                                       │                    │
│  ┌────────────────────────┐                        │ Watch for changes  │
│  │   Remora Plugin (Lua)  │                        │ (libuv/watchfiles) │
│  │   - Workspace Manager  │◄───────────────────────┘                    │
│  │   - File Tree Renderer │                                             │
│  │   - Status Monitor     │                                             │
│  └───────────┬────────────┘                                             │
└──────────────┼──────────────────────────────────────────────────────────┘
               │
               │ Create workspace, spawn agent
               ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         CAIRN WORKSPACE                                │
│  .remora/workspaces/{node_id}/                                         │
│                                                                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │   context/  │  │   scratch/  │  │   output/   │  │ status.json │    │
│  │             │  │             │  │             │  │             │    │
│  │ Agent reads │  │ Agent works │  │ Final props │  │ Live status │    │
│  │ & writes    │  │ iteratively │  │ for review  │  │ for UI      │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
│         ▲                ▲                ▲                ▲           │
│         │                │                │                │           │
│         └────────────────┴────────────────┴────────────────┘           │
│                                   │                                    │
│                          Agent writes files                            │
│                                   │                                    │
│  ┌────────────────────────────────┴────────────────────────────────┐   │
│  │                      REMORA AGENT                               │   │
│  │                                                                 │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │   │
│  │  │ Context      │  │ Reasoning    │  │ Output       │           │   │
│  │  │ Providers    │  │ Engine       │  │ Generator    │           │   │
│  │  │              │  │              │  │              │           │   │
│  │  │ - Docs fetch │  │ - Draft      │  │ - Format     │           │   │
│  │  │ - KG search  │  │ - Evaluate   │  │ - Validate   │           │   │
│  │  │ - AST scan   │  │ - Refine     │  │ - Write      │           │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Principles

1. **Workspace as Communication**: No stdin/stdout streaming. Agents write files, Neovim watches files.

2. **Physical Evidence**: Every agent action produces a file. User can see exactly what the agent researched, drafted, and decided.

3. **Interruptible**: User can browse workspace mid-execution. Agent can be stopped and resumed.

4. **Node Isolation**: Each AST node (function, class) gets its own workspace. No cross-contamination.

5. **Live Updates**: File watcher triggers UI refresh. Changes appear instantly.

---

## 3. Workspace Structure

### Standard Layout

Every node workspace follows this structure:

```
.remora/workspaces/{node_id}/
├── context/                      # Research & context gathering
│   ├── node_source.py            # Original source code
│   ├── node_metadata.json        # AST info, location, type
│   ├── related_functions.md      # Similar functions found
│   ├── related_tests.md          # Existing tests for this node
│   ├── library_docs.md           # Relevant documentation
│   ├── codebase_patterns.md      # Patterns from this codebase
│   └── knowledge_graph.json      # Structured knowledge
│
├── scratch/                      # Agent working space
│   ├── draft_001.py              # First attempt
│   ├── draft_001_eval.md         # Self-evaluation
│   ├── draft_002.py              # Refined attempt
│   ├── draft_002_eval.md         # Second evaluation
│   └── final_decision.md         # Why agent chose this approach
│
├── output/                       # Final proposals for user
│   ├── proposed_change.py        # The actual code change
│   ├── proposed_change.diff      # Diff format for easy review
│   └── summary.md                # Human-readable summary
│
├── logs/                         # Execution logs
│   ├── agent.log                 # Agent execution log
│   ├── tools.log                 # Tool invocations
│   └── errors.log                # Any errors encountered
│
├── status.json                   # Live status for UI
└── workspace.lock                # Prevents concurrent access
```

### status.json Schema

```json
{
  "node_id": "src/calculator.py:calculate_total",
  "node_name": "calculate_total",
  "node_type": "function",
  "operation": "docstring",
  "status": "executing",
  "phase": "context_gathering",
  "progress": {
    "current_step": "Searching for similar docstrings",
    "steps_completed": 2,
    "steps_total": 5
  },
  "files": {
    "context": ["node_source.py", "related_functions.md"],
    "scratch": ["draft_001.py"],
    "output": []
  },
  "started_at": "2026-02-22T14:30:00Z",
  "updated_at": "2026-02-22T14:30:15Z",
  "error": null
}
```

### Workspace States

| State | Description | UI Indicator |
|-------|-------------|--------------|
| `pending` | Workspace created, agent not started | ⏳ |
| `executing` | Agent actively working | 🔄 |
| `paused` | Agent paused (user can resume) | ⏸️ |
| `completed` | Agent finished, awaiting review | ✅ |
| `accepted` | User accepted changes | ✔️ |
| `rejected` | User rejected changes | ❌ |
| `error` | Agent encountered error | ⚠️ |

---

## 4. Prerequisites

### 4.1 Neovim Setup

**Required Neovim version**: 0.10.0+ (for improved file watching)

**Required plugins**:

```lua
-- lazy.nvim example
{
  "nvim-treesitter/nvim-treesitter",
  build = ":TSUpdate",
},
{
  "nvim-treesitter/nvim-treesitter-textobjects",
  dependencies = { "nvim-treesitter/nvim-treesitter" },
},
{
  "nvim-tree/nvim-web-devicons",  -- For file icons in panel
  lazy = true,
},
{
  "nvim-lua/plenary.nvim",  -- For async utilities
},
```

### 4.2 Remora Setup

**Verify Remora CLI**:

```bash
# Should list available agents
remora list-agents

# Verify workspaces can be created
mkdir -p .remora/workspaces/test
ls .remora/workspaces/
```

### 4.3 Verification Checkpoint

- [ ] Neovim 0.10.0+ installed
- [ ] Tree-sitter Python parser working
- [ ] plenary.nvim available
- [ ] `.remora/` directory writable
- [ ] Remora CLI in PATH

---

## 5. Phase 1: Workspace Manager

**Goal**: Create Python module for workspace lifecycle management.

### 5.1 Workspace Manager Module

**File**: `src/remora/workspace_manager.py` (NEW)

```python
"""
src/remora/workspace_manager.py

Manages Cairn workspaces for node-level agent execution.
Each AST node gets its own isolated workspace with standard structure.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from enum import Enum

from pydantic import BaseModel, Field


class WorkspaceStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ERROR = "error"


class WorkspaceProgress(BaseModel):
    current_step: str = ""
    steps_completed: int = 0
    steps_total: int = 0


class WorkspaceState(BaseModel):
    """Live state written to status.json for UI consumption."""
    node_id: str
    node_name: str
    node_type: str
    operation: str
    status: WorkspaceStatus = WorkspaceStatus.PENDING
    phase: str = "initializing"
    progress: WorkspaceProgress = Field(default_factory=WorkspaceProgress)
    files: dict[str, list[str]] = Field(default_factory=lambda: {
        "context": [],
        "scratch": [],
        "output": [],
    })
    started_at: str | None = None
    updated_at: str | None = None
    error: str | None = None


class NodeWorkspace:
    """
    Manages a single node's workspace.

    Provides methods for:
    - Creating workspace structure
    - Writing context, scratch, and output files
    - Updating status for UI
    - Cleaning up on accept/reject
    """

    SUBDIRS = ["context", "scratch", "output", "logs"]

    def __init__(
        self,
        workspace_root: Path,
        node_id: str,
        node_name: str,
        node_type: str,
        operation: str,
    ):
        self.workspace_root = workspace_root
        self.node_id = node_id
        self.node_name = node_name
        self.node_type = node_type
        self.operation = operation

        # Sanitize node_id for filesystem
        self.workspace_id = self._sanitize_id(node_id)
        self.path = workspace_root / self.workspace_id

        # State tracking
        self._state = WorkspaceState(
            node_id=node_id,
            node_name=node_name,
            node_type=node_type,
            operation=operation,
        )

    @staticmethod
    def _sanitize_id(node_id: str) -> str:
        """Convert node_id to filesystem-safe name."""
        # Replace path separators and colons
        safe = node_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        # Remove leading dots
        safe = safe.lstrip(".")
        return safe

    def create(self) -> None:
        """Create workspace directory structure."""
        self.path.mkdir(parents=True, exist_ok=True)

        for subdir in self.SUBDIRS:
            (self.path / subdir).mkdir(exist_ok=True)

        # Initialize status
        self._state.started_at = datetime.now(timezone.utc).isoformat()
        self._write_status()

    def exists(self) -> bool:
        """Check if workspace already exists."""
        return self.path.exists()

    def _write_status(self) -> None:
        """Write current state to status.json."""
        self._state.updated_at = datetime.now(timezone.utc).isoformat()
        status_path = self.path / "status.json"
        status_path.write_text(
            self._state.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def update_status(
        self,
        status: WorkspaceStatus | None = None,
        phase: str | None = None,
        current_step: str | None = None,
        steps_completed: int | None = None,
        steps_total: int | None = None,
        error: str | None = None,
    ) -> None:
        """Update workspace status for UI."""
        if status is not None:
            self._state.status = status
        if phase is not None:
            self._state.phase = phase
        if current_step is not None:
            self._state.progress.current_step = current_step
        if steps_completed is not None:
            self._state.progress.steps_completed = steps_completed
        if steps_total is not None:
            self._state.progress.steps_total = steps_total
        if error is not None:
            self._state.error = error
            self._state.status = WorkspaceStatus.ERROR

        self._write_status()

    def write_context(self, filename: str, content: str) -> Path:
        """Write a file to the context directory."""
        file_path = self.path / "context" / filename
        file_path.write_text(content, encoding="utf-8")
        self._update_file_list("context", filename)
        return file_path

    def write_scratch(self, filename: str, content: str) -> Path:
        """Write a file to the scratch directory."""
        file_path = self.path / "scratch" / filename
        file_path.write_text(content, encoding="utf-8")
        self._update_file_list("scratch", filename)
        return file_path

    def write_output(self, filename: str, content: str) -> Path:
        """Write a file to the output directory."""
        file_path = self.path / "output" / filename
        file_path.write_text(content, encoding="utf-8")
        self._update_file_list("output", filename)
        return file_path

    def write_log(self, filename: str, content: str, append: bool = True) -> Path:
        """Write or append to a log file."""
        file_path = self.path / "logs" / filename
        mode = "a" if append else "w"
        with open(file_path, mode, encoding="utf-8") as f:
            f.write(content)
        return file_path

    def _update_file_list(self, category: str, filename: str) -> None:
        """Update the files list in status."""
        if filename not in self._state.files[category]:
            self._state.files[category].append(filename)
            self._write_status()

    def read_file(self, category: str, filename: str) -> str | None:
        """Read a file from workspace."""
        file_path = self.path / category / filename
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
        return None

    def get_status(self) -> WorkspaceState:
        """Get current workspace status."""
        return self._state

    def mark_completed(self) -> None:
        """Mark workspace as completed, awaiting review."""
        self.update_status(status=WorkspaceStatus.COMPLETED, phase="awaiting_review")

    def accept(self, target_file: Path) -> None:
        """Accept changes: copy output to target file."""
        output_dir = self.path / "output"
        proposed = output_dir / "proposed_change.py"

        if proposed.exists():
            shutil.copy(proposed, target_file)
            self.update_status(status=WorkspaceStatus.ACCEPTED, phase="applied")

    def reject(self) -> None:
        """Reject changes: mark workspace as rejected."""
        self.update_status(status=WorkspaceStatus.REJECTED, phase="discarded")

    def cleanup(self, delete: bool = False) -> None:
        """Clean up workspace. Optionally delete entirely."""
        if delete and self.path.exists():
            shutil.rmtree(self.path)


class WorkspaceManager:
    """
    Manages all node workspaces for a project.

    Handles:
    - Workspace creation and discovery
    - Status aggregation for UI
    - Cleanup of old workspaces
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.workspace_root = project_root / ".remora" / "workspaces"
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def create_workspace(
        self,
        node_id: str,
        node_name: str,
        node_type: str,
        operation: str,
    ) -> NodeWorkspace:
        """Create a new workspace for a node."""
        workspace = NodeWorkspace(
            workspace_root=self.workspace_root,
            node_id=node_id,
            node_name=node_name,
            node_type=node_type,
            operation=operation,
        )
        workspace.create()
        return workspace

    def get_workspace(self, node_id: str) -> NodeWorkspace | None:
        """Get existing workspace by node_id."""
        workspace_id = NodeWorkspace._sanitize_id(node_id)
        workspace_path = self.workspace_root / workspace_id

        if not workspace_path.exists():
            return None

        status_path = workspace_path / "status.json"
        if not status_path.exists():
            return None

        # Load state from status.json
        state = WorkspaceState.model_validate_json(status_path.read_text())

        workspace = NodeWorkspace(
            workspace_root=self.workspace_root,
            node_id=state.node_id,
            node_name=state.node_name,
            node_type=state.node_type,
            operation=state.operation,
        )
        workspace._state = state
        return workspace

    def list_workspaces(self) -> list[NodeWorkspace]:
        """List all workspaces in project."""
        workspaces = []

        for workspace_dir in self.workspace_root.iterdir():
            if not workspace_dir.is_dir():
                continue

            status_path = workspace_dir / "status.json"
            if not status_path.exists():
                continue

            try:
                state = WorkspaceState.model_validate_json(status_path.read_text())
                workspace = NodeWorkspace(
                    workspace_root=self.workspace_root,
                    node_id=state.node_id,
                    node_name=state.node_name,
                    node_type=state.node_type,
                    operation=state.operation,
                )
                workspace._state = state
                workspaces.append(workspace)
            except Exception:
                continue

        return workspaces

    def list_active_workspaces(self) -> list[NodeWorkspace]:
        """List workspaces that are pending, executing, or completed."""
        active_states = {
            WorkspaceStatus.PENDING,
            WorkspaceStatus.EXECUTING,
            WorkspaceStatus.PAUSED,
            WorkspaceStatus.COMPLETED,
        }
        return [
            ws for ws in self.list_workspaces()
            if ws.get_status().status in active_states
        ]

    def cleanup_old_workspaces(self, max_age_hours: int = 24) -> int:
        """Clean up workspaces older than max_age_hours."""
        now = datetime.now(timezone.utc)
        cleaned = 0

        for workspace in self.list_workspaces():
            state = workspace.get_status()
            if state.updated_at:
                updated = datetime.fromisoformat(state.updated_at)
                age_hours = (now - updated).total_seconds() / 3600

                if age_hours > max_age_hours and state.status in {
                    WorkspaceStatus.ACCEPTED,
                    WorkspaceStatus.REJECTED,
                    WorkspaceStatus.ERROR,
                }:
                    workspace.cleanup(delete=True)
                    cleaned += 1

        return cleaned
```

### 5.2 CLI Integration

**File**: `src/remora/cli.py`

Add workspace-related commands:

```python
@app.command()
def workspace(
    action: Annotated[str, typer.Argument(help="Action: list, show, clean")],
    node_id: Annotated[str | None, typer.Argument()] = None,
):
    """Manage node workspaces."""
    from remora.workspace_manager import WorkspaceManager

    manager = WorkspaceManager(Path.cwd())

    if action == "list":
        workspaces = manager.list_workspaces()
        for ws in workspaces:
            state = ws.get_status()
            typer.echo(f"{state.status.value:10} {state.node_name:30} {state.operation}")

    elif action == "show" and node_id:
        workspace = manager.get_workspace(node_id)
        if workspace:
            state = workspace.get_status()
            typer.echo(state.model_dump_json(indent=2))
        else:
            typer.echo(f"Workspace not found: {node_id}", err=True)

    elif action == "clean":
        cleaned = manager.cleanup_old_workspaces()
        typer.echo(f"Cleaned {cleaned} old workspaces")
```

### 5.3 Verification

**Test workspace creation**:

```python
# tests/test_workspace_manager.py

import pytest
from pathlib import Path
from remora.workspace_manager import WorkspaceManager, WorkspaceStatus


def test_create_workspace(tmp_path):
    manager = WorkspaceManager(tmp_path)

    ws = manager.create_workspace(
        node_id="src/calc.py:add",
        node_name="add",
        node_type="function",
        operation="docstring",
    )

    assert ws.exists()
    assert (ws.path / "context").is_dir()
    assert (ws.path / "scratch").is_dir()
    assert (ws.path / "output").is_dir()
    assert (ws.path / "status.json").exists()


def test_write_files(tmp_path):
    manager = WorkspaceManager(tmp_path)
    ws = manager.create_workspace("test:func", "func", "function", "lint")

    ws.write_context("source.py", "def func(): pass")
    ws.write_scratch("draft_1.py", "def func():\n    '''Doc.'''")
    ws.write_output("proposed.py", "def func():\n    '''Final doc.'''")

    state = ws.get_status()
    assert "source.py" in state.files["context"]
    assert "draft_1.py" in state.files["scratch"]
    assert "proposed.py" in state.files["output"]


def test_status_updates(tmp_path):
    manager = WorkspaceManager(tmp_path)
    ws = manager.create_workspace("test:func", "func", "function", "lint")

    ws.update_status(
        status=WorkspaceStatus.EXECUTING,
        phase="analyzing",
        current_step="Parsing AST",
        steps_completed=1,
        steps_total=5,
    )

    state = ws.get_status()
    assert state.status == WorkspaceStatus.EXECUTING
    assert state.phase == "analyzing"
    assert state.progress.current_step == "Parsing AST"
```

---

## 6. Phase 2: Neovim Plugin Core

**Goal**: Create plugin structure that manages workspaces instead of subprocesses.

### 6.1 Plugin Directory Structure

```bash
mkdir -p ~/.config/nvim/lua/remora/ui
touch ~/.config/nvim/lua/remora/init.lua
touch ~/.config/nvim/lua/remora/config.lua
touch ~/.config/nvim/lua/remora/workspace.lua
touch ~/.config/nvim/lua/remora/commands.lua
touch ~/.config/nvim/lua/remora/watcher.lua
touch ~/.config/nvim/lua/remora/ui/panel.lua
touch ~/.config/nvim/lua/remora/ui/tree.lua
touch ~/.config/nvim/lua/remora/ui/status.lua
```

### 6.2 Configuration Module

**File**: `~/.config/nvim/lua/remora/config.lua`

```lua
-- remora/config.lua
-- User configuration for workspace-based workflow

local M = {}

M.defaults = {
  -- Path to remora CLI
  cli_path = "remora",

  -- Workspace root (relative to project)
  workspace_dir = ".remora/workspaces",

  -- Default operations
  default_operations = { "docstring" },

  -- Panel settings
  panel = {
    width = 50,
    position = "right",  -- "left" or "right"
    auto_open = true,    -- Open panel when analysis starts
    auto_close = false,  -- Close panel when analysis completes
  },

  -- File watching
  watch = {
    enabled = true,
    debounce_ms = 100,
  },

  -- Status line integration
  statusline = {
    enabled = true,
    format = " %s %s",  -- icon, message
  },

  -- Keymaps
  keymaps = {
    analyze = "<leader>ra",
    accept = "<leader>ry",
    reject = "<leader>rn",
    toggle_panel = "<leader>rp",
    focus_panel = "<leader>rf",
  },

  -- Icons (requires nvim-web-devicons or nerd font)
  icons = {
    folder_closed = "",
    folder_open = "",
    file = "",
    status = {
      pending = "⏳",
      executing = "🔄",
      paused = "⏸️",
      completed = "✅",
      accepted = "✔️",
      rejected = "❌",
      error = "⚠️",
    },
  },

  debug = false,
}

M.options = {}

function M.setup(opts)
  M.options = vim.tbl_deep_extend("force", M.defaults, opts or {})
end

function M.get()
  if vim.tbl_isempty(M.options) then
    M.setup({})
  end
  return M.options
end

return M
```

### 6.3 Workspace Module

**File**: `~/.config/nvim/lua/remora/workspace.lua`

```lua
-- remora/workspace.lua
-- Interface to Remora workspaces

local M = {}

local config = require("remora.config")

-- Cache of workspace states
M.workspaces = {}
M.active_workspace = nil

function M.get_workspace_root()
  local cfg = config.get()
  return vim.fn.getcwd() .. "/" .. cfg.workspace_dir
end

function M.get_workspace_path(node_id)
  -- Sanitize node_id to match Python logic
  local safe_id = node_id:gsub("/", "_"):gsub("\\", "_"):gsub(":", "_")
  safe_id = safe_id:gsub("^%.", "")
  return M.get_workspace_root() .. "/" .. safe_id
end

function M.read_status(workspace_path)
  local status_file = workspace_path .. "/status.json"

  if vim.fn.filereadable(status_file) == 0 then
    return nil
  end

  local content = vim.fn.readfile(status_file)
  if #content == 0 then
    return nil
  end

  local ok, status = pcall(vim.json.decode, table.concat(content, "\n"))
  if not ok then
    return nil
  end

  return status
end

function M.list_workspaces()
  local root = M.get_workspace_root()

  if vim.fn.isdirectory(root) == 0 then
    return {}
  end

  local workspaces = {}
  local dirs = vim.fn.glob(root .. "/*", false, true)

  for _, dir in ipairs(dirs) do
    if vim.fn.isdirectory(dir) == 1 then
      local status = M.read_status(dir)
      if status then
        table.insert(workspaces, {
          path = dir,
          status = status,
        })
      end
    end
  end

  return workspaces
end

function M.get_active_workspace()
  if M.active_workspace then
    local status = M.read_status(M.active_workspace.path)
    if status then
      M.active_workspace.status = status
    end
  end
  return M.active_workspace
end

function M.set_active_workspace(workspace_path)
  local status = M.read_status(workspace_path)
  if status then
    M.active_workspace = {
      path = workspace_path,
      status = status,
    }
    return true
  end
  return false
end

function M.get_workspace_tree(workspace_path)
  -- Build a tree structure of workspace contents
  local tree = {
    name = vim.fn.fnamemodify(workspace_path, ":t"),
    path = workspace_path,
    type = "directory",
    children = {},
  }

  local function scan_dir(dir_path, parent)
    local items = vim.fn.glob(dir_path .. "/*", false, true)
    table.sort(items)

    for _, item in ipairs(items) do
      local name = vim.fn.fnamemodify(item, ":t")
      local is_dir = vim.fn.isdirectory(item) == 1

      local node = {
        name = name,
        path = item,
        type = is_dir and "directory" or "file",
        children = is_dir and {} or nil,
      }

      table.insert(parent.children, node)

      if is_dir then
        scan_dir(item, node)
      end
    end
  end

  scan_dir(workspace_path, tree)
  return tree
end

function M.create_workspace(node_id, node_name, node_type, operation, callback)
  local cfg = config.get()

  -- Call remora CLI to create workspace and start agent
  local cmd = string.format(
    "%s analyze --node-id '%s' --operations %s --workspace-mode",
    cfg.cli_path,
    node_id,
    operation
  )

  if cfg.debug then
    vim.notify("Running: " .. cmd, vim.log.levels.DEBUG)
  end

  -- Run async
  vim.fn.jobstart(cmd, {
    on_exit = function(_, exit_code, _)
      if exit_code == 0 then
        local workspace_path = M.get_workspace_path(node_id)
        M.set_active_workspace(workspace_path)
        if callback then
          callback(workspace_path)
        end
      else
        vim.notify("Failed to create workspace", vim.log.levels.ERROR)
      end
    end,
  })
end

function M.accept_workspace(workspace_path)
  local cfg = config.get()
  local status = M.read_status(workspace_path)

  if not status then
    vim.notify("Cannot read workspace status", vim.log.levels.ERROR)
    return
  end

  local cmd = string.format(
    "%s workspace accept %s",
    cfg.cli_path,
    status.node_id
  )

  vim.fn.system(cmd)

  if vim.v.shell_error == 0 then
    vim.notify("Changes accepted!", vim.log.levels.INFO)
    vim.cmd("edit!")  -- Reload buffer
  else
    vim.notify("Accept failed", vim.log.levels.ERROR)
  end
end

function M.reject_workspace(workspace_path)
  local cfg = config.get()
  local status = M.read_status(workspace_path)

  if not status then
    return
  end

  local cmd = string.format(
    "%s workspace reject %s",
    cfg.cli_path,
    status.node_id
  )

  vim.fn.system(cmd)
  vim.notify("Changes rejected", vim.log.levels.INFO)
end

return M
```

### 6.4 Commands Module

**File**: `~/.config/nvim/lua/remora/commands.lua`

```lua
-- remora/commands.lua
-- User commands for workspace-based workflow

local M = {}

local config = require("remora.config")
local workspace = require("remora.workspace")
local panel = require("remora.ui.panel")

function M.analyze(operations)
  local cfg = config.get()
  operations = operations or cfg.default_operations

  -- Get current buffer info
  local bufnr = vim.api.nvim_get_current_buf()
  local file_path = vim.api.nvim_buf_get_name(bufnr)

  if file_path == "" then
    vim.notify("No file in current buffer", vim.log.levels.ERROR)
    return
  end

  -- Get node at cursor
  local ts = require("remora.treesitter")
  local node_info = ts.get_node_at_cursor()

  if not node_info then
    vim.notify("No function or class at cursor", vim.log.levels.WARN)
    return
  end

  local node_id = file_path .. ":" .. node_info.name
  local operation = type(operations) == "table" and operations[1] or operations

  vim.notify(
    string.format("Creating workspace for %s...", node_info.name),
    vim.log.levels.INFO
  )

  -- Create workspace and open panel
  workspace.create_workspace(
    node_id,
    node_info.name,
    node_info.type,
    operation,
    function(workspace_path)
      -- Open panel showing this workspace
      if cfg.panel.auto_open then
        panel.open()
        panel.focus_workspace(workspace_path)
      end

      -- Start watching for changes
      local watcher = require("remora.watcher")
      watcher.watch(workspace_path)
    end
  )
end

function M.accept()
  local ws = workspace.get_active_workspace()

  if not ws then
    vim.notify("No active workspace", vim.log.levels.WARN)
    return
  end

  if ws.status.status ~= "completed" then
    vim.notify("Workspace not ready for accept", vim.log.levels.WARN)
    return
  end

  workspace.accept_workspace(ws.path)
  panel.refresh()
end

function M.reject()
  local ws = workspace.get_active_workspace()

  if not ws then
    vim.notify("No active workspace", vim.log.levels.WARN)
    return
  end

  workspace.reject_workspace(ws.path)
  panel.refresh()
end

function M.toggle_panel()
  panel.toggle()
end

function M.focus_panel()
  panel.focus()
end

function M.setup_commands()
  vim.api.nvim_create_user_command("RemoraAnalyze", function(opts)
    local operations = nil
    if opts.args ~= "" then
      operations = vim.split(opts.args, "%s+")
    end
    M.analyze(operations)
  end, {
    nargs = "*",
    desc = "Analyze current node with Remora",
  })

  vim.api.nvim_create_user_command("RemoraAccept", function()
    M.accept()
  end, {
    desc = "Accept workspace changes",
  })

  vim.api.nvim_create_user_command("RemoraReject", function()
    M.reject()
  end, {
    desc = "Reject workspace changes",
  })

  vim.api.nvim_create_user_command("RemoraPanel", function()
    M.toggle_panel()
  end, {
    desc = "Toggle Remora workspace panel",
  })

  vim.api.nvim_create_user_command("RemoraWorkspaces", function()
    local ws_list = workspace.list_workspaces()
    for _, ws in ipairs(ws_list) do
      local status = ws.status
      local icon = config.get().icons.status[status.status] or "?"
      print(string.format("%s %s - %s (%s)",
        icon, status.node_name, status.operation, status.status))
    end
  end, {
    desc = "List all Remora workspaces",
  })
end

return M
```

### 6.5 Plugin Entry Point

**File**: `~/.config/nvim/lua/remora/init.lua`

```lua
-- remora/init.lua
-- Workspace-based Remora plugin

local M = {}

function M.setup(opts)
  -- Initialize configuration
  local config = require("remora.config")
  config.setup(opts)

  -- Set up commands
  local commands = require("remora.commands")
  commands.setup_commands()

  -- Set up keymaps
  local cfg = config.get()

  if cfg.keymaps.analyze then
    vim.keymap.set("n", cfg.keymaps.analyze, ":RemoraAnalyze<CR>", {
      desc = "Analyze with Remora",
      silent = true,
    })
  end

  if cfg.keymaps.accept then
    vim.keymap.set("n", cfg.keymaps.accept, ":RemoraAccept<CR>", {
      desc = "Accept Remora changes",
      silent = true,
    })
  end

  if cfg.keymaps.reject then
    vim.keymap.set("n", cfg.keymaps.reject, ":RemoraReject<CR>", {
      desc = "Reject Remora changes",
      silent = true,
    })
  end

  if cfg.keymaps.toggle_panel then
    vim.keymap.set("n", cfg.keymaps.toggle_panel, ":RemoraPanel<CR>", {
      desc = "Toggle Remora panel",
      silent = true,
    })
  end

  -- Set up autocommands for workspace watching
  local augroup = vim.api.nvim_create_augroup("Remora", { clear = true })

  -- Watch for entering a workspace buffer
  vim.api.nvim_create_autocmd("BufEnter", {
    group = augroup,
    pattern = "*/.remora/workspaces/*",
    callback = function()
      -- Auto-set active workspace when entering workspace buffer
      local path = vim.fn.expand("%:p:h")
      while path:find("/.remora/workspaces/") do
        local status_file = path .. "/status.json"
        if vim.fn.filereadable(status_file) == 1 then
          require("remora.workspace").set_active_workspace(path)
          break
        end
        path = vim.fn.fnamemodify(path, ":h")
      end
    end,
  })
end

return M
```

---

## 7. Phase 3: Workspace View Panel

**Goal**: Create side panel that shows live workspace contents.

### 7.1 Panel Module

**File**: `~/.config/nvim/lua/remora/ui/panel.lua`

```lua
-- remora/ui/panel.lua
-- Side panel for workspace viewing

local M = {}

local config = require("remora.config")
local workspace = require("remora.workspace")

-- Panel state
M.bufnr = nil
M.winid = nil
M.is_open = false
M.current_workspace = nil
M.expanded = {}  -- Track expanded directories

-- Icons
local function get_icon(node)
  local cfg = config.get()
  if node.type == "directory" then
    if M.expanded[node.path] then
      return cfg.icons.folder_open
    else
      return cfg.icons.folder_closed
    end
  else
    return cfg.icons.file
  end
end

-- Render tree to lines
local function render_tree(tree, depth)
  depth = depth or 0
  local lines = {}
  local indent = string.rep("  ", depth)

  -- Render this node
  local icon = get_icon(tree)
  local line = string.format("%s%s %s", indent, icon, tree.name)
  table.insert(lines, { text = line, node = tree })

  -- Render children if expanded
  if tree.children and M.expanded[tree.path] then
    for _, child in ipairs(tree.children) do
      local child_lines = render_tree(child, depth + 1)
      for _, cl in ipairs(child_lines) do
        table.insert(lines, cl)
      end
    end
  end

  return lines
end

function M.create_buffer()
  if M.bufnr and vim.api.nvim_buf_is_valid(M.bufnr) then
    return M.bufnr
  end

  M.bufnr = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_option(M.bufnr, "buftype", "nofile")
  vim.api.nvim_buf_set_option(M.bufnr, "bufhidden", "hide")
  vim.api.nvim_buf_set_option(M.bufnr, "swapfile", false)
  vim.api.nvim_buf_set_option(M.bufnr, "filetype", "remora-panel")
  vim.api.nvim_buf_set_name(M.bufnr, "Remora Workspace")

  -- Set up keymaps for panel
  local opts = { buffer = M.bufnr, noremap = true, silent = true }

  -- Enter to open file or toggle directory
  vim.keymap.set("n", "<CR>", function()
    M.action_open()
  end, opts)

  -- o to open file
  vim.keymap.set("n", "o", function()
    M.action_open()
  end, opts)

  -- Space to toggle directory
  vim.keymap.set("n", "<Space>", function()
    M.action_toggle()
  end, opts)

  -- r to refresh
  vim.keymap.set("n", "r", function()
    M.refresh()
  end, opts)

  -- q to close panel
  vim.keymap.set("n", "q", function()
    M.close()
  end, opts)

  -- a to accept
  vim.keymap.set("n", "a", function()
    require("remora.commands").accept()
  end, opts)

  -- x to reject
  vim.keymap.set("n", "x", function()
    require("remora.commands").reject()
  end, opts)

  return M.bufnr
end

function M.open()
  if M.is_open then
    return
  end

  local cfg = config.get()

  M.create_buffer()

  -- Calculate window position
  local width = cfg.panel.width
  local win_opts = {
    split = cfg.panel.position,
    width = width,
  }

  -- Create split window
  if cfg.panel.position == "right" then
    vim.cmd("botright vsplit")
  else
    vim.cmd("topleft vsplit")
  end

  M.winid = vim.api.nvim_get_current_win()
  vim.api.nvim_win_set_buf(M.winid, M.bufnr)
  vim.api.nvim_win_set_width(M.winid, width)

  -- Window options
  vim.api.nvim_win_set_option(M.winid, "number", false)
  vim.api.nvim_win_set_option(M.winid, "relativenumber", false)
  vim.api.nvim_win_set_option(M.winid, "signcolumn", "no")
  vim.api.nvim_win_set_option(M.winid, "foldcolumn", "0")
  vim.api.nvim_win_set_option(M.winid, "winfixwidth", true)
  vim.api.nvim_win_set_option(M.winid, "cursorline", true)

  M.is_open = true
  M.refresh()

  -- Return to previous window
  vim.cmd("wincmd p")
end

function M.close()
  if not M.is_open then
    return
  end

  if M.winid and vim.api.nvim_win_is_valid(M.winid) then
    vim.api.nvim_win_close(M.winid, true)
  end

  M.winid = nil
  M.is_open = false
end

function M.toggle()
  if M.is_open then
    M.close()
  else
    M.open()
  end
end

function M.focus()
  if M.is_open and M.winid and vim.api.nvim_win_is_valid(M.winid) then
    vim.api.nvim_set_current_win(M.winid)
  else
    M.open()
    if M.winid then
      vim.api.nvim_set_current_win(M.winid)
    end
  end
end

function M.focus_workspace(workspace_path)
  M.current_workspace = workspace_path
  -- Expand root directory
  M.expanded[workspace_path] = true
  M.refresh()
end

function M.refresh()
  if not M.bufnr or not vim.api.nvim_buf_is_valid(M.bufnr) then
    return
  end

  local lines = {}
  local line_data = {}
  local cfg = config.get()

  -- Header with status
  local ws = workspace.get_active_workspace()

  if ws then
    local status = ws.status
    local icon = cfg.icons.status[status.status] or "?"

    table.insert(lines, "╭─ Remora Workspace ─────────────────╮")
    table.insert(lines, string.format("│ %s %s", icon, status.node_name))
    table.insert(lines, string.format("│   Operation: %s", status.operation))
    table.insert(lines, string.format("│   Status: %s", status.status))

    if status.progress and status.progress.current_step ~= "" then
      table.insert(lines, string.format("│   Step: %s", status.progress.current_step))
    end

    table.insert(lines, "╰────────────────────────────────────╯")
    table.insert(lines, "")

    -- File tree
    local tree = workspace.get_workspace_tree(ws.path)

    -- Auto-expand standard directories
    for _, subdir in ipairs({ "context", "scratch", "output", "logs" }) do
      local subpath = ws.path .. "/" .. subdir
      if vim.fn.isdirectory(subpath) == 1 then
        M.expanded[subpath] = true
      end
    end

    local tree_lines = render_tree(tree, 0)
    for _, tl in ipairs(tree_lines) do
      table.insert(lines, tl.text)
      table.insert(line_data, tl.node)
    end

  else
    table.insert(lines, "╭─ Remora Workspace ─────────────────╮")
    table.insert(lines, "│ No active workspace                │")
    table.insert(lines, "│                                    │")
    table.insert(lines, "│ Use :RemoraAnalyze to start        │")
    table.insert(lines, "╰────────────────────────────────────╯")
  end

  -- Keybindings help
  table.insert(lines, "")
  table.insert(lines, "─── Keybindings ───────────────────────")
  table.insert(lines, " <CR>/o  Open file")
  table.insert(lines, " <Space> Toggle directory")
  table.insert(lines, " r       Refresh")
  table.insert(lines, " a       Accept changes")
  table.insert(lines, " x       Reject changes")
  table.insert(lines, " q       Close panel")

  -- Write to buffer
  vim.api.nvim_buf_set_option(M.bufnr, "modifiable", true)
  vim.api.nvim_buf_set_lines(M.bufnr, 0, -1, false, lines)
  vim.api.nvim_buf_set_option(M.bufnr, "modifiable", false)

  -- Store line data for actions
  M.line_data = line_data
end

function M.get_node_at_cursor()
  local cursor = vim.api.nvim_win_get_cursor(M.winid)
  local line = cursor[1]

  -- Account for header lines (7 lines before tree starts)
  local tree_start = 8
  local tree_index = line - tree_start + 1

  if M.line_data and tree_index >= 1 and tree_index <= #M.line_data then
    return M.line_data[tree_index]
  end

  return nil
end

function M.action_open()
  local node = M.get_node_at_cursor()

  if not node then
    return
  end

  if node.type == "directory" then
    M.action_toggle()
  else
    -- Open file in previous window
    vim.cmd("wincmd p")
    vim.cmd("edit " .. vim.fn.fnameescape(node.path))
  end
end

function M.action_toggle()
  local node = M.get_node_at_cursor()

  if not node or node.type ~= "directory" then
    return
  end

  M.expanded[node.path] = not M.expanded[node.path]
  M.refresh()
end

return M
```

### 7.2 Syntax Highlighting for Panel

**File**: `~/.config/nvim/after/syntax/remora-panel.vim`

```vim
" Syntax highlighting for Remora panel

syntax match RemoraPanelBorder /[╭╮╰╯│─]/
syntax match RemoraPanelHeader /Remora Workspace/
syntax match RemoraPanelLabel /Operation:\|Status:\|Step:/
syntax match RemoraPanelFolder //
syntax match RemoraPanelFolderOpen //
syntax match RemoraPanelFile //
syntax match RemoraPanelKeyHelp /^\s*<.\+>/

" Status icons
syntax match RemoraPanelPending /⏳/
syntax match RemoraPanelExecuting /🔄/
syntax match RemoraPanelCompleted /✅/
syntax match RemoraPanelAccepted /✔️/
syntax match RemoraPanelRejected /❌/
syntax match RemoraPanelError /⚠️/

highlight RemoraPanelBorder guifg=#5c6370
highlight RemoraPanelHeader guifg=#61afef gui=bold
highlight RemoraPanelLabel guifg=#98c379
highlight RemoraPanelFolder guifg=#e5c07b
highlight RemoraPanelFolderOpen guifg=#e5c07b
highlight RemoraPanelFile guifg=#abb2bf
highlight RemoraPanelKeyHelp guifg=#5c6370

highlight RemoraPanelPending guifg=#e5c07b
highlight RemoraPanelExecuting guifg=#61afef
highlight RemoraPanelCompleted guifg=#98c379
highlight RemoraPanelAccepted guifg=#98c379
highlight RemoraPanelRejected guifg=#e06c75
highlight RemoraPanelError guifg=#e06c75
```

### 7.3 Verification

```vim
" Open panel manually
:RemoraPanel

" Should see empty state with help text
" Then create a workspace and verify tree appears
```

---

## 8. Phase 4: Tree-sitter Integration

**File**: `~/.config/nvim/lua/remora/treesitter.lua`

(Same as before, no changes needed)

```lua
-- remora/treesitter.lua
-- Extract AST node information using tree-sitter

local M = {}

local ts_utils = require("nvim-treesitter.ts_utils")

local TARGET_TYPES = {
  function_definition = "function",
  async_function_definition = "function",
  class_definition = "class",
}

function M.get_node_at_cursor()
  local bufnr = vim.api.nvim_get_current_buf()
  local node = ts_utils.get_node_at_cursor()

  if not node then
    return nil
  end

  local current = node
  while current do
    local node_type = current:type()
    if TARGET_TYPES[node_type] then
      return M.extract_node_info(current, bufnr)
    end
    current = current:parent()
  end

  return nil
end

function M.extract_node_info(node, bufnr)
  local node_type = node:type()
  local start_row, start_col, end_row, end_col = node:range()

  local name = nil
  for child in node:iter_children() do
    if child:type() == "identifier" or child:type() == "name" then
      name = vim.treesitter.get_node_text(child, bufnr)
      break
    end
  end

  if not name then
    return nil
  end

  return {
    name = name,
    type = TARGET_TYPES[node_type],
    start_row = start_row,
    end_row = end_row,
  }
end

return M
```

---

## 9. Phase 5: Live File Watching

**Goal**: Watch workspace directories and auto-refresh panel.

### 9.1 Watcher Module

**File**: `~/.config/nvim/lua/remora/watcher.lua`

```lua
-- remora/watcher.lua
-- Watch workspace directories for changes

local M = {}

local config = require("remora.config")
local uv = vim.loop

-- Active watchers
M.watchers = {}

function M.watch(workspace_path)
  local cfg = config.get()

  if not cfg.watch.enabled then
    return
  end

  -- Already watching?
  if M.watchers[workspace_path] then
    return
  end

  -- Create file system watcher
  local handle = uv.new_fs_event()

  if not handle then
    vim.notify("Failed to create file watcher", vim.log.levels.WARN)
    return
  end

  -- Debounce timer
  local timer = nil
  local debounce_ms = cfg.watch.debounce_ms

  local function on_change(err, filename, events)
    if err then
      return
    end

    -- Debounce: wait for debounce_ms before refreshing
    if timer then
      timer:stop()
    end

    timer = vim.defer_fn(function()
      -- Refresh panel
      vim.schedule(function()
        local panel = require("remora.ui.panel")
        if panel.is_open then
          panel.refresh()
        end
      end)
    end, debounce_ms)
  end

  -- Start watching (recursive)
  local success, err = handle:start(
    workspace_path,
    { recursive = true },
    vim.schedule_wrap(on_change)
  )

  if not success then
    vim.notify("Failed to watch: " .. (err or "unknown error"), vim.log.levels.WARN)
    return
  end

  M.watchers[workspace_path] = {
    handle = handle,
    timer = timer,
  }
end

function M.unwatch(workspace_path)
  local watcher = M.watchers[workspace_path]

  if watcher then
    if watcher.handle then
      watcher.handle:stop()
    end
    if watcher.timer then
      watcher.timer:stop()
    end
    M.watchers[workspace_path] = nil
  end
end

function M.unwatch_all()
  for path, _ in pairs(M.watchers) do
    M.unwatch(path)
  end
end

return M
```

### 9.2 Verification

```vim
" Create a workspace
:RemoraAnalyze docstring

" Panel should open
" Manually touch a file in the workspace
:!touch .remora/workspaces/*/context/test.txt

" Panel should refresh automatically
```

---

## 10. Phase 6: Context Providers

**Goal**: Agents write context files that user can see.

### 10.1 Update Agent to Write Context Files

The key change is modifying the agent bundles to write files to workspace directories instead of streaming events.

**File**: `agents/docstring/tools/gather_context.pym` (NEW)

```python
"""
Gather context for docstring generation.
Writes findings to workspace context/ directory.
"""
from grail import Input, Output
from pathlib import Path
import json

workspace_path: str = Input("Path to workspace directory")
node_source: str = Input("Source code of the target node")
file_path: str = Input("Path to the source file")

workspace = Path(workspace_path)
context_dir = workspace / "context"

# 1. Write the source code
(context_dir / "node_source.py").write_text(node_source)

# 2. Search for similar functions in codebase
# (This would use discovery/tree-sitter in real implementation)
related_funcs = []
# ... search logic ...

related_md = "# Related Functions\n\n"
for func in related_funcs:
    related_md += f"## {func['name']}\n```python\n{func['source']}\n```\n\n"

(context_dir / "related_functions.md").write_text(related_md)

# 3. Look for existing docstring patterns in project
patterns_md = "# Docstring Patterns in This Project\n\n"
# ... pattern analysis ...
(context_dir / "codebase_patterns.md").write_text(patterns_md)

# 4. Write metadata
metadata = {
    "node_name": "...",
    "node_type": "function",
    "file_path": file_path,
    "gathered_at": "...",
}
(context_dir / "node_metadata.json").write_text(json.dumps(metadata, indent=2))

Output({
    "success": True,
    "files_written": [
        "node_source.py",
        "related_functions.md",
        "codebase_patterns.md",
        "node_metadata.json",
    ]
})
```

**File**: `agents/docstring/tools/generate_draft.pym` (NEW)

```python
"""
Generate docstring draft.
Writes drafts to workspace scratch/ directory.
"""
from grail import Input, Output
from pathlib import Path

workspace_path: str = Input("Path to workspace directory")
draft_number: int = Input("Draft number", default=1)

workspace = Path(workspace_path)
scratch_dir = workspace / "scratch"

# Read context
context = {}
context_dir = workspace / "context"
if (context_dir / "node_source.py").exists():
    context["source"] = (context_dir / "node_source.py").read_text()
if (context_dir / "codebase_patterns.md").exists():
    context["patterns"] = (context_dir / "codebase_patterns.md").read_text()

# Generate draft (would use LLM in real implementation)
draft = f'''def {context.get("name", "function")}(...):
    """
    [Generated docstring goes here]

    Args:
        ...

    Returns:
        ...
    """
    ...
'''

draft_file = f"draft_{draft_number:03d}.py"
(scratch_dir / draft_file).write_text(draft)

Output({
    "success": True,
    "draft_file": draft_file,
})
```

**File**: `agents/docstring/tools/evaluate_draft.pym` (NEW)

```python
"""
Evaluate a draft and write evaluation.
"""
from grail import Input, Output
from pathlib import Path

workspace_path: str = Input("Path to workspace directory")
draft_number: int = Input("Draft number to evaluate")

workspace = Path(workspace_path)
scratch_dir = workspace / "scratch"

draft_file = f"draft_{draft_number:03d}.py"
draft_path = scratch_dir / draft_file

if not draft_path.exists():
    Output({"success": False, "error": "Draft not found"})

draft = draft_path.read_text()

# Evaluate (would use LLM in real implementation)
evaluation = f"""# Evaluation of Draft {draft_number}

## Strengths
- Clear parameter documentation
- Return type specified

## Weaknesses
- Missing examples
- Could be more concise

## Recommendation
Proceed to final output with minor refinements.
"""

eval_file = f"draft_{draft_number:03d}_eval.md"
(scratch_dir / eval_file).write_text(evaluation)

Output({
    "success": True,
    "evaluation_file": eval_file,
    "proceed_to_output": True,
})
```

**File**: `agents/docstring/tools/finalize_output.pym` (NEW)

```python
"""
Create final output from best draft.
"""
from grail import Input, Output
from pathlib import Path
import difflib

workspace_path: str = Input("Path to workspace directory")
selected_draft: int = Input("Draft number to finalize")
original_source: str = Input("Original source code")

workspace = Path(workspace_path)
scratch_dir = workspace / "scratch"
output_dir = workspace / "output"

# Read selected draft
draft_file = f"draft_{selected_draft:03d}.py"
draft = (scratch_dir / draft_file).read_text()

# Write proposed change
(output_dir / "proposed_change.py").write_text(draft)

# Generate diff
diff = difflib.unified_diff(
    original_source.splitlines(keepends=True),
    draft.splitlines(keepends=True),
    fromfile="original",
    tofile="proposed",
)
(output_dir / "proposed_change.diff").write_text("".join(diff))

# Write summary
summary = f"""# Proposed Changes

## Summary
Added comprehensive docstring to function.

## Changes Made
- Added Args documentation
- Added Returns documentation
- Added type hints in docstring

## Review
Please review the diff and accept or reject.
"""
(output_dir / "summary.md").write_text(summary)

Output({
    "success": True,
    "files": [
        "proposed_change.py",
        "proposed_change.diff",
        "summary.md",
    ]
})
```

### 10.2 Workspace-Mode CLI Flag

**File**: `src/remora/cli.py`

Add `--workspace-mode` flag:

```python
@app.command()
def analyze(
    paths: Annotated[list[Path], typer.Argument(...)],
    operations: Annotated[str, typer.Option("--operations", "-o")] = None,
    node_id: Annotated[str | None, typer.Option("--node-id", "-n")] = None,
    workspace_mode: Annotated[bool, typer.Option(
        "--workspace-mode",
        help="Write to workspace instead of stdout",
    )] = False,
):
    if workspace_mode and node_id:
        return asyncio.run(_analyze_workspace_mode(node_id, operations))
    # ... existing logic ...


async def _analyze_workspace_mode(node_id: str, operations: str | None) -> None:
    """Run analysis in workspace mode."""
    from remora.workspace_manager import WorkspaceManager, WorkspaceStatus

    # Parse node_id
    file_path, node_name = node_id.rsplit(":", 1)

    # Create workspace
    manager = WorkspaceManager(Path.cwd())
    workspace = manager.create_workspace(
        node_id=node_id,
        node_name=node_name,
        node_type="function",  # Would detect from AST
        operation=operations or "docstring",
    )

    # Write initial context
    source = Path(file_path).read_text()
    workspace.write_context("node_source.py", source)

    # Update status
    workspace.update_status(
        status=WorkspaceStatus.EXECUTING,
        phase="gathering_context",
        current_step="Reading source file",
        steps_completed=1,
        steps_total=5,
    )

    # Run agent with workspace path injected
    # ... agent execution logic ...

    # Mark completed
    workspace.mark_completed()
```

---

## 11. Phase 7: Demo Polish

### 11.1 Demo Target File

**File**: `examples/demo_target.py`

```python
"""
Demo target file for Remora MVP showcase.

This file contains intentionally imperfect code that demonstrates
the workspace-based agent workflow.
"""


def calculate_total(items, tax_rate, discount):
    # Calculate total with tax and discount
    subtotal = 0
    for item in items:
        subtotal += item["price"] * item["quantity"]

    if discount > 0:
        subtotal = subtotal - (subtotal * discount)

    total = subtotal + (subtotal * tax_rate)
    return total


class ShoppingCart:
    def __init__(self):
        self.items = []

    def add_item(self, name, price, quantity):
        self.items.append({
            "name": name,
            "price": price,
            "quantity": quantity
        })

    def get_total(self, tax_rate, discount):
        return calculate_total(self.items, tax_rate, discount)

    def remove_item(self, name):
        self.items = [i for i in self.items if i["name"] != name]
```

### 11.2 Demo Script

**File**: `scripts/demo_walkthrough.md`

```markdown
# Remora Workspace Demo Script

## Setup (before demo)

1. Clear any existing workspaces: `rm -rf .remora/workspaces/*`
2. Open Neovim with the demo file

## Demo Flow (2 minutes)

### Scene 1: Introduction (15 seconds)

> "Let me show you something different about Remora.
> Instead of a black-box AI that just gives you answers,
> Remora creates a workspace where you can watch
> the agent think."

### Scene 2: Start Analysis (30 seconds)

```vim
:e examples/demo_target.py
/def calculate_total<CR>
:RemoraAnalyze docstring
```

> "I've selected the calculate_total function.
> When I run RemoraAnalyze, watch what happens..."

**The panel slides in from the right**

> "A workspace was created just for this function.
> Let's look at what the agent is doing."

### Scene 3: Watch Context Gathering (30 seconds)

> "See the context/ folder? The agent is researching.
> It found the source code, looked for similar functions,
> and analyzed docstring patterns in my codebase."

**Click on related_functions.md**

> "It found these similar functions that might help
> it understand how I want my docstrings written."

### Scene 4: Watch Drafting (30 seconds)

> "Now in scratch/, the agent is drafting.
> Draft 1... let's see the evaluation..."

**Click on draft_001_eval.md**

> "It evaluated its own work and decided to refine.
> Draft 2 looks better."

### Scene 5: Review Output (20 seconds)

> "Finally, in output/, we have the proposal.
> Let me open the diff..."

**Click on proposed_change.diff**

> "Clean, well-documented docstring.
> If I like it, I press 'a' to accept."

### Scene 6: Accept (15 seconds)

```vim
a
```

> "Done. The docstring is now in my code.
> Every step was visible. No black box."
```

---

## 12. Demo Script (Quick Reference)

```vim
" === REMORA WORKSPACE DEMO ===

" 1. Open demo file
:e examples/demo_target.py

" 2. Navigate to function
/def calculate_total<CR>

" 3. Start analysis (panel auto-opens)
:RemoraAnalyze docstring

" 4. Watch files appear in panel
"    - context/ fills with research
"    - scratch/ shows drafts
"    - output/ shows final proposal

" 5. Browse files (press Enter on any file)

" 6. When complete (✅ appears):
a    " Accept changes

" 7. Verify
:e!  " Reload file

" === DEMO COMPLETE ===
```

---

## 13. Troubleshooting

### Panel Not Opening

```vim
:lua print(require("remora.ui.panel").is_open)
:RemoraPanel
```

### Workspace Not Created

```bash
ls -la .remora/workspaces/
remora workspace list
```

### File Watcher Not Working

```vim
:lua print(vim.inspect(require("remora.watcher").watchers))
```

### Agent Not Writing Files

```bash
# Check agent logs
cat .remora/workspaces/*/logs/agent.log
```

---

## Appendix A: Complete Plugin File Tree

```
~/.config/nvim/
├── lua/
│   └── remora/
│       ├── init.lua           # Entry point
│       ├── config.lua         # Configuration
│       ├── workspace.lua      # Workspace interface
│       ├── commands.lua       # :Remora* commands
│       ├── treesitter.lua     # AST integration
│       ├── watcher.lua        # File watching
│       └── ui/
│           ├── panel.lua      # Side panel
│           ├── tree.lua       # File tree renderer
│           └── status.lua     # Status line
└── after/
    └── syntax/
        └── remora-panel.vim   # Panel highlighting
```

---

## Appendix B: Key Differences from Event-Streaming Approach

| Aspect | Event Streaming | Workspace Files |
|--------|-----------------|-----------------|
| Communication | stdin/stdout | File system |
| Visibility | Events in floating window | Full file tree |
| Persistence | Events lost on close | Files persist |
| Interruptibility | Kill process | Pause/resume |
| Debugging | Parse event stream | Read files |
| User Agency | Watch passively | Browse actively |

---

*End of MVP Demo Guide*
