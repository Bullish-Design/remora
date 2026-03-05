# START HERE — LSP Startup Initial Connection

If you are a new agent/session, do this in order:

1. Read:
   - `ASSUMPTIONS.md`
   - `CONTEXT.md`
   - `PROGRESS.md`
   - `ISSUES.md`
2. Read issue artifacts:
   - `issues/2026-03-05-latest-manual-run/LOG_ANALYSIS.md`
   - `issues/2026-03-05-latest-manual-run/HYPOTHESIS_REPORT.md`
   - `issues/2026-03-05-latest-manual-run/NEXT_STEP_PLAN.md`
3. Run fresh attach probe:
   - `devenv shell -- uv sync --extra dev`
   - `devenv shell -- nv2 --headless remora_demo/companion/demo/harness.py \
      "+lua vim.defer_fn(function() local clients=vim.lsp.get_clients({name='remora'}); print('REMORA_CLIENTS=' .. tostring(#clients)); vim.cmd('qa!') end, 10000)"`
4. If `REMORA_CLIENTS=0`, treat startup as failed and instrument startup path first.
5. If `REMORA_CLIENTS>=1`, run manual chat/panel workflow and inspect markers listed in `REPO_RULES.md`.
