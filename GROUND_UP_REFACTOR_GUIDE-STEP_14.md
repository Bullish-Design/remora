# Implementation Guide for Step 14: Integration Testing

This guide covers end-to-end testing of the full Remora v1.0 pipeline and fixing any integration issues discovered.

## Prerequisites

- All previous steps completed (Phase 1-6: Foundation, Core, Execution, Agents, Services)
- Working CLI entry points: `remora`, `remora-index`, `remora-dashboard`
- Test fixtures and mock agents in place

## Test Environment Setup

### 1. Verify CLI Entry Points

```bash
# Check main CLI
remora --help

# Check indexer CLI
remora-index --help

# Check dashboard CLI
remora-dashboard --help
```

### 2. Set Up Test Directory

Create a clean test directory with sample source files:

```bash
mkdir -p /tmp/remora-test/{src,agents}
```

Create a minimal `remora.yaml` in the test directory:

```yaml
discovery:
  paths: ["src/"]
  languages: ["python"]

bundles:
  path: "agents/"
  mapping:
    function: harness
    class: harness
    file: harness

execution:
  max_concurrency: 2
  error_policy: skip_downstream
  timeout: 60

workspace:
  base_path: ".remora/workspaces"
  cleanup_after: "30m"

model:
  base_url: "http://localhost:8000/v1"
  default_model: "Qwen/Qwen3-4B"
```

### 3. Create Simple Test Source Files

Create `src/test_module.py`:

```python
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


class Calculator:
    """Simple calculator."""
    
    def __init__(self):
        self.value = 0
    
    def add(self, n: int) -> None:
        self.value += n
    
    def get_value(self) -> int:
        return self.value
```

## Integration Test Procedures

### Test 1: Discovery Pipeline

Verify basic discovery functionality:

```bash
cd /tmp/remora-test
remora discover src/
```

**Expected Output:** JSON array of discovered CSTNodes with fields:
- `node_id`: SHA256-based ID
- `node_type`: "function" or "class"
- `name`: function/class name
- `file_path`: path to source file
- `start_line`, `end_line`: line numbers

**Verification:**
```bash
remora discover src/ | python -c "import json, sys; nodes = json.load(sys.stdin); print(f'Discovered {len(nodes)} nodes'); assert len(nodes) >= 5, 'Should find 5+ nodes'"
```

### Test 2: Graph Building

Verify graph construction:

```bash
cd /tmp/remora-test
remora plan src/
```

**Expected Output:** JSON showing agent nodes with dependencies.

### Test 3: Full Execution with Harness Agent

Test the complete pipeline with the harness agent (minimal agent for testing):

```bash
cd /tmp/remora-test
remora run src/ --bundles agents/harness/
```

**Expected Behavior:**
1. Discover nodes from `src/`
2. Map nodes to harness bundle
3. Build dependency graph
4. Execute each node with harness agent
5. Output results

**Verification:**
```bash
remora run src/ --bundles agents/harness/ 2>&1 | grep -q "completed" && echo "SUCCESS" || echo "FAILED"
```

### Test 4: Indexer Integration

Test the background indexer:

```bash
cd /tmp/remora-test

# Start indexer in background
remora-index start --watch src/ &
INDEXER_PID=$!

# Wait for initial indexing
sleep 3

# Check index status
remora-index status

# Verify index contains files
remora-index status | grep -q "test_module.py" && echo "Indexed" || echo "Not indexed"

# Stop indexer
kill $INDEXER_PID
```

**Expected Output:**
- Index shows tracked files
- Status reports "watching" state

### Test 5: Dashboard Integration

Test the web dashboard:

```bash
cd /tmp/remora-test

# Start dashboard in background
remora-dashboard start --port 8420 &
DASH_PID=$!

# Wait for startup
sleep 2

# Test HTTP endpoint
curl -s http://localhost:8420/ | head -20

# Check SSE endpoint
timeout 3 curl -s http://localhost:8420/events || true

# Stop dashboard
kill $DASH_PID
```

**Expected Behavior:**
- Dashboard serves HTML on `/`
- SSE endpoint available at `/events`

### Test 6: Human-in-the-Loop Testing

Test interactive IPC with dashboard:

1. Create an agent that requests human input:

```python
# In a test bundle's tool that asks for input
from grail import external

@external
async def ask_user(question: str) -> str:
    """Ask the user a question and wait for response."""
    ...
```

2. Run with the agent:

```bash
remora run src/ --bundles agents/harness/ --interactive
```

3. From another terminal, submit input via dashboard API:

```bash
curl -X POST http://localhost:8420/api/input \
  -H "Content-Type: application/json" \
  -d '{"request_id": "abc123", "response": "yes"}'
```

4. Verify agent continues after input is received.

### Test 7: Checkpointing

Test save and restore functionality:

```python
# Test checkpoint save
remora run src/ --bundles agents/harness/ --checkpoint /tmp/checkpoint-test/

# Verify checkpoint files exist
ls -la /tmp/checkpoint-test/

# Test restore
remora run src/ --bundles agents/harness/ --restore /tmp/checkpoint-test/
```

**Expected Behavior:**
- Checkpoint directory contains workspace snapshots
- Restore resumes from saved state

### Test 8: Full Test Suite

Run all unit and integration tests:

```bash
# Run pytest
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=src/remora --cov-report=term-missing
```

**Expected:** All tests pass with >80% coverage on new code.

## Common Issues and Fixes

### Issue: Discovery finds no nodes

**Cause:** Tree-sitter queries not loading or language not detected.

**Fix:**
1. Check queries directory exists at `src/remora/queries/`
2. Verify language detection: `remora discover src/ --verbose`
3. Add explicit language: `remora discover src/ -l python`

### Issue: Agent execution hangs

**Cause:** Model server not available or timeout too short.

**Fix:**
1. Verify model server: `curl http://localhost:8000/v1/models`
2. Increase timeout in `remora.yaml`:
```yaml
execution:
  timeout: 300
```

### Issue: Dashboard won't start

**Cause:** Port already in use or missing dependencies.

**Fix:**
1. Check port: `lsof -i :8420`
2. Kill existing process or use different port
3. Check dependencies: `pip list | grep -E "starlette|datastar"`

### Issue: Checkpoint restore fails

**Cause:** Checkpoint format incompatible or workspace corruption.

**Fix:**
1. Verify checkpoint directory structure
2. Check Cairn workspace health: `cairn status <workspace>`
3. Delete corrupted checkpoint and re-run

## Verification Checklist

- [ ] `remora discover` outputs valid JSON with discovered nodes
- [ ] `remora run` executes full pipeline without errors
- [ ] `remora-index start` watches directories and builds index
- [ ] `remora-index status` shows tracked files
- [ ] `remora-dashboard start` serves web interface
- [ ] Dashboard SSE endpoint streams events
- [ ] Human-in-the-loop input reaches running agent
- [ ] Checkpoint saves complete state
- [ ] Checkpoint restores to saved state
- [ ] All pytest tests pass

## Cleanup

After testing, clean up test artifacts:

```bash
rm -rf /tmp/remora-test
rm -rf .remora/
```

## Next Step

Once all integration tests pass, proceed to cleanup phase:
- Remove all old code
- Update `pyproject.toml` with new entry points
- Update documentation
- Tag release v1.0.0
