# Workspace Visibility & Materialization

Concept document for Cairn workspace observability and sandbox execution.

---

## Executive Summary

Cairn workspaces are currently opaque SQLite databases. This document proposes utilities for:

1. **Visibility** - Inspect workspace contents without extraction
2. **Materialization** - Extract workspace to real filesystem
3. **Sandboxing** - Execute code in isolated containers
4. **Bidirectional Sync** - Edit on disk, sync back to workspace

These capabilities enable debugging, testing, and development workflows that are currently impossible or cumbersome.

---

## Existing Capabilities (fsdantic)

Analysis of `.context/fsdantic/` reveals that **most primitives already exist**:

### Already Implemented

| Capability | Location | API |
|------------|----------|-----|
| Tree view | `files.py:578-637` | `FileManager.tree(path, max_depth)` |
| File listing | `files.py:452-480` | `FileManager.list_dir(path, output)` |
| File query | `files.py:521-562` | `FileManager.query(FileQuery)` |
| Materialization | `materialization.py:78-184` | `Materializer.materialize()` |
| Diff | `materialization.py:244-316` | `Materializer.diff(overlay, base)` |
| Merge | `overlay.py:98-153` | `OverlayOperations.merge()` |
| List changes | `overlay.py:289-334` | `OverlayOperations.list_changes()` |
| Reset overlay | `overlay.py:336-388` | `OverlayOperations.reset_overlay()` |
| KV store | `kv.py:133-455` | `KVManager` (get, set, delete, list) |
| Typed KV repos | `repository.py` | `TypedKVRepository` |

### Workspace Facade (workspace.py)

```python
class Workspace:
    @property
    def files(self) -> FileManager
    @property
    def kv(self) -> KVManager
    @property
    def overlay(self) -> OverlayManager
    @property
    def materialize(self) -> MaterializationManager
```

### MaterializationManager API

```python
class MaterializationManager:
    async def to_disk(
        self,
        target_path: Path,
        *,
        base: AgentFS | Workspace | None = None,
        filters: ViewQuery | None = None,
        clean: bool = True,
        allow_root: Path | None = None,
    ) -> MaterializationResult

    async def diff(
        self,
        base: AgentFS | Workspace,
        *,
        path: str = "/",
    ) -> list[FileChange]

    async def preview(
        self,
        base: AgentFS | Workspace,
        *,
        path: str = "/",
    ) -> list[FileChange]
```

### FileManager.tree() Output

```python
{
    "name": "src",
    "path": "/src",
    "type": "directory",
    "children": [
        {
            "name": "main.py",
            "path": "/src/main.py",
            "type": "file",
            "children": []
        },
        ...
    ]
}
```

---

## Gap Analysis

| Need | Status | Gap |
|------|--------|-----|
| Tree view | **Exists** | Need CLI wrapper |
| Diff view | **Exists** | Need CLI wrapper |
| Materialize to disk | **Exists** | Need CLI wrapper |
| Container sandbox | **Missing** | New implementation needed |
| Bidirectional sync | **Partial** | Overlay merge exists, need disk→workspace |
| Validation harness | **Missing** | New implementation needed |
| Web UI inspector | **Missing** | Future enhancement |

**Key insight:** The hard work is done. We primarily need CLI/service wrappers around existing fsdantic APIs.

---

## Proposed Architecture

### Layer 1: CLI Utilities

```
remora workspace <command>

Commands:
  tree       Print directory tree of workspace
  diff       Show changes between workspaces
  ls         List files in workspace directory
  cat        Print file contents from workspace
  materialize  Extract workspace to disk
  sync       Sync disk changes back to workspace
  sandbox    Run workspace in container
```

### Layer 2: Workspace Utilities Module

```python
# src/remora/workspace/utils.py

class WorkspaceInspector:
    """Read-only workspace inspection utilities."""
    
    def __init__(self, workspace_path: Path):
        self._workspace: Workspace | None = None
        self._path = workspace_path
    
    async def tree(
        self,
        path: str = "/",
        max_depth: int | None = None,
        format: Literal["tree", "json", "flat"] = "tree",
    ) -> str:
        """Return formatted directory tree."""
        ...
    
    async def diff(
        self,
        base_workspace_path: Path,
        path: str = "/",
    ) -> list[FileChange]:
        """Diff this workspace against another."""
        ...
    
    async def stats(self) -> WorkspaceStats:
        """Return workspace statistics."""
        ...
```

### Layer 3: Sandbox System

```python
# src/remora/workspace/sandbox.py

@dataclass
class SandboxConfig:
    base_image: str = "python:3.12-slim"
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    timeout: float = 300.0
    network: bool = False
    read_only: bool = False
    install_deps: bool = True
    env: dict[str, str] = field(default_factory=dict)

class WorkspaceSandbox:
    """Container-based sandbox for workspace execution."""
    
    def __init__(
        self,
        workspace: AgentWorkspace,
        config: SandboxConfig | None = None,
    ):
        ...
    
    async def __aenter__(self) -> "WorkspaceSandbox":
        """Materialize workspace and start container."""
        ...
    
    async def __aexit__(self, *args) -> None:
        """Stop container and optionally sync changes."""
        ...
    
    async def exec(
        self,
        command: str,
        *,
        timeout: float | None = None,
        capture: bool = True,
    ) -> ExecutionResult:
        """Execute command in sandbox."""
        ...
    
    async def sync_back(self) -> list[FileChange]:
        """Sync container changes back to workspace."""
        ...
```

### Layer 4: Validation Harness

```python
# src/remora/workspace/validation.py

@dataclass
class ValidationCheck:
    name: str
    passed: bool
    output: str
    duration: float

@dataclass  
class ValidationResult:
    checks: list[ValidationCheck]
    all_passed: bool
    total_duration: float

class WorkspaceValidator:
    """Validate agent-generated code in sandbox."""
    
    def __init__(
        self,
        workspace: AgentWorkspace,
        checks: list[str] | None = None,
    ):
        self.workspace = workspace
        self.checks = checks or ["syntax", "types", "tests", "lint"]
    
    async def validate(self) -> ValidationResult:
        """Run all validation checks in sandbox."""
        async with WorkspaceSandbox(self.workspace) as sandbox:
            results = []
            
            if "syntax" in self.checks:
                results.append(await self._check_syntax(sandbox))
            if "types" in self.checks:
                results.append(await self._check_types(sandbox))
            if "tests" in self.checks:
                results.append(await self._check_tests(sandbox))
            if "lint" in self.checks:
                results.append(await self._check_lint(sandbox))
            
            return ValidationResult(
                checks=results,
                all_passed=all(r.passed for r in results),
                total_duration=sum(r.duration for r in results),
            )
```

---

## CLI Interface Design

### `remora workspace tree`

```bash
# Basic tree
$ remora workspace tree .remora/stable.db
/
├── src/
│   ├── remora/
│   │   ├── __init__.py (142 B)
│   │   ├── core/
│   │   │   ├── agent_context.py (1.8 KB)
│   │   │   └── cairn_bridge.py (5.2 KB)
│   │   └── service/
│   │       └── api.py (4.1 KB)
│   └── tests/
│       └── ...
└── pyproject.toml (2.1 KB)

127 files, 342 KB total

# JSON output
$ remora workspace tree --format json .remora/stable.db
{"name": "/", "type": "directory", "children": [...]}

# Limited depth
$ remora workspace tree --depth 2 .remora/stable.db

# Compare to agent workspace (show diff markers)
$ remora workspace tree --diff .remora/agents/abc/workspace.db --base .remora/stable.db
/
├── src/remora/core/
│   ├── agent_context.py     [=] 1.8 KB
│   ├── cairn_bridge.py      [M] 5.4 KB  (+200 B)
│   └── new_feature.py       [+] 892 B
└── deleted_file.py          [-]
```

### `remora workspace diff`

```bash
$ remora workspace diff .remora/agents/abc/workspace.db .remora/stable.db

Changes from stable → agent:
  Modified: src/remora/core/cairn_bridge.py (+15 lines, -3 lines)
  Added:    src/remora/core/new_feature.py (892 bytes)
  Deleted:  src/remora/core/deprecated.py

# Show unified diff
$ remora workspace diff --unified .remora/agents/abc/workspace.db .remora/stable.db
--- a/src/remora/core/cairn_bridge.py
+++ b/src/remora/core/cairn_bridge.py
@@ -42,6 +42,10 @@
     def __init__(self):
+        self.new_field = True
```

### `remora workspace materialize`

```bash
# Extract to directory
$ remora workspace materialize .remora/agents/abc/workspace.db ./output/
Materializing workspace to ./output/
  src/remora/core/agent_context.py ... OK
  src/remora/core/cairn_bridge.py ... OK
  ...
127 files extracted (342 KB)

# With base layer
$ remora workspace materialize \
    --base .remora/stable.db \
    .remora/agents/abc/workspace.db \
    ./output/

# Changes only (no base files)
$ remora workspace materialize --changes-only .remora/agents/abc/workspace.db ./output/
```

### `remora workspace sandbox`

```bash
# Interactive shell
$ remora workspace sandbox .remora/agents/abc/workspace.db
Creating sandbox container...
Materializing workspace...
Container ready.

root@sandbox:/workspace# python -c "import mymodule; print(mymodule.version)"
1.0.0
root@sandbox:/workspace# pytest tests/
...
root@sandbox:/workspace# exit

Sync changes back to workspace? [y/N] y
Synced 2 modified files.

# Run single command
$ remora workspace sandbox --exec "pytest tests/" .remora/agents/abc/workspace.db
===== test session starts =====
...
===== 42 passed in 3.21s =====

# With options
$ remora workspace sandbox \
    --image python:3.11-slim \
    --memory 1g \
    --timeout 60 \
    --network \
    .remora/agents/abc/workspace.db
```

### `remora workspace sync`

```bash
# Sync disk changes to workspace
$ remora workspace sync ./edited-files/ .remora/agents/abc/workspace.db
Scanning for changes...
  Modified: src/foo.py
  Added:    src/new_file.py

Sync 2 files to workspace? [y/N] y
Synced.

# Preview only
$ remora workspace sync --dry-run ./edited-files/ .remora/agents/abc/workspace.db
Would sync:
  Modified: src/foo.py
  Added:    src/new_file.py
```

---

## Implementation Plan

### Phase 1: CLI Wrappers (Low Effort)

Wrap existing fsdantic APIs with CLI commands.

| Task | Effort | Dependencies |
|------|--------|--------------|
| `workspace tree` | 2h | FileManager.tree() |
| `workspace diff` | 2h | Materializer.diff() |
| `workspace ls` | 1h | FileManager.list_dir() |
| `workspace cat` | 1h | FileManager.read() |
| `workspace materialize` | 2h | MaterializationManager.to_disk() |
| CLI framework setup | 2h | typer/click |

**Total: ~10 hours**

### Phase 2: Bidirectional Sync (Medium Effort)

Enable disk → workspace sync.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Disk scanner | 2h | - |
| Change detector | 3h | - |
| Workspace writer | 2h | FileManager.write() |
| `workspace sync` command | 2h | Above |
| Conflict detection | 3h | - |

**Total: ~12 hours**

### Phase 3: Container Sandbox (Medium Effort)

Container-based execution environment.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Docker/Podman abstraction | 4h | - |
| Container lifecycle | 4h | - |
| Exec interface | 3h | - |
| Materialization integration | 2h | Phase 1 |
| Sync-back integration | 2h | Phase 2 |
| `workspace sandbox` command | 3h | Above |

**Total: ~18 hours**

### Phase 4: Validation Harness (Medium Effort)

Automated code validation.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Check framework | 3h | - |
| Syntax checker | 1h | - |
| Type checker (mypy) | 2h | - |
| Test runner (pytest) | 2h | - |
| Linter (ruff) | 1h | - |
| Result aggregation | 2h | - |
| Integration with agent loop | 4h | - |

**Total: ~15 hours**

### Phase 5: Web UI (Future)

Web-based workspace inspector.

| Task | Effort | Dependencies |
|------|--------|--------------|
| Tree component | 4h | - |
| File viewer | 4h | - |
| Diff viewer | 6h | - |
| Real-time updates | 4h | - |
| Integration | 4h | - |

**Total: ~22 hours**

---

## Integration Points

### With SwarmExecutor

```python
# After agent execution, validate output
result = await executor.run_agent(node, trigger_event)

if config.validate_agent_output:
    validator = WorkspaceValidator(workspace)
    validation = await validator.validate()
    
    if not validation.all_passed:
        # Log failures, potentially retry or escalate
        logger.warning(f"Agent output validation failed: {validation}")
```

### With AgentContext

```python
# Add workspace inspection to agent tools
async def inspect_workspace() -> dict:
    """Let agent inspect its own workspace state."""
    inspector = WorkspaceInspector(workspace)
    return await inspector.stats()
```

### With Event System

```python
# Emit events on workspace changes
@event_bus.on("agent.completed")
async def on_agent_completed(event: AgentCompletedEvent):
    changes = await workspace.materialize.diff(stable_workspace)
    await event_bus.emit(WorkspaceChangedEvent(
        agent_id=event.agent_id,
        changes=changes,
    ))
```

---

## Security Considerations

### Container Sandbox

| Concern | Mitigation |
|---------|------------|
| Network access | Default `--network=none` |
| Filesystem escape | Mount workspace read-only by default |
| Resource exhaustion | Memory/CPU limits |
| Long-running processes | Timeout enforcement |
| Privilege escalation | `--no-new-privileges` |
| Host access | No volume mounts outside workspace |

### Materialization

| Concern | Mitigation |
|---------|------------|
| Path traversal | Validate target within allow_root |
| Symlink attacks | Don't follow symlinks |
| Overwrite sensitive files | Require explicit --force for existing dirs |
| Disk exhaustion | Optional size limits |

---

## Open Questions

1. **Container runtime:** Docker vs Podman vs both?
   - Docker more common, Podman rootless better for security
   - Recommendation: Abstract with fallback

2. **Materialization persistence:** Temp dir vs configurable?
   - Temp safer (auto-cleanup)
   - Configurable useful for debugging
   - Recommendation: Temp by default, --output-dir option

3. **Sync conflict resolution:** How to handle disk vs workspace conflicts?
   - Options: ours/theirs/interactive/merge
   - Recommendation: Start with interactive, add merge later

4. **Validation scope:** What checks by default?
   - Recommendation: syntax only by default, opt-in for types/tests/lint

5. **Integration depth:** How tightly to integrate with agent loop?
   - Recommendation: Start as standalone utilities, integrate gradually

---

## Summary

**What we're building:**
1. CLI tools for workspace inspection (`tree`, `diff`, `ls`, `cat`)
2. CLI tools for workspace extraction (`materialize`, `sync`)
3. Container sandbox for safe code execution
4. Validation harness for agent output quality

**Key insight:** fsdantic already provides the core primitives. We're building user-facing tools on top.

**Estimated total effort:** ~77 hours across 5 phases

**Recommended priority:**
1. Phase 1 (CLI wrappers) - Immediate value, low effort
2. Phase 3 (Sandbox) - Enables safe testing
3. Phase 2 (Sync) - Enables development workflow
4. Phase 4 (Validation) - Quality gate for agents
5. Phase 5 (Web UI) - Future polish

---

## Appendix: fsdantic API Reference

### FileManager

```python
async def tree(path: str = "/", max_depth: int | None = None) -> dict[str, Any]
async def list_dir(path: str, output: Literal["name", "relative", "full"] = "name") -> list[str]
async def read(path: str, mode: Literal["text", "binary"] = "text") -> str | bytes
async def write(path: str, content: str | bytes) -> None
async def exists(path: str) -> bool
async def stat(path: str) -> FileStats
async def search(pattern: str, recursive: bool = True) -> list[str]
async def query(query: FileQuery) -> list[FileEntry]
async def traverse_files(root: str, recursive: bool, include_stats: bool) -> AsyncIterator[tuple[str, Any]]
```

### Materializer

```python
async def materialize(
    agent_fs: AgentFS,
    target_path: Path,
    base_fs: AgentFS | None = None,
    filters: ViewQuery | None = None,
    clean: bool = True,
    allow_root: Path | None = None,
) -> MaterializationResult

async def diff(
    overlay_fs: AgentFS,
    base_fs: AgentFS,
    path: str = "/",
) -> list[FileChange]
```

### OverlayOperations

```python
async def merge(
    source: AgentFS,
    target: AgentFS,
    path: str = "/",
    strategy: MergeStrategy | None = None,
) -> MergeResult

async def list_changes(overlay: AgentFS, path: str = "/") -> list[str]
async def reset_overlay(overlay: AgentFS, paths: list[str] | None = None) -> int
```

### KVManager

```python
async def get(key: str, default: Any = _MISSING) -> Any
async def set(key: str, value: Any) -> None
async def delete(key: str) -> bool
async def exists(key: str) -> bool
async def list(prefix: str = "") -> list[dict[str, Any]]
def repository(prefix: str = "", model_type: type[BaseModel] | None = None) -> TypedKVRepository
def transaction() -> KVTransaction
```
