# structured-agents v0.4 Migration for Remora

## Overview

Remora depends on `structured-agents` for its agent kernel, LLM client, and event system.
The v0.4 release of structured-agents removes intermediate abstractions (`ModelAdapter`,
`agent.py` module) in favor of a cleaner, more direct API.

**This migration is required** - Remora will fail to import after upgrading to v0.4.

## Quick Reference

### Removed in v0.4

| Import | Status |
|--------|--------|
| `structured_agents.agent` | **DELETED** |
| `structured_agents.agent.load_manifest` | **DELETED** - reimplement locally |
| `structured_agents.agent.get_response_parser` | Moved to `structured_agents.parsing` |
| `structured_agents.models.adapter.ModelAdapter` | **DELETED** - no replacement needed |

### New v0.4 API

```python
from structured_agents import (
    # Core
    AgentKernel,
    
    # Parsing (moved from agent.py)
    ResponseParser, DefaultResponseParser, get_response_parser,
    
    # Client (unchanged)
    LLMClient, OpenAICompatibleClient, LiteLLMClient, build_client,
    
    # Grammar (unchanged)  
    ConstraintPipeline, DecodingConstraint, StructuredOutputModel,
    
    # Events (now Pydantic models instead of dataclasses)
    Observer, NullObserver, Event, KernelStartEvent, KernelEndEvent,
    ModelRequestEvent, ModelResponseEvent, ToolCallEvent, ToolResultEvent,
    
    # Types (unchanged)
    Message, ToolCall, ToolResult, ToolSchema, TokenUsage, StepResult, RunResult,
    
    # Tools (unchanged)
    Tool,
)
```

## Migration Checklist

- [ ] Update `pyproject.toml` to require `structured-agents>=0.4.0`
- [ ] Create `src/remora/core/manifest.py` with `load_manifest` implementation
- [ ] Rewrite `src/remora/core/kernel_factory.py` (remove ModelAdapter)
- [ ] Update `src/remora/core/swarm_executor.py` imports
- [ ] Run tests and verify
- [ ] Test with vLLM grammar constraints

## Files to Modify

| File | Priority | Changes |
|------|----------|---------|
| `pyproject.toml` | P0 | Version bump |
| `src/remora/core/manifest.py` | P0 | **NEW FILE** |
| `src/remora/core/kernel_factory.py` | P0 | Remove ModelAdapter |
| `src/remora/core/swarm_executor.py` | P0 | Update imports |

## Related Documentation

- `MANIFEST_IMPL.md` - Complete `load_manifest` implementation
- `KERNEL_FACTORY.md` - Before/after for kernel_factory.py
- `TESTING.md` - Test plan for validation
