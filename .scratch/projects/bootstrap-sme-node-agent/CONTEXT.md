# Bootstrap SME Node Agent — Context

## Current state
- New project scaffold created at `.scratch/projects/bootstrap-sme-node-agent/`.
- Milestone 1 completed via TDD (tests added first, then assets implemented).
- New system schema: `bootstrap/agents/subject_matter_expert.yaml`.
- New system tool: `bootstrap/tools/user_question.pym`.
- Bootstrap schema/tool contract tests now cover SME profile + user question event payload.
- Milestone 2 completed: file-open fan-out trigger path implemented.
  - Added unassigned-node planning (`find_unassigned_nodes`) in bootstrap coordinator.
  - Added `BootstrapRunner.run_for_file(file_path)` with parallel node activation.
  - Wired LSP `did_open` to schedule bootstrap fan-out task for opened file.
  - Added/updated tests for coordinator, runner, and LSP document handler.
- Milestone 3 started with two concrete pieces in place:
  - `handle_agent_needed` now seeds `schema.yaml` (extends `subject_matter_expert`) and `summary.md` template when missing.
  - Companion workspace sidebar now includes a `Summary` panel backed by `summary.md`.
  - Added tests for seeding behavior and summary panel rendering.
- User-correction loop now wired end-to-end in code:
  - Neovim panel supports pending `HumanInputRequestEvent` requests and submits `request_id` responses.
  - LSP `$/remora/submitInput` handler routes `request_id` responses to bootstrap runner.
  - Bootstrap runner appends `HumanInputResponseEvent` and immediately re-activates the target SME agent.
  - Activation path persists correction entries into `notes.md` and `summary.md` (`## User corrections`) before turn execution.
  - LSP startup now bridges bootstrap `HumanInputRequestEvent(kind=user_question)` into `$/remora/requestInput` notifications.
- Added regression coverage for the new routing path:
  - `tests/unit/test_lsp_background_scan_manifest.py::test_initialized_registers_bootstrap_user_question_bridge`
  - `tests/unit/test_lsp_notifications.py::test_input_submitted_request_id_falls_back_to_human_input_event`
- Added headless Neovim smoke check for plugin Lua loadability:
  - `nvim --headless -u NONE -i NONE ... require('remora.panel') / require('remora.init')` passes.
- Re-ran targeted bootstrap/LSP/companion tests in devenv; all passing.

## User intent snapshot
- Start work in root `bootstrap/` for a foundational node SME agent.
- Target existing Python codebases.
- Generate per-node summaries and show in sidebar.
- Support user Q&A and correction note capture.

## Next immediate step
- Perform interactive end-to-end verification in a real Neovim session:
  - open Python file and verify file-open fan-out creates SME workspaces and summaries.
  - trigger `user_question`, submit response in panel, confirm correction persistence + refreshed sidebar summary.
