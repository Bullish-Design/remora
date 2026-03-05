# REPO_RULES — lsp-chat-delivery-recovery

Project-specific working rules for this investigation.

1. For scripts/tests/tooling, use `devenv shell -- ...`. For read-only inspection (`ls`, `cat`, `rg`, `git log`, `git show`), direct shell commands are fine.
2. Change one lock-contention variable per experiment and capture before/after log metrics.
3. Do not increase SQLite busy timeout as a primary strategy.
4. Do not mix client-startup retry issues with DB write-contention issues in the same experiment.
5. Every attempted fix must be written to `DECISIONS.md` with expected effect and observed outcome.
