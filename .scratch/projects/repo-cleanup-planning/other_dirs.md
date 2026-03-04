# Other directories — Shadow Tree Notes

## server/ — KEEP (deployment artifacts)
- `adapter_manager.py`, `agents_server.py` — Server management. KEEP.
- `docker-compose.yml`, `Dockerfile`, `Dockerfile.*` — Docker configs. KEEP.
- `entrypoint.sh`, `update.sh` — Shell scripts. KEEP.
- `.env.example` — Example env. KEEP.
- `README.md`, `SERVER_DEV_GUIDE.md` — Docs. KEEP.
- `test_connection.py` — Connection test. KEEP.
- `tool_chat_template_functiongemma.jinja` — Template. KEEP.

## scripts/ — KEEP (mostly) + REMOVE duplicates
- `jsonl_to_readable.py` — Utility. KEEP.
- `migrate_bundles.py` — Bundle migration. KEEP (or REMOVE if bundles are gone).
- `remora_tui.py` — TUI script. KEEP.
- `start_lsp.sh` — LSP launcher. KEEP.
- `training_examples/` — DUPLICATE of docs/training_examples/. REMOVE one copy.

## examples/ — KEEP (reference material)
- `article_summary_demo/` — Working example with remora.yaml. KEEP.
- `stario_reference/` — Stario reference. KEEP.
- `treesitter_swarm/` — Treesitter swarm example. KEEP.
- Various CONCEPT.md files — Future concept docs. KEEP or MOVE to docs/.

## training/ — KEEP (training data)
- `demo_project/` — Demo project for training. KEEP.
- `docstring/`, `lint/`, `sample_data/`, `test/` — Empty .gitkeep dirs. KEEP for structure.

## plugin/ — KEEP
- `remora_nvim.lua` — Neovim plugin. KEEP.

## _review_notes/ — REMOVE (old review notes)
- `00_core_library.md`, `01_lsp_layer.md` — Outdated pre-EventBased reviews.

## tmp_test_runner/ — REMOVE (temp files)
- `events.db`, `subscriptions.db` — Leftover test DB files.
