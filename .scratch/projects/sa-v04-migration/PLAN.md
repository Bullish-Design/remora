# Implementation Plan: structured-agents v0.4 Migration

> **CRITICAL INSTRUCTIONS FOR EXECUTING AGENT:**
> - **DO NOT USE SUBAGENTS** - Execute all tasks directly
> - **DO NOT STOP UNTIL COMPLETE** - Continue through all phases until tests pass
> - **UPDATE PROGRESS.md** - Mark tasks complete as you go

---

## Status: READY TO EXECUTE

## Overview

Migrate Remora from structured-agents v0.3.x to v0.4.0, which removes the `ModelAdapter` abstraction and relocates `load_manifest`.

## Prerequisites

- [x] structured-agents v0.4.0 committed and tagged
- [x] Migration documentation complete
- [ ] GitHub accessible (push pending)

## Implementation Steps

### Phase 1: Create New Files

#### Step 1.1: Create `src/remora/core/manifest.py`

**Action:** Create new file with `BundleManifest` dataclass and `load_manifest` function.

**Source:** Copy implementation from `MANIFEST_IMPL.md`

**Verification:**
```bash
uv run python -c "from remora.core.manifest import load_manifest; print('OK')"
```

### Phase 2: Update Existing Files

#### Step 2.1: Update `pyproject.toml`

**Action:** Bump structured-agents version requirement.

**Changes:**
```diff
-"structured-agents>=0.3.4",
+"structured-agents>=0.4.0",
```

**Also update `[tool.uv.sources]`:**
```diff
-structured-agents = { git = "...", rev = "main" }
+structured-agents = { git = "...", tag = "v0.4.0" }
```

**Verification:**
```bash
uv lock --upgrade-package structured-agents && uv sync
uv run python -c "import structured_agents; print(structured_agents.__version__)"
# Expected: 0.4.0
```

#### Step 2.2: Rewrite `src/remora/core/kernel_factory.py`

**Action:** Remove ModelAdapter, update imports, pass response_parser directly to AgentKernel.

**Changes:** See `KERNEL_FACTORY.md` for complete diff.

**Key changes:**
1. Remove `from structured_agents.agent import get_response_parser`
2. Remove `from structured_agents.models.adapter import ModelAdapter`
3. Add `from structured_agents import AgentKernel, build_client, get_response_parser, ConstraintPipeline, NullObserver`
4. Remove `ModelAdapter` instantiation
5. Pass `response_parser` and `constraint_pipeline` directly to `AgentKernel`

**Verification:**
```bash
uv run python -c "from remora.core.kernel_factory import create_kernel; print('OK')"
```

#### Step 2.3: Update `src/remora/core/swarm_executor.py`

**Action:** Change import for `load_manifest`.

**Changes:**
```diff
-from structured_agents.agent import load_manifest
+from remora.core.manifest import load_manifest
```

**Verification:**
```bash
uv run python -c "from remora.core.swarm_executor import SwarmExecutor; print('OK')"
```

#### Step 2.4: Update `src/remora/core/__init__.py`

**Action:** Export new manifest module.

**Changes:** Add to exports:
```python
from remora.core.manifest import BundleManifest, load_manifest
```

Add to `__all__`:
```python
"BundleManifest",
"load_manifest",
```

### Phase 3: Verification

#### Step 3.1: Run Import Checks

```bash
uv run python -c "
from remora.core.kernel_factory import create_kernel
from remora.core.swarm_executor import SwarmExecutor
from remora.core.manifest import load_manifest, BundleManifest
print('All imports OK')
"
```

#### Step 3.2: Run Unit Tests

```bash
uv run pytest tests/unit/ -v
```

#### Step 3.3: Run Full Test Suite

```bash
uv run pytest tests/ -v
```

#### Step 3.4: Type Check

```bash
uv run mypy src/remora/core/manifest.py
uv run mypy src/remora/core/kernel_factory.py
```

### Phase 4: Commit

**Commit message:**
```
feat: migrate to structured-agents v0.4.0

- Create remora/core/manifest.py with local load_manifest implementation
- Rewrite kernel_factory.py to remove ModelAdapter abstraction
- Update swarm_executor.py imports
- Bump structured-agents dependency to v0.4.0

Breaking changes in structured-agents v0.4:
- ModelAdapter removed (response_parser now direct on AgentKernel)
- structured_agents.agent module deleted
- load_manifest must be implemented locally
```

## Execution Order

```
1. Create manifest.py           (no dependencies)
2. Update pyproject.toml        (get new s-a version)
3. Run uv sync                  (install new version)
4. Rewrite kernel_factory.py    (depends on new s-a)
5. Update swarm_executor.py     (depends on manifest.py)
6. Update __init__.py exports   (depends on manifest.py)
7. Run tests                    (verify everything)
8. Commit                       (if tests pass)
```

## Rollback Plan

If critical issues arise after migration:

```toml
# In pyproject.toml
[tool.uv.sources]
structured-agents = { git = "https://github.com/Bullish-Design/structured-agents.git", rev = "v0.3.4" }
```

Then revert the code changes and run `uv sync`.

## Files Modified

| File | Action |
|------|--------|
| `src/remora/core/manifest.py` | CREATE |
| `pyproject.toml` | MODIFY |
| `src/remora/core/kernel_factory.py` | REWRITE |
| `src/remora/core/swarm_executor.py` | MODIFY (1 line) |
| `src/remora/core/__init__.py` | MODIFY (add exports) |

## Time Estimate

- Phase 1 (create manifest.py): 5 min
- Phase 2 (update files): 10 min
- Phase 3 (verification): 5 min
- Phase 4 (commit): 2 min

**Total: ~25 minutes**

## Related Documentation

- `MANIFEST_IMPL.md` - Complete manifest.py implementation
- `KERNEL_FACTORY.md` - Before/after diffs
- `SWARM_EXECUTOR.md` - Import changes
- `TESTING.md` - Test plan
- `CONTEXT.md` - Quick reference

---

> **REMINDER:**
> - **DO NOT USE SUBAGENTS** - Execute all tasks directly
> - **DO NOT STOP UNTIL COMPLETE** - Continue through all phases until tests pass
> - **UPDATE PROGRESS.md** - Mark tasks complete as you go
