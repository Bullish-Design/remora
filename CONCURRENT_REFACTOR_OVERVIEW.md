# Concurrent Processing Refactor Overview

## Executive Summary

This document outlines the architectural changes required to enable **concurrent file indexing and change processing** in the Remora Hub daemon. Currently, all file processing happens sequentially, which causes:

1. **Slow cold-start indexing**: ~80s for 100 files instead of potential ~15-20s
2. **Lost file change events**: Only ~60% of concurrent changes are processed
3. **Poor scalability**: Linear performance degradation with codebase size

The codebase already has precedent for parallel processing in `TreeSitterDiscoverer` (uses `ThreadPoolExecutor`), so this approach is validated.

---

## Current Architecture Analysis

### 1. Cold Start Indexing (Sequential)

**Location**: `src/remora/hub/daemon.py:125-181`

```python
async def _cold_start_index(self) -> None:
    for py_file in self.project_root.rglob("*.py"):  # Sequential!
        # ...
        await self._index_file(py_file, "cold_start")  # Awaited one-by-one
```

**Bottlenecks**:
- Each file is processed sequentially in a `for` loop
- No batching or parallel execution
- Hash computation and store operations are also sequential

### 2. File Change Handling (Sequential)

**Location**: `src/remora/hub/daemon.py:197-248`

```python
async def _handle_file_change(self, change_type: str, path: Path) -> None:
    # Sequential action execution
    for action in actions:
        result = await action.execute(context)  # Awaited one-by-one
```

**Location**: `src/remora/hub/watcher.py:68-99`

```python
async for changes in awatch(...):
    for change_type, path_str in changes:
        await self.callback(change, path)  # Sequential processing
```

**Bottlenecks**:
- File watcher processes changes one-at-a-time
- Each change handler awaits full completion before next
- No task queue or worker pool

### 3. Store Operations

**Location**: `src/remora/hub/store.py`

The store uses `fsdantic` with `TypedKVRepository`. Key methods:
- `set_many()` - Already batched for nodes (line 114-124)
- `get_many()` - Already batched for retrieval (line 80-100)
- `invalidate_file()` - Sequential get + delete (line 169-193)

**Assessment**: Store appears to support batch operations. This relies on the underlying AgentFS, which is a solid architectural decision. 

---

## Proposed Architecture

### Option A: ThreadPoolExecutor (Recommended)

Leverage existing pattern from `TreeSitterDiscoverer`:

```python
import concurrent.futures

async def _cold_start_index(self) -> None:
    files = [f for f in self.project_root.rglob("*.py") if should_process(f)]
    
    # Process files in parallel using thread pool
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # Submit all tasks
        futures = {
            executor.submit(self._index_file_sync, f, "cold_start"): f 
            for f in files
        }
        
        # Collect results as they complete
        for future in concurrent.futures.as_completed(futures):
            file = futures[future]
            try:
                await future.result()  # Raises if failed
            except Exception as exc:
                logger.exception("Failed to index %s", file)
```

**Pros**:
- Matches existing pattern in discoverer.py
- No asyncio concurrency complexity
- Good for CPU-bound AST parsing

**Cons**:
- Need to handle async/sync boundary carefully
- Thread pool size needs tuning

### Option B: asyncio Task Queue

Use asyncio-native concurrency:

```python
import asyncio
from collections import deque

class HubDaemon:
    def __init__(self, ...):
        self._task_queue: asyncio.Queue[Path] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task] = []
    
    async def _start_workers(self, num_workers: int = 4):
        """Start worker coroutines."""
        for _ in range(num_workers):
            task = asyncio.create_task(self._worker_loop())
            self._worker_tasks.append(task)
    
    async def _worker_loop(self):
        """Worker coroutine that processes files from queue."""
        while not self._shutdown_event.is_set():
            try:
                path = await asyncio.wait_for(
                    self._task_queue.get(), 
                    timeout=1.0
                )
                await self._index_file(path, "file_change")
            except asyncio.TimeoutError:
                continue
    
    async def _handle_file_change(self, change_type: str, path: Path):
        """Add change to queue instead of processing directly."""
        await self._task_queue.put(path)
```

**Pros**:
- True async concurrency
- Better resource utilization
- Natural backpressure handling

**Cons**:
- More complex refactoring
- Need to handle store concurrency
- More testing required

---

## Required Changes

### Phase 1: Cold Start Parallelization

#### 1.1 Add ThreadPoolExecutor to HubDaemon

**File**: `src/remora/hub/daemon.py`

```python
import concurrent.futures
from typing import Literal

class HubDaemon:
    # Add config
    max_indexing_workers: int = 8  # Configurable
    
    async def _cold_start_index(self) -> None:
        # Collect all files first
        files = []
        for py_file in self.project_root.rglob("*.py"):
            if self._shutdown_event.is_set():
                break
            if self.rules.should_process_file(py_file, HubWatcher.DEFAULT_IGNORE_PATTERNS):
                files.append(py_file)
        
        # Pre-filter unchanged files
        files_to_index = []
        for f in files:
            file_hash = self._hash_file(f)
            existing = await self.store.get_file_index(str(f))
            if not existing or existing.file_hash != file_hash:
                files_to_index.append(f)
        
        # Process in parallel batches
        if files_to_index:
            await self._index_files_parallel(files_to_index, "cold_start")
        
        # ... rest of method unchanged
    
    async def _index_files_parallel(
        self, 
        files: list[Path], 
        update_source: Literal["cold_start", "file_change"]
    ) -> None:
        """Index multiple files in parallel using thread pool."""
        
        def process_file(path: Path) -> tuple[Path, int, float]:
            """Synchronous file processing for thread pool."""
            import time
            start = time.monotonic()
            
            # Use index_file_simple directly (it's sync)
            from remora.hub.indexer import index_file_simple
            from remora.hub.models import FileIndex
            
            # Get or create event loop for thread
            loop = asyncio.new_event_loop()
            try:
                count = loop.run_until_complete(index_file_simple(path, self.store))
            finally:
                loop.close()
            
            duration = time.monotonic() - start
            return (path, count, duration)
        
        # Process in parallel
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_indexing_workers
        ) as executor:
            futures = {
                executor.submit(process_file, f): f 
                for f in files
            }
            
            indexed = 0
            errors = 0
            for future in concurrent.futures.as_completed(futures):
                path = futures[future]
                try:
                    _, count, duration = future.result()
                    self._metrics.record_file_indexed(count, duration)
                    indexed += 1
                except Exception as exc:
                    logger.exception("Error indexing %s", path)
                    self._metrics.record_file_failed()
                    errors += 1
            
            logger.info(
                "Parallel indexing complete: %s files, %s errors",
                indexed, errors
            )
```

#### 1.2 Update Indexer to Support Both Sync and Async

**File**: `src/remora/hub/indexer.py`

```python
# Already async - no changes needed
# But ensure it uses set_many() which is already batched
```

### Phase 2: File Change Queue

#### 2.1 Add Task Queue to HubDaemon

**File**: `src/remora/hub/daemon.py`

```python
class HubDaemon:
    def __init__(self, ...):
        # ... existing init ...
        self._change_queue: asyncio.Queue[tuple[str, Path]] = asyncio.Queue(
            maxsize=1000  # Backpressure limit
        )
        self._change_workers: list[asyncio.Task] = []
        self.max_change_workers: int = 4
    
    async def run(self):
        # ... existing setup ...
        
        # Start change workers
        await self._start_change_workers()
        
        # ... rest unchanged
    
    async def _start_change_workers(self):
        """Start workers to process file changes concurrently."""
        for i in range(self.max_change_workers):
            task = asyncio.create_task(self._change_worker(i))
            self._change_workers.append(task)
    
    async def _change_worker(self, worker_id: int):
        """Worker coroutine that processes file changes from queue."""
        logger.debug("Change worker %s started", worker_id)
        
        while not self._shutdown_event.is_set():
            try:
                # Wait for change with timeout to check shutdown
                change_type, path = await asyncio.wait_for(
                    self._change_queue.get(),
                    timeout=1.0
                )
                
                # Process the change
                await self._handle_file_change_internal(change_type, path)
                
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.exception("Error in change worker %s", worker_id)
        
        logger.debug("Change worker %s stopped", worker_id)
    
    async def _handle_file_change(self, change_type: str, path: Path) -> None:
        """Queue a file change for processing instead of processing directly."""
        # Check queue size for backpressure
        if self._change_queue.full():
            logger.warning("Change queue full, dropping change for %s", path)
            return
        
        await self._change_queue.put((change_type, path))
    
    async def _handle_file_change_internal(
        self, 
        change_type: str, 
        path: Path
    ) -> None:
        """Actual file change processing (moved from _handle_file_change)."""
        # ... existing logic from current _handle_file_change ...
        self._metrics.record_file_change()
        store = self.store
        if store is None:
            return
        # ... rest of existing implementation
```

### Phase 3: Store Concurrency

#### 3.1 Add Locking for Critical Sections

**File**: `src/remora/hub/store.py`

The store may need locking for concurrent operations. Investigate:

```python
import asyncio
from typing import Optional

class NodeStateStore:
    def __init__(self, workspace: Workspace) -> None:
        # ... existing init ...
        self._lock = asyncio.Lock()  # Add for operations that need atomicity
    
    async def invalidate_and_set(
        self, 
        file_path: str, 
        states: list[NodeState],
        file_index: FileIndex
    ) -> None:
        """Atomic operation: invalidate + set + set_file_index."""
        async with self._lock:
            await self.invalidate_file(file_path)
            if states:
                await self.set_many(states)
            await self.set_file_index(file_index)
```

### Phase 4: Configuration

#### 4.1 Add New Config Options

**File**: `src/remora/config.py`

```python
class HubConfig(BaseModel):
    # ... existing fields ...
    
    # New concurrency settings
    max_indexing_workers: int = Field(
        default=8,
        description="Max parallel workers for cold-start indexing"
    )
    max_change_workers: int = Field(
        default=4,
        description="Max parallel workers for file change processing"
    )
    change_queue_size: int = Field(
        default=1000,
        description="Max size of file change queue (backpressure)"
    )
```

---

## Testing Strategy

### Unit Tests

1. **Test ThreadPoolExecutor integration**
   - Mock file system, verify parallel execution
   - Test error handling in worker threads

2. **Test asyncio queue**
   - Test backpressure behavior
   - Test worker shutdown

3. **Test store concurrency**
   - Concurrent reads/writes
   - Verify no race conditions

### Integration Tests

1. **Update `test_large_codebase_indexing`**
   ```python
   # Reduce time assertion since it should be faster now
   assert elapsed < 20.0, f"Indexing took {elapsed:.1f}s, expected < 20s"
   ```

2. **Update `test_concurrent_file_changes`**
   ```python
   # Should now process all 20 changes
   assert len(added_funcs) == 20
   ```

3. **Add new stress tests**
   - 500 files concurrent indexing
   - 100 concurrent file changes

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Thread safety in store | Medium | Add locking, test thoroughly |
| Memory pressure | Low | Use bounded queue, monitor |
| Race conditions | Medium | Comprehensive testing |
| Backpressure | Low | Queue size limits |
| Complexity increase | Medium | Phased rollout |

---

## Implementation Plan

### Phase 1 (Low Risk)
- [ ] Add `max_indexing_workers` config
- [ ] Implement parallel cold-start indexing
- [ ] Update stress tests

### Phase 2 (Medium Risk) 
- [ ] Add change queue
- [ ] Implement worker pool
- [ ] Add backpressure handling

### Phase 3 (If Needed)
- [ ] Add store locking
- [ ] Performance tuning

### Phase 4 (Optimization)
- [ ] Config tuning
- [ ] Monitoring/metrics

---

## Estimated Impact

| Metric | Current | Expected | Improvement |
|--------|---------|----------|-------------|
| 100 file cold start | ~80s | ~15-20s | **4-5x faster** |
| File change processing | ~60% | 100% | **No drops** |
| CPU utilization | ~10-20% | ~60-80% | **Better use** |

---

## References

- Existing parallel implementation: `src/remora/discovery/discoverer.py:125`
- Asyncio patterns: `src/remora/orchestrator.py:123` (semaphore)
- Store operations: `src/remora/hub/store.py`
