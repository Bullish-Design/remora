# Context — devenv-example-workspace

## Current State (2026-03-03)

**STATUS: Working.** All files written, devenv shell builds and works.

### What Was Done

1. Created all example workspace files in `/home/andrew/Documents/Projects/remora-example-workspace/`:
   - `devenv.yaml`, `devenv.nix`, `remora.yaml`, `.remora/`, `.gitignore`, `pyproject.toml`
   - `src/example_workspace/{__init__,models,utils,service}.py`
   - `tests/{test_models,test_utils}.py`
   - `.tmuxp.yaml`

2. Hit a Nix evaluation failure: `CanonPath::removePrefix` C++ assertion when using `git+file://` non-flake input for nixvim. Root cause: Nix's `lazy-trees` option + store-copied non-flake inputs can't handle relative path resolution (`./nvim`, `./plugins.nix`) inside the copied source.

3. **Fixed** by switching to the same pattern as `remora/devenv.nix` — direct Nix path import:
   ```nix
   imports = [ /home/andrew/Documents/Projects/nixvim/devenv.nix ];
   ```
   Removed `nix-neovim` from `devenv.yaml` inputs and imports. Cleaned up `.devenv/flake.json` and `imports.txt`.

4. Verified:
   - `devenv shell` builds successfully (169s first build, <300ms cached)
   - Remora installed, reconciliation discovers 20 nodes
   - `nv2` is on PATH, runs Neovim v0.11.6
   - Remora plugin loads in nv2 (`require("remora")` succeeds)

### What Remains

- Commit all changes in the example workspace repo
- Optionally push to `remora-example-workspace` remote

### Key Decision

Used direct Nix path import for nixvim instead of `devenv.yaml` `git+file://` input. This is documented in a comment in `devenv.nix`. The `git+file://` approach triggers a Nix bug. The direct path import works identically to how `remora/devenv.nix` imports nixvim.
