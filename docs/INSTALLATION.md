# Installation

Remora is not published to PyPI. It is developed locally using [devenv.sh](https://devenv.sh/) for environment management and [uv](https://docs.astral.sh/uv/) for Python dependency management.

## Prerequisites

- [Nix](https://nixos.org/) package manager
- [devenv.sh](https://devenv.sh/getting-started/) (installs on top of Nix)

## Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd remora

# 2. Enter the devenv shell (provisions Python 3.13, uv, and system deps)
devenv shell

# 3. Sync Python dependencies (includes dev tools: pytest, mypy, ruff, hypothesis)
uv sync --extra dev
```

This is the only supported installation method. `pip install remora` will **not** work.

## Optional Extras

Defined in `pyproject.toml`:

| Extra | Description |
|-------|-------------|
| `frontend` | Adds `uvicorn` and `httpx` for running `remora serve` |
| `companion` | Adds `sqlite-vec`, `sentence-transformers`, `jinja2` for the companion LSP |
| `dev` | Test and lint tools: pytest, mypy, ruff, hypothesis, etc. |

Install extras with:

```bash
uv sync --extra dev --extra frontend
```

## Python Version

Requires Python `>=3.13`. The devenv shell provisions the correct version automatically.

## Running Tests

```bash
devenv shell -- pytest
```

## Running the Swarm

```bash
# Start a vLLM-compatible model server first, then:
remora swarm start
```

See `HOW_TO_USE_REMORA.md` for detailed usage.
