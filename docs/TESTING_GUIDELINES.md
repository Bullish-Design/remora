# Testing Guidelines

Remora's test suite covers the event-driven runtime, agent discovery, workspaces, service layer, and UI components. The suite currently contains ~1400 tests including Hypothesis property-based tests.

## Running Tests

```bash
# Full suite
devenv shell -- pytest

# Unit tests only
devenv shell -- pytest tests/unit/ -v

# Integration tests (requires vLLM server)
devenv shell -- pytest tests/integration/ -v

# Cairn workspace tests
devenv shell -- pytest tests/integration/cairn/ -v -m cairn

# Hypothesis property tests
devenv shell -- pytest tests/test_hypothesis_properties.py -v
```

Always run `devenv shell -- uv sync --extra dev` before the first test run in a session.

## Test Directory Structure

```
tests/
  unit/                        # Fast, isolated unit tests
    test_event_bus.py          # EventBus pub/sub, filtering, streams
    test_workspace.py          # Cairn workspace creation, snapshot/restore
    ...
  integration/                 # Tests requiring external services
    cairn/                     # Cairn copy-on-write isolation, concurrency
    ...
  benchmarks/                  # Performance benchmarks
  companion/                   # Companion LSP tests
  roundtrip/                   # Serialization roundtrip tests
  test_hypothesis_properties.py  # Property-based tests (Hypothesis)
  test_discovery.py            # Agent discovery via tree-sitter
  test_tool_script_fuzzing.py  # Tool script fuzz testing
  conftest.py                  # Shared fixtures (EventStore, SubscriptionRegistry, etc.)
```

## Test Categories

### Unit Tests

Validate individual components in isolation:

- **EventBus**: pub/sub, wildcard matching, SSE stream iteration, JSON serialization
- **EventStore**: append, replay, trigger consumption
- **SubscriptionRegistry**: pattern matching, agent registration
- **Workspaces**: Cairn workspace creation, snapshot/restore, shared directories
- **Discovery**: tree-sitter node extraction, CSTNode construction
- **Config**: load/serialize/validate config from YAML

### Integration Tests

Stitch multiple components together. Integration tests expect a real vLLM server and will skip when unavailable.

- Agent workflow: discovery -> execution -> event emission
- Cairn isolation: copy-on-write semantics, concurrent access

Environment variables for tuning:
- `REMORA_WORKFLOW_RUNS` (default 20)
- `REMORA_WORKFLOW_CONCURRENCY` (default 8)
- `REMORA_WORKFLOW_MIN_SUCCESS` (default 0.8)
- `REMORA_CAIRN_STRESS_AGENTS` (default 200)

### Hypothesis Property Tests

Property-based tests using the Hypothesis library for fuzzing and invariant checking:

- Config serialization roundtrips
- Event serialization/deserialization
- AgentNode model validation
- SubscriptionPattern matching properties
- Discovery determinism

These tests generate random inputs and verify that invariants hold across all generated cases.

### Cairn Integration Tests

Located in `tests/integration/cairn/`. Validates:

- Copy-on-write isolation between agent workspaces
- Read/write semantics
- KV submissions and lifecycle behavior
- Concurrency safety under load

Markers: `cairn`, `cairn_isolation`, `cairn_concurrent`, `cairn_lifecycle`, `cairn_slow`.

## Test Markers

Defined in `pyproject.toml`:

| Marker | Description |
|--------|-------------|
| `integration` | Requires vLLM server |
| `grail_runtime` | Exercises Grail runtime execution |
| `acceptance` | End-to-end MVP tests (requires vLLM) |
| `acceptance_mock` | End-to-end tests with mock server |
| `slow` | Long-running tests |
| `cairn` | Cairn workspace integration |
| `cairn_isolation` | Copy-on-write isolation tests |
| `cairn_concurrent` | Concurrency safety tests |
| `cairn_lifecycle` | Workspace lifecycle tests |
| `cairn_slow` | Long-running Cairn tests |

## Writing New Tests

- Keep assertions at the **public event/model level** rather than testing private internals
- Use the shared fixtures from `tests/conftest.py` (e.g., `event_store`, `subscription_registry`)
- For async tests, `asyncio_mode = "auto"` is configured — just use `async def test_*`
- For property-based tests, use `@given()` from Hypothesis with appropriate strategies
- Mark integration tests with the appropriate marker so they skip in CI without external services
