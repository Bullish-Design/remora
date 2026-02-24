# Structured Agents vLLM Optional Dependency Refactor

## Problem Overview
- `structured-agents` currently declares `vllm>=0.15.1` as a required dependency, so installing it pulls in the `vllm` package and its Python 3.13 constraint.
- The package also runs `require_xgrammar_and_vllm()` inside `structured_agents.__init__`, immediately trying to import `vllm` (and `xgrammar`) every time the package is imported. That means any project importing `structured-agents` now needs `vllm`, even if it only uses the parts unrelated to vLLM or never runs a vLLM-enabled workflow.
- Because `vllm` is incompatible with Python 3.14, this prevents consumers (like Remora’s frontend) from upgrading their Python runtime even if they just need the non-vLLM features.

## Desired State
- `vllm` should be an **optional** dependency, pulled in only when a developer opts into vLLM-aware tooling (e.g., installing `structured-agents[vllm]` or enabling Remora’s backend extra).
- `import structured_agents` should succeed without `vllm` installed; any runtime errors should only surface when code paths that genuinely require vLLM are executed.
- Documentation and configuration should clearly explain the split between the lightweight frontend and the vLLM backend.

## Step-by-step Refactor Guide

1. **Remove the eager dependency check**
   - In `src/structured_agents/__init__.py`, remove the top-level call to `require_xgrammar_and_vllm()`.
   - Instead, export a helper such as `ensure_vllm_dependencies()` from `src/structured_agents/deps.py`. This helper should still raise a `RuntimeError` if either `xgrammar` or `vllm` is missing, but only when explicitly invoked.
   - Update anywhere in the code that currently assumes these imports exist to call the helper just before building structured-output payloads or starting vLLM-specific flows. For example, wrap the sections in `grammar/artifacts.py` and `plugins/*` that emit `structured_outputs` with a call to the helper, so the runtime error happens there instead of at import time.

2. **Turn `vllm` into an optional extra**
   - In `pyproject.toml`, remove `"vllm>=0.15.1"` from the main `dependencies` list.
   - Add a `[project.optional-dependencies]` section (if it doesn't exist yet) with an extra such as:
     ```toml
     [project.optional-dependencies]
     vllm = ["vllm>=0.15.1"]
     ```
   - Document that consumers should install `structured-agents[vllm]` (or Remora’s backend extra) to enable the vLLM payload builders and backend workflows.

3. **Gate vLLM-aware logic**
   - Identify modules that rely on vLLM for structured-output constraints (e.g., `grammar/artifacts.py`, `plugins/*_components.py`). Guard those flows with runtime checks that call the new helper before touching `vllm`-specific APIs.
   - If any of those modules import `xgrammar` or other tight dependencies, catch `ImportError` and raise a clear message instructing the developer to install the extra.
   - Ensure that structured-agents’ public API remains usable (e.g., bundle loading, kernel orchestration) even when `vllm` is absent.

4. **Update documentation and tests**
   - In `README.md` and `DEV_GUIDE.md`, explain the optional-extra approach and how to install the backend when needed (e.g., `pip install structured-agents[vllm]`).
   - Adjust any test fixtures that require `vllm` so they either skip when it's missing or explicitly install the extra via Poetry/Hatch when running integration tests.
   - Update any CI scripts or docs to reflect that `vllm` is optional; we still run the backend tests in environments where Python 3.13 with `structured-agents[vllm]` is available.

5. **Coordinate with Remora**
   - After these changes, Remora can depend on plain `structured-agents` and only request the `vllm` extra when backend functionality is needed (for example, by making the remora `backend` extra install `structured-agents[vllm]`).
   - Update the `VLLM_OPTIONAL_REFACTOR.md` guide (or similar docs) describing that the frontend now only requires the lightweight dependencies while Remora’s backend installs the extra.

## Summary for the Junior Dev
- Moving `vllm` into an optional extra prevents its Python 3.13 requirement from blocking the rest of the project.
- The key work is shifting the dependency check out of the package initializer, gating vLLM-only code paths, and documenting the new installation choices.
- Follow the step-by-step plan above, verifying after each change that `import structured_agents` works without `vllm` installed and that the vLLM helpers still raise helpful errors when triggered.
