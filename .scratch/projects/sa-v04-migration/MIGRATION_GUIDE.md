# Migration Guide: structured-agents v0.3 → v0.4

## Executive Summary

The v0.4 refactor eliminates the `ModelAdapter` abstraction layer. Instead of:

```
Client → Adapter (parser + pipeline) → Kernel
```

It's now:

```
Client → Kernel (with parser + pipeline as direct fields)
```

---

## Breaking Changes

### 1. `ModelAdapter` Removed

**Before (v0.3):**
```python
from structured_agents.models.adapter import ModelAdapter

adapter = ModelAdapter(
    name=model_name,
    response_parser=parser,
    constraint_pipeline=pipeline,
)
kernel = AgentKernel(client=client, adapter=adapter, ...)
```

**After (v0.4):**
```python
# No adapter - pass directly to kernel
kernel = AgentKernel(
    client=client,
    response_parser=parser,
    constraint_pipeline=pipeline,
    ...
)
```

### 2. `structured_agents.agent` Module Deleted

The `agent.py` module contained:
- `get_response_parser()` → Moved to `structured_agents.parsing`
- `load_manifest()` → Removed (implement locally)
- `Agent` class → Removed (use `AgentKernel` directly)

**Before:**
```python
from structured_agents.agent import get_response_parser, load_manifest
```

**After:**
```python
from structured_agents.parsing import get_response_parser
from remora.core.manifest import load_manifest  # Local implementation
```

### 3. Import Path Changes

| Old Import | New Import |
|------------|------------|
| `structured_agents.agent.get_response_parser` | `structured_agents.parsing.get_response_parser` |
| `structured_agents.models.adapter.ModelAdapter` | *Removed* |
| `structured_agents.agent.load_manifest` | *Removed - implement locally* |

### 4. Events Are Now Pydantic Models

Events changed from `@dataclass(frozen=True)` to Pydantic `BaseModel` with `frozen=True`.

**Implications:**
- Use `.model_dump()` instead of `dataclasses.asdict()`
- Use `.model_dump_json()` for JSON serialization
- Same immutability guarantees

---

## AgentKernel v0.4 Constructor

```python
@dataclass
class AgentKernel:
    # Required
    client: LLMClient
    
    # Optional with defaults
    response_parser: ResponseParser = DefaultResponseParser()
    tools: Sequence[Tool] = ()
    observer: Observer = NullObserver()
    constraint_pipeline: ConstraintPipeline | None = None
    max_history_messages: int = 50
    max_concurrency: int = 1
    max_tokens: int = 4096
    temperature: float = 0.1
    tool_choice: str = "auto"
```

**Key changes from v0.3:**
- No `adapter` parameter
- `response_parser` is a direct field
- `constraint_pipeline` is a direct field
- `observer` defaults to `NullObserver()` (not `None`)

---

## build_client() Behavior

The `build_client()` function now routes based on model prefix:

| Model Format | Client Type | Grammar Support |
|--------------|-------------|-----------------|
| `hosted_vllm/Model/Name` | `LiteLLMClient` | Yes |
| `anthropic/model` | `LiteLLMClient` | No |
| `openai/model` | `LiteLLMClient` | No |
| `Plain/Model` | `OpenAICompatibleClient` | No* |

*Grammar constraints are only applied when model starts with `hosted_vllm/`.

**For Remora's vLLM usage:**

Option 1 - Keep existing behavior (no grammar):
```python
model = "Qwen/Qwen3-4B"  # Uses OpenAICompatibleClient
```

Option 2 - Enable grammar constraints:
```python
model = "hosted_vllm/Qwen/Qwen3-4B"  # Uses LiteLLMClient with extra_body
```

---

## Migration Steps

### Step 1: Update pyproject.toml

```toml
# Change version requirement
"structured-agents>=0.4.0",
"structured-agents[grammar,vllm]>=0.4",
```

### Step 2: Rewrite kernel_factory.py

See `KERNEL_FACTORY.md` for complete before/after.

### Step 3: Create manifest.py

See `MANIFEST_IMPL.md` for implementation.

### Step 4: Update swarm_executor.py

Change imports:
```python
# Before
from structured_agents.agent import load_manifest

# After  
from remora.core.manifest import load_manifest
```

### Step 5: Run Tests

```bash
uv run pytest tests/ -v
```

---

## What Stays The Same

- `Tool` protocol (schema + execute)
- `Message`, `ToolCall`, `ToolResult`, `ToolSchema` types
- `Observer` protocol (emit method)
- `ConstraintPipeline` API
- `build_client()` function signature
- `kernel.run()` and `kernel.step()` methods
- Event types and their fields

---

## Rollback

If critical issues arise, pin to v0.3:

```toml
[tool.uv.sources]
structured-agents = { git = "https://github.com/Bullish-Design/structured-agents.git", rev = "v0.3.4" }
```
