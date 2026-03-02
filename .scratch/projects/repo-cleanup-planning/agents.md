# agents/ — Shadow Tree Notes

## Status: REMOVE (old grail/cairn agent bundles, pre-EventBased)

This directory contains the old-style agent bundles:
- `apply_fix/` — Cairn-based tool (check.json, externals.json, monty_code.py)
- `article_section/`, `article_summary/` — Grail bundles (bundle.yaml + tools/*.pym)
- `.cairn/docstring_style/`, `.cairn/ruff_config/` — Cairn tool bundles
- `chat/` — Chat bundle
- `docstring/` — Docstring agent bundle + tools
- `docstring_style/` — Cairn docstring style tool
- `harness/` — Test harness bundle
- `lint/` — Lint agent bundle + tools
- `pytest_config/` — Cairn pytest config tool
- `read_current_docstring/`, `read_file/`, `read_type_hints/` — Cairn tools
- `ruff_config/` — Cairn ruff config tool
- `sample_data/` — Sample data agent bundle
- `test/` — Test agent bundle + tools

All of these are OLD architecture — they use grail bundles (bundle.yaml) and cairn tools
(check.json + monty_code.py). In the EventBased architecture, agent behavior comes from
AgentExtension configs in `.remora/models/`.

The entire `agents/` directory is already gitignored. Safe to REMOVE from working tree.
Might want to keep one or two as reference/examples if needed.
