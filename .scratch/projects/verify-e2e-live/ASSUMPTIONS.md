# ASSUMPTIONS: Verify E2E Live Scenarios

## Environment

- All commands run inside `devenv shell --` prefix
- vLLM server at `http://remora-server:8000/v1` with model `Qwen/Qwen3-4B-Instruct-2507-FP8`
- `nv2`, `remora-lsp`, `tmux`, `agg` all available via devenv
- Working directory: `/home/andrew/Documents/Projects/remora`

## Demo Project

- Located at `remora_demo/project/`
- 3 source files: `loader.py` (3 functions), `merge.py` (2 functions), `schema.py` (1 class + 1 function)
- 2 test files: `test_loader.py`, `test_merge.py`
- `.remora/` directory with extension models
- `DemoProjectGuard` restores files after each scenario run

## Scenario Behavior

- LLM responses are non-deterministic — assertions must be tolerant (regex, substring)
- Model response latency: typically 5-30s
- LSP startup: 3-8s
- `[Remora]` notification indicates LSP connected
- Scenarios modify files via keystrokes in nv2, not direct file I/O
- Previous runs (March 2) produced .cast/.gif files — those were from development, not verified

## Line Numbers in Demo Files

- `loader.py`: `load_config` at line 12, `detect_format` at line 29, `load_yaml` at line 39
- `merge.py`: `deep_merge` at line 8, `merge_dicts` at line 19
- `schema.py`: `SchemaError` at line 8, `validate` at line 16
- `test_loader.py`: `test_load_yaml` at line 13

## Non-Determinism

- Chat responses will vary in wording each run
- Rewrite proposals will vary in content
- Timing of agent discovery and cascade varies per run
- A [PASS] means no exceptions, NOT that the scenario tested the right thing
