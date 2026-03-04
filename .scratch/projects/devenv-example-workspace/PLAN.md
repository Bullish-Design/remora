# devenv-example-workspace — Implementation Plan

Transform `/home/andrew/Documents/Projects/remora-example-workspace` into a working example of
the devenv-installed Remora vision from `DEVENV_INSTALLED_BRAINSTORM.md`.

## Goal

A consumer repo that:
1. Imports nixvim (from local disk path) to get `nv2`
2. Imports remora (from local disk path) to get the remora Python package + nvim plugin
3. On `devenv shell` entry: sets up .remora/, installs remora into venv, reconciles workspace
4. `nv2` launches with remora plugin auto-configured, LSP ready

## Steps

1. **devenv.yaml** — Add `nix-neovim` and `remora` inputs as `git+file://` local paths; import nix-neovim
2. **devenv.nix** — Import nixvim devenv.nix, configure nv2 options (extraRuntimePaths for remora nvim plugin, extraInitLua for remora.setup()), add Python venv with remora, add enterShell for scaffolding + reconcile
3. **remora.yaml** — Sensible defaults for the example workspace (discovery_paths, model config, bundle_mapping)
4. **.remora/** — Create directory structure + .gitignore entries for runtime state
5. **pyproject.toml** — Update project name, add remora as dependency via git source
6. **Example source files** — Create `src/example_workspace/` with a few Python files so discovery has something to find
7. **.tmuxp.yaml** — Update project name
8. **Test** — `devenv shell` and verify everything works

## Key Technical Decisions

- Use `git+file://` local path imports for nixvim (same pattern as the guide docs)
- Use `builtins.getEnv "PWD"` for remora nvim plugin path so edits are live-reloaded
- Remora Python package installed via `uv pip install -e /path/to/remora` in enterShell (not Nix-packaged)
- `impure: true` in devenv.yaml (needed for `builtins.getEnv`)

## NO SUBAGENTS — do all work directly.
