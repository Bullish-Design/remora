# Cairn Integration Opportunities

Identified gaps and enhancement possibilities.

---

## 1. Current Gaps

### 1.1 Private API Usage

**Issue:** `cairn_bridge.py` uses `workspace_manager._open_workspace()` (underscore-prefixed).

**Risk:** Private APIs may change without notice.

**Recommendation:** 
- Check if Cairn has a public API for workspace opening
- If not, request one from Cairn maintainers
- Document the private API dependency

### 1.2 No KV Store Usage in Core

**Current State:** KV operations are only tested (`test_kv_operations.py`) but not used in core agent execution.

**Opportunity:** The KV store could be used for:
- Agent state persistence
- Inter-agent communication
- Caching computed results
- Checkpointing long-running tasks

**Example Use Case:**
```python
# Store agent state between turns
repo = workspace.cairn.kv.repository(prefix="state", model_type=AgentState)
await repo.set(agent_id, state)
```

### 1.3 No File Watch/Subscription

**Current State:** File sync is pull-based (mtime check on sync).

**Opportunity:** If Cairn supports file watchers, could enable:
- Real-time file change detection
- Automatic re-sync on external edits
- Event-driven agent triggers

### 1.4 Limited Merge Strategy

**Current State:** Agent writes are isolated (CoW). No merge-back to stable.

**Opportunity:** Implement merge strategies:
- Agent can "commit" changes to stable
- Conflict detection and resolution
- Multi-agent collaborative editing

---

## 2. Enhancement Ideas

### 2.1 Workspace Snapshots

**Idea:** Create point-in-time snapshots of agent workspaces.

**Benefits:**
- Rollback capability
- Audit trail
- Debugging aid

**Implementation:**
```python
class CairnWorkspaceService:
    async def snapshot(self, agent_id: str, label: str) -> str:
        """Create a named snapshot of agent workspace."""
        ...
```

### 2.2 Lazy File Loading

**Current:** All project files synced at initialization.

**Improvement:** Lazy load files on first access.

**Benefits:**
- Faster startup for large projects
- Reduced memory usage
- Only sync what's needed

### 2.3 File Versioning

**Idea:** Track file versions in workspace.

**Benefits:**
- Diff between versions
- Undo/redo support
- History for agents to reference

### 2.4 Shared Workspaces

**Current:** Each agent has isolated workspace.

**Enhancement:** Allow shared workspaces between related agents.

**Use Case:** 
- Parent/child agents share workspace
- Collaborative editing between siblings

### 2.5 Workspace Templates

**Idea:** Pre-configured workspaces for different agent types.

**Benefits:**
- Faster agent spawning
- Consistent starting state
- Reduced sync overhead

---

## 3. Missing Cairn Features (if available)

### 3.1 Transactions

If Cairn supports transactions:
```python
async with workspace.transaction():
    await workspace.files.write("a.py", content_a)
    await workspace.files.write("b.py", content_b)
    # Atomic commit or rollback
```

### 3.2 Compression

If Cairn supports compression:
- Enable for large project sync
- Reduce disk usage

### 3.3 Encryption

If Cairn supports encryption:
- Encrypt workspace at rest
- Secure sensitive project files

---

## 4. Architectural Improvements

### 4.1 Abstract Workspace Interface

**Current:** Direct coupling to Cairn's API.

**Improvement:** Define `WorkspaceProtocol`:
```python
class WorkspaceProtocol(Protocol):
    async def read(self, path: str) -> str: ...
    async def write(self, path: str, content: str) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def list_dir(self, path: str) -> list[str]: ...
```

**Benefits:**
- Testability with mock implementations
- Alternative backends possible
- Cleaner interface

### 4.2 Workspace Middleware

**Idea:** Add hooks/middleware for workspace operations.

**Use Cases:**
- Logging all file operations
- Access control checks
- Rate limiting
- Metrics collection

```python
class LoggingMiddleware:
    async def on_write(self, path: str, content: str) -> None:
        logger.info(f"Write to {path}: {len(content)} bytes")
```

### 4.3 Workspace Events

**Idea:** Emit events on workspace operations.

**Benefits:**
- Real-time UI updates
- Audit logging
- Reactive agent triggers

```python
@event_bus.on("workspace.write")
async def handle_write(event: WorkspaceWriteEvent):
    # Notify UI, trigger agents, etc.
```

---

## 5. Performance Opportunities

### 5.1 Parallel File Sync

**Current:** Sequential file sync in `_sync_project_to_workspace`.

**Improvement:** Use `asyncio.gather()` for parallel writes:
```python
tasks = [
    self._stable_workspace.files.write(path, content)
    for path, content in files_to_sync
]
await asyncio.gather(*tasks)
```

### 5.2 Connection Pooling

**Check:** Does Cairn's WorkspaceManager pool connections?

If not, consider:
- Pooling workspace connections
- Reusing connections across operations

### 5.3 Caching Layer

**Idea:** Cache frequently accessed files in memory.

```python
class CachedAgentWorkspace(AgentWorkspace):
    _cache: dict[str, str]
    
    async def read(self, path: str) -> str:
        if path in self._cache:
            return self._cache[path]
        content = await super().read(path)
        self._cache[path] = content
        return content
```

---

## 6. Documentation Gaps

### 6.1 Cairn API Reference

**Missing:** Documentation of which Cairn APIs Remora depends on.

**Action:** Create `CAIRN_API_CONTRACT.md` listing:
- Required Cairn version
- Expected API methods
- Behavior assumptions

### 6.2 Workspace Lifecycle

**Missing:** Clear documentation of workspace lifecycle.

**Action:** Document in architecture docs:
- When workspaces are created
- When they're synced
- When they're cleaned up

### 6.3 Error Handling

**Missing:** Documentation of Cairn error codes.

**Action:** Document error handling strategy:
- Which errors are recoverable
- How to handle workspace corruption
- Cleanup procedures

---

## 7. Priority Matrix

| Opportunity | Impact | Effort | Priority |
|-------------|--------|--------|----------|
| Fix private API usage | High | Low | P0 |
| Abstract WorkspaceProtocol | High | Medium | P1 |
| KV store for state | High | Medium | P1 |
| Lazy file loading | Medium | Medium | P2 |
| Workspace snapshots | Medium | High | P2 |
| File versioning | Medium | High | P3 |
| Parallel file sync | Low | Low | P3 |
| Workspace templates | Low | Medium | P3 |

---

## 8. Next Steps

1. **Immediate:** Audit Cairn for public workspace opening API
2. **Short-term:** Implement `WorkspaceProtocol` abstraction
3. **Medium-term:** Add KV store usage for agent state
4. **Long-term:** Evaluate workspace snapshots and versioning
