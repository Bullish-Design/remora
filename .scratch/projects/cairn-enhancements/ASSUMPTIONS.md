# Cairn Enhancements - Assumptions

Constraints and context that inform implementation decisions.

---

## Project Constraints

### 1. Dependency Constraints

- **fsdantic** - Already a dependency, provides low-level APIs
- **cairn** - Already a dependency, provides workspace management
- **click** - Already used for CLI (not typer)
- **Docker/Podman** - Optional, only for sandbox phase

### 2. API Stability

- fsdantic APIs are considered stable (0.2.0+)
- Cairn APIs have one known private usage (`_open_workspace`)
- Protocol definitions should be forward-compatible

### 3. Testing Requirements

- All new code needs unit tests
- Integration tests need Cairn fixtures (existing pattern)
- Sandbox tests may be skipped if Docker unavailable
- Maintain mypy strict compliance

### 4. Performance Constraints

- CLI commands should complete in <5s for typical workspaces
- Materialization may take longer for large projects
- Sandbox startup has Docker overhead (~2-5s)

---

## User Scenarios

### 1. Developer Debugging

> "I want to see what files are in the agent's workspace without extracting it"

→ `remora workspace tree .remora/agents/.../workspace.db`

### 2. Testing Without Cairn

> "I want to unit test my code that uses workspaces without real Cairn"

→ Use `MockWorkspace` implementing `WorkspaceProtocol`

### 3. Agent State Persistence

> "I want agent context to persist between turns"

→ `AgentStateManager` stores state in Cairn KV

### 4. Safe Code Execution

> "I want to run agent-generated code without affecting my system"

→ `WorkspaceSandbox` runs in isolated Docker container

### 5. Code Quality Gate

> "I want to validate agent output before accepting it"

→ `WorkspaceValidator` runs syntax/types/tests/lint checks

---

## Design Decisions

### 1. CLI Framework

**Decision:** Use Click (existing), not Typer

**Rationale:** Click already used in `cli/main.py`. Adding Typer would add redundant dependency.

### 2. Protocol vs ABC

**Decision:** Use `typing.Protocol` with `@runtime_checkable`

**Rationale:**
- Structural typing (duck typing) more Pythonic
- No inheritance required for implementations
- Runtime checking available when needed

### 3. State Storage Location

**Decision:** Store state in agent's workspace KV, not separate DB

**Rationale:**
- State travels with workspace
- Automatic isolation per agent
- Leverages existing Cairn infrastructure

### 4. Container Runtime

**Decision:** Docker first, with abstraction for Podman

**Rationale:**
- Docker more widely installed
- Podman compatible with Docker CLI
- Abstract `ContainerRuntime` allows swapping

### 5. Validation Default

**Decision:** Only syntax check by default, opt-in for full validation

**Rationale:**
- Syntax is fast and always works
- Types/tests/lint require project-specific setup
- User can enable with `--all-checks`

---

## Invariants

1. **Workspace isolation** - Agents cannot access each other's workspaces
2. **Stable workspace immutability** - Agents read from stable, write to overlay
3. **Path normalization** - All paths use `/` separator, start with `/`
4. **Async everything** - All workspace operations are async
5. **No blocking I/O** - Use asyncio for all I/O operations

---

## Out of Scope

- Web UI for workspace inspection (future phase)
- Multi-user workspace sharing
- Distributed workspace storage
- Real-time workspace watching
- Git integration for workspaces
