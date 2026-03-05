# ASSUMPTIONS — lsp-chat-delivery-recovery

## Scope
- Immediate goal is baseline chat delivery from editor input to runner/LLM execution.
- Problem is in local app flow before vLLM response generation in most failing runs.

## Environment
- Workspace root: `/home/andrew/Documents/Projects/remora`.
- Logs source: `.remora/logs/server-2026-03-05_*.log` and matching client logs.
- Event persistence uses SQLite (`.remora/indexer.db` events table in current wiring).

## Constraints
- Avoid repeating pure retry/backoff tuning without isolating lock holder ownership.
- Avoid large speculative refactors until baseline reliability is measurable.
- Keep changes aligned with `.scratch/CRITICAL_RULES.md` and `.scratch/REPO_RULES.md`.

## Success Criteria
- `on_input_submitted` consistently reaches `HumanChatEvent emitted`.
- `execute_turn: START` appears for each submission.
- `execute_turn: ... calling LLM` appears for each submission.
- No sustained `append: database locked`/`batch_append: database locked` storms during chat.
