# Cairn Enhancements - Decisions Log

Key decisions with rationale. Load ASSUMPTIONS.md before making decisions.

---

## D1: CLI Framework Choice

**Date:** 2026-03-03  
**Decision:** Use Click for workspace CLI commands  
**Alternatives Considered:**
- Typer (modern, auto-generates help)
- Click (already used in project)

**Rationale:**
- Click already used in `cli/main.py`
- Adding Typer would create two CLI frameworks
- Click is mature and sufficient for needs
- Consistency with existing code

**Assumptions Referenced:** None

---

## D2: Protocol vs Abstract Base Class

**Date:** 2026-03-03  
**Decision:** Use `typing.Protocol` with `@runtime_checkable`  
**Alternatives Considered:**
- ABC (Abstract Base Class)
- Protocol (structural typing)
- Plain duck typing

**Rationale:**
- Protocol enables structural typing (more Pythonic)
- No inheritance required for mock implementations
- `@runtime_checkable` allows isinstance() checks if needed
- Better IDE support than plain duck typing

**Assumptions Referenced:** Design Decisions #2

---

## D3: State Storage Location

**Date:** 2026-03-03  
**Decision:** Store agent state in workspace KV, not separate database  
**Alternatives Considered:**
- Separate SQLite database per agent
- Central state database
- Workspace KV store

**Rationale:**
- State naturally travels with workspace
- Automatic isolation per agent
- Leverages existing Cairn KV infrastructure
- No additional database connections needed
- fsdantic KVManager already has typed repositories

**Assumptions Referenced:** Design Decisions #3

---

## D4: Container Runtime Abstraction

**Date:** 2026-03-03  
**Decision:** Abstract ContainerRuntime with Docker implementation first  
**Alternatives Considered:**
- Docker-only, hard-coded
- Podman-only
- Abstract with multiple implementations

**Rationale:**
- Docker is most widely installed
- Podman has Docker-compatible CLI
- Abstraction allows adding Podman later
- Some users may have security requirements for Podman

**Assumptions Referenced:** Design Decisions #4

---

## D5: Default Validation Checks

**Date:** 2026-03-03  
**Decision:** Only syntax check by default, opt-in for full validation  
**Alternatives Considered:**
- All checks by default
- No checks by default
- Syntax only by default

**Rationale:**
- Syntax check is fast (~1s) and always works
- Type/test/lint require project-specific setup
- Full validation can be slow (30s+)
- Users can enable with `--all-checks` flag
- Reduces friction for getting started

**Assumptions Referenced:** Design Decisions #5

---

## D6: Execution Order

**Date:** 2026-03-03  
**Decision:** Execute phases in order 4 → 2 → 3 → 1 → 5 → 6 → 7  
**Alternatives Considered:**
- Priority order (P0, P1, P2)
- Dependency order
- User-facing value order

**Rationale:**
- Phase 4 (P0) first: Fix private API reduces risk
- Phase 2 before 3: Protocol enables testing of state manager
- Phase 1 after 2,3: CLI can use tested components
- Phase 5 before 6: Sync required for sandbox sync-back
- Phase 7 last: Requires sandbox

**Assumptions Referenced:** None

---

## D7: Inspector Context Manager Pattern

**Date:** 2026-03-03  
**Decision:** Use async context manager for WorkspaceInspector  
**Alternatives Considered:**
- Manual open/close methods
- Context manager
- Automatic cleanup on GC

**Rationale:**
- Context manager ensures cleanup
- Matches existing Workspace pattern in fsdantic
- Python best practice for resource management
- Works well with async code (`async with`)

**Assumptions Referenced:** Invariants #5 (async everything)

---

## Pending Decisions

### PD1: Private API Replacement

**Status:** RESOLVED - See D8

**Options:**
- A: Use public API if available ← CHOSEN (we will add it to Cairn)
- B: Wrap private API with deprecation warning
- C: Pin Cairn version and document

---

## D8: Cairn-First Implementation Strategy

**Date:** 2026-03-03  
**Decision:** Add public APIs to Cairn first, then implement Remora features using those clean APIs  
**Alternatives Considered:**
- Option A: Cairn-first - Add APIs to Cairn, then use in Remora (CHOSEN)
- Option B: Remora-first - Import fsdantic directly in Remora now, migrate later
- Option C: Minimal Cairn additions - Add only essential Cairn APIs, rest in Remora

**Rationale:**
- Maintains clean dependency chain: Remora → Cairn → fsdantic
- Avoids Remora importing fsdantic directly (tech debt)
- Creates reusable APIs that benefit other Cairn consumers
- Resolves PD1 by adding public `open_workspace()` to Cairn
- User explicitly requested Option A

**Assumptions Referenced:** Design Decisions #1 (clean dependency chain)

**Impact:**
- New Phase 0 added to plan: Cairn API Additions
- Execution order updated: 0 → 4 → 2 → 3 → 1 → 5 → 6 → 7
- Cairn will gain: `open_workspace()`, `WorkspaceInspector`, `AgentStateManager`, `Workspace` type export

---

## Decision Template

```markdown
## D#: [Title]

**Date:** YYYY-MM-DD  
**Decision:** [What was decided]  
**Alternatives Considered:**
- [Option 1]
- [Option 2]

**Rationale:**
- [Why this option was chosen]

**Assumptions Referenced:** [Which assumptions informed this]
```
