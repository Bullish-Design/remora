# Implementation Guide: Step 6 - Context Builder & Event Integration

## Target
Implement `ContextBuilder` as an EventBus subscriber that maintains the Two-Track Memory (short track recent actions, optional long-track store data) by listening for structured kernel and graph events.

## Overview
- Subscribe to `ToolResultEvent` and `AgentCompleteEvent` on the unified EventBus to update the rolling deque and knowledge map.
- Provide `build_context_for(node)` that optionally asks the indexer store for related nodes and concatenates hub context with the short track summary.
- Expose helper methods `get_recent_actions()`, `get_knowledge()`, and `clear()` for tests and dashboard pre-flight checks.

## Contract Touchpoints
- `ContextBuilder` subscribes to `ToolResultEvent` and `AgentCompleteEvent` on the shared EventBus.
- `build_context_for(node)` may query the indexer store and merges long-track knowledge with short-track summaries.
- `ContextBuilder` and `RecentAction` are re-exported from `src/remora/__init__.py`.

## Done Criteria
- Recent actions deque updates on each relevant event.
- Knowledge summaries reflect tool results and agent completions.
- Tests cover event handling and context composition.

## Steps
1. Create `ContextBuilder` in `src/remora/context.py` that stores recent actions (deque) and knowledge (dict), uses typed `match` statements to process events, and provides prompt-building helpers.
2. Use structured-agents events directly (no extra ToolResult schema) and re-export `ContextBuilder` and `RecentAction` in `src/remora/__init__.py`.
3. Write unit tests (`tests/test_context.py`) that emit `ToolResultEvent`/`AgentCompleteEvent`, verify rolling window behavior, and ensure context sections include knowledge summaries.
