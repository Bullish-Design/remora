# Implementation Plan: Neovim Demo Integration with structured-agents v0.4.0

> **CRITICAL RULES:**
> - **NO SUBAGENTS** — Do ALL work directly. No Task tool. No delegation.
> - **NEVER STOP AFTER COMPACTION** — Read CONTEXT.md, resume immediately.

---

## Overview

Ensure the Neovim demo is fully integrated with structured-agents v0.4.0 functionality. The demo demonstrates Remora's reactive agent swarm in a real editor environment.

## Current State

The s-a v0.4.0 migration is complete for core code:
- `src/remora/core/kernel_factory.py` — Updated (ModelAdapter removed)
- `src/remora/core/swarm_executor.py` — Updated imports
- `src/remora/core/manifest.py` — New local implementation
- `src/remora/lsp/runner.py` — Uses `build_client` from `structured_agents.client` (still works)

## Issues Found

1. **`tests/integration/test_vllm_real.py`** — Still imports `ModelAdapter` which was removed in v0.4.0
   - Lines 31, 50, 89: `from structured_agents import ModelAdapter`
   - Lines 116, 138, 162: Same issue

## Tasks

### Phase 1: Fix Integration Tests

| Task | Status | Notes |
|------|--------|-------|
| Update test_vllm_real.py to use v0.4.0 API | Pending | Remove ModelAdapter, use response_parser directly |
| Run integration tests | Pending | Verify fixes work |

### Phase 2: Verify Demo Components

| Task | Status | Notes |
|------|--------|-------|
| Verify LSP runner works with v0.4.0 | Pending | test_lsp_runner.py passes (11/11) |
| Verify neovim demo mock_llm.py works | Pending | No s-a imports, should be fine |
| Run golden_path e2e test | Pending | Full integration verification |

### Phase 3: Documentation

| Task | Status | Notes |
|------|--------|-------|
| Update any demo docs if needed | Pending | |

## Implementation Details

### Fixing test_vllm_real.py

The v0.4.0 API changes:
- `ModelAdapter` removed
- `AgentKernel` now takes `response_parser` directly
- `QwenResponseParser` still exists

Old code:
```python
from structured_agents import AgentKernel, ModelAdapter, QwenResponseParser
adapter = ModelAdapter(name="qwen", response_parser=QwenResponseParser())
kernel = AgentKernel(client=client, adapter=adapter, tools=tools)
```

New code:
```python
from structured_agents import AgentKernel, get_response_parser, ConstraintPipeline, NullObserver
response_parser = get_response_parser("qwen")  # or QwenResponseParser()
kernel = AgentKernel(
    client=client,
    response_parser=response_parser,
    constraint_pipeline=ConstraintPipeline.no_constraints(),
    observer=NullObserver(),
    tools=tools,
)
```

## Acceptance Criteria

1. `tests/integration/test_vllm_real.py` imports pass
2. LSP runner tests pass (already confirmed: 11/11)
3. Golden path e2e scenario runs successfully (with mock LLM)
4. All structured-agents imports use v0.4.0 API

---

> **REMINDER:**
> - **NO SUBAGENTS** — Do ALL work directly.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.
