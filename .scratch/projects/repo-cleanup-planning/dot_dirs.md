# Dot-directories — Shadow Tree Notes

## .context/ (10MB) — REMOVE from repo, add to .gitignore
Vendored reference codebases for AI assistant context:
- `cairn/`, `fsdantic/`, `grail_v3.0.0/`, `structured-agents_v0.3.4/` — Dependency source
- `datastar-python-develop/`, `stario/`, `templateer/`, `xgrammar-0.1.29/` — Reference code
- `functiongemma_examples/`, `remora-demo/`, `ty_lsp/` — Reference material
- Various analysis .md files
This is useful for AI-assisted development but should NOT be in the git repo.
Already partially gitignored but seems to be tracked. Add `.context/` to .gitignore.

## .grail/ (616K) — KEEP (runtime artifacts, already gitignored-ish)
Compiled Grail tools. Generated at runtime. Already gitignored via agents/** pattern.
But .grail/ itself isn't explicitly gitignored. Add to .gitignore.

## .hidden/ (2.0GB!) — REMOVE / ensure gitignored
Archive of old docs, code reviews, plans, future concepts. MASSIVE.
Already gitignored (`.hidden/**`). Should NOT be in working tree for a clean repo.
Consider deleting or moving to separate archive repo.

## .remora/ (5.9GB!) — Runtime artifacts, gitignored
Contains:
- `agents/` (245 dirs) — Compiled/cached agent artifacts
- `events/` — Event DB files
- `hub.db` (4.7MB) — Hub database
- `indexer.db` (1.6MB) — Indexer database
- `logs/` — Log files
- `swarm/` — Swarm state
Already gitignored (`.remora/**`). These are runtime artifacts. KEEP pattern in .gitignore.

## .worktrees/ (14MB) — REMOVE from repo, already gitignored
Git worktrees. Already gitignored (`.worktrees/`). KEEP .gitignore entry.

## .hypothesis/ (1.8MB) — Gitignored
Property-based testing artifacts. Already gitignored (`.hypothesis/`). KEEP .gitignore entry.

## .benchmarks/ — Empty directory. KEEP (for pytest-benchmark).

## .cache/ — Runtime cache (ast_summary). Gitignored. KEEP .gitignore entry.

## .claude/ — Claude settings. Not gitignored. ADD to .gitignore.

## .scratch/ — Working notes. Not gitignored. ADD to .gitignore (dev-only).
