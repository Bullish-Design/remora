# CONTEXT: Code Review 0005 Fixes

We are addressing the 22 issues raised in the `CODE_REVIEW.md` generated on 2026-03-07. 

## Current State
Phase 1 (Critical Issues 1-6) has been completed.
- `agent_node.py` import guards removed
- `discovery.py` DRY violation fixed with `_parse_nodes` extraction
- `dispatcher.py` EventBus API usage fixed
- `ls/__main__.py` import path fixed

## Next Action
Begin Phase 2 (Architectural Concerns):
1. Delete the 20 legacy proxy files in `src/remora/core/` since we've verified standard canonical imports are securely used throughout the codebase. No import modifications necessary.
2. Split `EventStore` in `event_store.py` by extracting Node CRUD operations into a separate `NodeStore` class.
