# Affected Files in Remora

## Summary

| File | Priority | Change Type | Effort |
|------|----------|-------------|--------|
| `pyproject.toml` | P0 | Version bump | Low |
| `src/remora/core/kernel_factory.py` | P0 | Major rewrite | Medium |
| `src/remora/core/manifest.py` | P0 | New file | Medium |
| `src/remora/core/swarm_executor.py` | P0 | Import update | Low |
| `src/remora/core/events.py` | P1 | Cosmetic | Low |
| `src/remora/core/chat.py` | P2 | No change | None |
| `src/remora/core/event_bus.py` | P2 | No change | None |
| `src/remora/core/event_store.py` | P2 | No change | None |
| `src/remora/lsp/runner.py` | P2 | No change | None |
| `src/remora/core/tools/*.py` | P2 | No change | None |

---

## P0: Critical Changes

### 1. pyproject.toml

**Change:** Update dependency version

```toml
# Before
"structured-agents>=0.3.4",
"structured-agents[grammar,vllm]>=0.3",

# After
"structured-agents>=0.4.0",
"structured-agents[grammar,vllm]>=0.4",
```

**Location:** Lines 21, 33

---

### 2. src/remora/core/kernel_factory.py

**Change:** Remove ModelAdapter, update imports, rewrite create_kernel

**Current imports (BROKEN in v0.4):**
```python
from structured_agents.agent import get_response_parser        # REMOVED
from structured_agents.client import build_client              # OK
from structured_agents.grammar.pipeline import ConstraintPipeline  # OK
from structured_agents.kernel import AgentKernel               # OK
from structured_agents.models.adapter import ModelAdapter      # REMOVED
```

**New imports:**
```python
from structured_agents import (
    AgentKernel,
    build_client,
    get_response_parser,
    ConstraintPipeline,
    NullObserver,
)
```

**Function rewrite:** See `KERNEL_FACTORY.md` for complete diff.

---

### 3. src/remora/core/manifest.py (NEW FILE)

**Change:** Create new file to replace `load_manifest` from structured-agents

**Purpose:** Load bundle manifests from YAML files

**Implementation:** See `MANIFEST_IMPL.md`

---

### 4. src/remora/core/swarm_executor.py

**Change:** Update import for `load_manifest`

**Current import (BROKEN in v0.4):**
```python
from structured_agents.agent import load_manifest  # REMOVED
```

**New import:**
```python
from remora.core.manifest import load_manifest  # Local implementation
```

**Location:** Line 15

**Note:** The rest of the file should work unchanged. The imports for
`build_client` and `Message` are still valid.

---

## P1: Minor Changes

### 5. src/remora/core/events.py

**Change:** Import cosmetic (still works, but could be cleaner)

**Current imports (WORK but verbose):**
```python
from structured_agents.events import (
    KernelStartEvent,
    KernelEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    TurnCompleteEvent,
)
```

**Alternative (cleaner):**
```python
from structured_agents import (
    KernelStartEvent,
    KernelEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    TurnCompleteEvent,
)
```

**Note:** Both work. The existing imports are fine.

---

## P2: No Changes Required

These files use stable APIs that haven't changed:

### src/remora/core/chat.py

Uses:
- `Tool` protocol ✓
- `Message`, `ToolCall`, `ToolResult`, `ToolSchema` types ✓
- `create_kernel()` from local kernel_factory ✓

### src/remora/core/event_bus.py

Uses:
- `Event` type alias ✓
- `Observer` protocol (implements it) ✓

### src/remora/core/event_store.py

Uses:
- `Event` type alias ✓

### src/remora/lsp/runner.py

Uses:
- `build_client()` ✓ (imported inside function)

### src/remora/core/tools/*.py

Uses:
- `ToolCall`, `ToolResult`, `ToolSchema` ✓

### src/remora/ui/projector.py

Uses:
- `Event` type alias ✓

---

## Verification Commands

After making changes:

```bash
# Check imports resolve
uv run python -c "from remora.core.kernel_factory import create_kernel; print('OK')"

# Check manifest works
uv run python -c "from remora.core.manifest import load_manifest; print('OK')"

# Run tests
uv run pytest tests/ -v

# Type check
uv run mypy src/remora
```

---

## File Dependency Order

Make changes in this order to avoid import errors:

1. `pyproject.toml` - Update dependency
2. `src/remora/core/manifest.py` - Create new file
3. `src/remora/core/kernel_factory.py` - Rewrite
4. `src/remora/core/swarm_executor.py` - Update import
5. Run tests
