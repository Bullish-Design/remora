# REPO_RULES — LSP Startup Initial Connection

Project-local reminders for this specific effort.

## Execution
- Use `devenv shell --` for runtime/tests.
- Before first test command in a new session: `devenv shell -- uv sync --extra dev`.

## Validation Policy
- Startup validation requires the direct headless attach probe (`REMORA_CLIENTS>=1`).
- Manual validation requires correlated evidence across:
  - `.remora/logs/client-*.log`
  - `.remora/logs/server-*.log`
  - `~/.local/state/nvim/lsp.log`

## Logging Hygiene
- Always capture explicit marker counts for:
  - `cmd_chat: requestInput sent`
  - `on_input_submitted: params=`
  - `execute_turn: START`
  - `panel.do_fetch_agent_data: TIMEOUT`
  - `_background_scan: batch_append SLOW`

## Scope Discipline
- Keep each implementation pass to one causal hypothesis.
- Update `CONTEXT.md` and `PROGRESS.md` after each substantial run/change.
- NO SUBAGENTS.
