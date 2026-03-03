# Skill: devenv.sh Environment

This project uses [devenv.sh](https://devenv.sh) to manage the development environment. **All commands must be run through the devenv shell.** No exceptions.

---

## Rule

**Every command** — tests, scripts, linters, formatters, Python invocations, package management — must be executed via:

```bash
devenv shell -- <command>
```

Do NOT:
- Run `python`, `pytest`, `mypy`, `ruff`, or any other tool directly from the system PATH.
- Use `uv run` outside the devenv shell.
- Use `/path/to/.devenv/state/venv/bin/python` directly.
- Assume the system Python or any globally installed tool is correct.

Do:
- Always prefix with `devenv shell --`.
- Install dev dependencies with `devenv shell -- uv sync --extra dev` if pytest or other dev tools are missing.

---

## Examples

### Running tests
```bash
devenv shell -- pytest tests/unit/test_lsp_graph.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

### Running a specific Python script
```bash
devenv shell -- python scripts/my_script.py
```

### Linting and formatting
```bash
devenv shell -- ruff check src/
devenv shell -- ruff format src/
devenv shell -- mypy
```

### Installing/syncing dependencies
```bash
devenv shell -- uv sync --extra dev
```

---

## Why

The devenv shell ensures:
- Correct Python version (pinned in `devenv.nix`).
- Correct virtualenv with all dependencies resolved from `pyproject.toml` and `uv.lock`.
- Reproducible environment across machines.
- No contamination from system packages or other project venvs.

Running commands outside the devenv shell can pick up wrong Python versions, missing packages, or stale dependency versions — leading to confusing failures that waste time.

---

## Hard Dependencies

rustworkx and all other packages listed in `pyproject.toml` `[project.dependencies]` are **hard dependencies**. They must:
- Be imported unconditionally (no `try/except ImportError` guards).
- Be tested unconditionally (no `pytest.mark.skipif` for missing deps).
- Always be available in the devenv shell environment.
