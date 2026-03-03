# Cairn Enhancements - Context Summary

Session resumption context for Cairn workspace enhancements.

---

## Project Location

```
/home/andrew/Documents/Projects/remora/.scratch/projects/cairn-enhancements/
```

## Related Projects

- **cairn-analysis** - Completed analysis that identified these enhancements
- **Remora source** - `/home/andrew/Documents/Projects/remora`
- **fsdantic context** - `/home/andrew/Documents/Projects/remora/.context/fsdantic/`
- **Cairn context** - `/home/andrew/Documents/Projects/remora/.context/cairn/`

---

## Architecture Decision: Cairn-First

**Decision D8:** Add public APIs to Cairn first, then implement Remora features using those clean APIs.

This maintains the clean dependency chain: **Remora → Cairn → fsdantic**

---

## What This Project Does

Implements enhancements in TWO PHASES:

### Phase 0: Cairn API Additions (CURRENT)
Add to Cairn library:
- `open_workspace()` - Public function to open workspace
- `WorkspaceInspector` - Tree, stats, diff utilities
- `AgentStateManager` - General-purpose KV state for agents
- `Workspace` type re-export

### Phases 1-7: Remora Features
Then implement in Remora:
1. **CLI Wrappers** - `remora workspace tree/ls/cat/diff/stats/materialize`
2. **WorkspaceProtocol** - Abstract interface for testability
3. **KV Store Integration** - Agent state persistence between turns
4. **Private API Fix** - Use new public `open_workspace()` API
5. **Bidirectional Sync** - Sync disk changes back to workspace
6. **Container Sandbox** - Isolated code execution in Docker
7. **Validation Harness** - Automated code quality checks

---

## Key Files

### Cairn Files to Create/Modify (Phase 0)

| File | Change |
|------|--------|
| `cairn/runtime/workspace_manager.py` | Add `open_workspace()` function |
| `cairn/runtime/inspection.py` | NEW - WorkspaceInspector class |
| `cairn/runtime/state.py` | NEW - AgentStateManager class |
| `cairn/runtime/__init__.py` | Add exports |
| `cairn/__init__.py` | Add top-level exports |
| `tests/unit/test_workspace_api.py` | NEW - Tests for new APIs |

### Remora Files (Phases 1-7)

| File | Description |
|------|-------------|
| `src/remora/workspace/__init__.py` | Package init |
| `src/remora/workspace/inspector.py` | CLI inspection utilities (wraps Cairn) |
| `src/remora/workspace/sync.py` | Bidirectional sync |
| `src/remora/workspace/sandbox.py` | Container sandbox |
| `src/remora/workspace/validation.py` | Code validation |
| `src/remora/cli/workspace.py` | CLI commands |
| `src/remora/core/protocols.py` | Protocol definitions |
| `src/remora/core/agent_state.py` | State models |
| `src/remora/testing/mock_workspace.py` | Mock implementations |

---

## Execution Order

**Updated:** 0 → 4 → 2 → 3 → 1 → 5 → 6 → 7

1. **Phase 0 (P0)** - Add Cairn APIs (CURRENT)
2. **Phase 4 (P0)** - Fix private API usage in Remora
3. **Phase 2 (P1)** - WorkspaceProtocol (enables testing)
4. **Phase 3 (P1)** - KV Store (uses new AgentStateManager from Cairn)
5. **Phase 1 (P1)** - CLI Wrappers (uses WorkspaceInspector from Cairn)
6. **Phase 5 (P2)** - Bidirectional Sync
7. **Phase 6 (P2)** - Container Sandbox
8. **Phase 7 (P2)** - Validation Harness

---

## Current State

- **Analysis complete** - See cairn-analysis project
- **Architecture decided** - Cairn-first approach (D8)
- **Plan updated** - PLAN.md has Phase 0 with detailed Cairn specs
- **Phase 0 in progress** - Ready to implement Cairn additions

---

## Next Action

Implement Phase 0 Cairn API additions. Start with:

1. **Add `open_workspace()` function** to `cairn/runtime/workspace_manager.py`
2. **Create `cairn/runtime/inspection.py`** with WorkspaceInspector
3. **Create `cairn/runtime/state.py`** with AgentStateManager
4. **Update exports** in `cairn/runtime/__init__.py` and `cairn/__init__.py`
5. **Add tests** in `tests/unit/test_workspace_api.py`
6. **Run test suite** to verify
7. **Commit changes**

Note: Cairn source is at `/home/andrew/Documents/Projects/remora/.context/cairn/`
The actual Cairn repo location needs to be confirmed before making changes.

---

## Critical Rules Reminder

- **NO SUBAGENTS** - Do all work directly
- **NO STOPPING** - Continue until complete
- **UPDATE PROGRESS.md** - Mark tasks as done
