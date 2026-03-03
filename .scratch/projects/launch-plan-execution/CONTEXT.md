# CONTEXT — Launch Plan Execution

## Current State
- **Active batch:** ALL BATCHES COMPLETE + PYDANTIC CONSOLIDATION REFACTOR COMPLETE
- **Last completed:** Pydantic Consolidation Refactor — all 6 steps implemented
- **Test suite:** 659 passed, 2 xfailed (6 new TDD tests added)

## What Just Happened
- **Implemented the full Pydantic Consolidation Refactor** (described in `PYDANTIC_CONSOLIDATION_REFACTOR.md`):
  - **Step 1:** `ToolSchema` → `BaseModel` in `agent_node.py`, updated `to_row()` to use `model_dump()`, updated test assertion, added `model_dump` fallback to `projections.py:_dataclass_default()`
  - **Step 2:** `SubscriptionPattern` + `Subscription` → `BaseModel` in `subscriptions.py`, replaced `asdict(pattern)` with `pattern.model_dump()`, simplified `agent_node.py to_row()` (removed all `is_dataclass` branches), removed `dataclasses` imports from `agent_node.py`
  - **Step 3:** `ToolCall` + `LLMResponse` → `BaseModel` in `runner.py`, removed `dataclasses` import
  - **Step 4:** `Message` + `ChatConfig` + `AgentResponse` → `BaseModel` in `chat.py`, removed dead `from dataclasses import asdict` in `chat_service.py`
  - **Step 5:** `CSTNode` → `BaseModel` with `ConfigDict(frozen=True)` in `discovery.py`, preserved custom `__hash__` (only hashes `node_id`) with detailed docstring, added 3 regression tests
  - **Step 6:** Updated serialization in `projector.py` — reordered `_to_jsonable()` and `_event_payload()` to check `model_dump` before `is_dataclass`, kept `is_dataclass`/`asdict` for `structured_agents` external events
- All TDD: wrote failing tests first, then converted, then verified full suite green
- `UiStateProjector` remains `@dataclass` (service component, not a data model)
- `is_dataclass`/`asdict` imports kept in `projections.py` and `projector.py` for external `structured_agents` events

## What Needs to Be Done Next

ALL WORK IS COMPLETE.
- Launch plan execution: 75+ items, Batches 1-8 — all done
- Pydantic consolidation refactor guide: written and implemented in full
- No remaining stdlib `@dataclass` data models in `src/remora/` (only `UiStateProjector` stays as service @dataclass)

## Files Modified in Pydantic Consolidation
1. `src/remora/core/agent_node.py` — ToolSchema → BaseModel, removed dataclass imports, simplified to_row()
2. `src/remora/core/subscriptions.py` — SubscriptionPattern/Subscription → BaseModel, model_dump()
3. `src/remora/lsp/runner.py` — ToolCall/LLMResponse → BaseModel, removed dataclass import
4. `src/remora/core/chat.py` — Message/ChatConfig/AgentResponse → BaseModel
5. `src/remora/service/chat_service.py` — removed dead `from dataclasses import asdict`
6. `src/remora/core/discovery.py` — CSTNode → BaseModel(frozen=True), preserved __hash__
7. `src/remora/core/projections.py` — added model_dump fallback in _dataclass_default()
8. `src/remora/ui/projector.py` — reordered model_dump before is_dataclass in _to_jsonable/_event_payload

## Test Files Modified
1. `tests/unit/test_lsp_server.py` — assert ToolSchema issubclass(BaseModel)
2. `tests/unit/test_subscriptions.py` — added test_subscription_pattern_is_pydantic_model
3. `tests/unit/test_runner_loop.py` — added test_tool_call_llm_response_are_pydantic_models
4. `tests/unit/test_chat_session.py` — added test_chat_types_are_pydantic_models
5. `tests/test_discovery.py` — added TestCSTNodeIsPydantic (3 tests: model check, hash regression, frozen check)
6. `tests/unit/test_phase1_gaps.py` — updated test_extra_tools_missing_fields to accept ValidationError

## Key Decisions Made (carried forward)
1-17. (Same as before — see previous version)
18. **All stdlib @dataclass data models → Pydantic BaseModel** — ToolSchema, SubscriptionPattern, Subscription, ToolCall, LLMResponse, Message, ChatConfig, AgentResponse, CSTNode
19. **CSTNode __hash__ override preserved** — Pydantic frozen hashes all fields, but CSTNode identity is node_id only
20. **Serialization fallbacks check model_dump before is_dataclass** — future-proof ordering

## How to Resume
1. Read `.scratch/CRITICAL_RULES.md`
2. Read `.scratch/REPO_RULES.md`
3. Read this file
4. Check PROGRESS.md
5. All work is complete — no remaining tasks
