# Assumptions — Remora Docs

## Audience
- **Primary**: Developers who want to USE Remora as an AI-assisted coding environment
- **Secondary**: Note-takers who want to use Remora for Obsidian-style markdown management
- **NOT**: Contributors to Remora's source code (that's internal docs territory)

## Constraints
- Docs go in `docs/` in the remora repo (new files, not replacing existing internal docs)
- The `docs/guides/` subdirectory is new and will be created
- Existing docs (`EventBased_Concept.md`, `LLM_REFERENCE.md`, `HOW_TO_CREATE_AN_AGENT.md`, etc.) are internal/developer docs and remain untouched
- New docs should be standalone — a user shouldn't need to read the internal design docs
- Keep examples concrete and runnable where possible
- Notetaking workflow is aspirational but grounded in real discovery capabilities (markdown queries exist and work)

## Technical Ground Truth
- Config: `remora.yaml` with `${VAR:-default}` env expansion, Pydantic BaseSettings with `REMORA_*` prefix
- Model config hierarchy: remora.yaml defaults -> bundle.yaml per-bundle override -> REMORA_* env vars
- LLM backend: OpenAI-compatible `/v1/chat/completions` API. vLLM is primary. External APIs work by changing base URL + API key.
- Discovery: tree-sitter based. Python (.py), Markdown (.md), TOML (.toml) built-in. Custom `.scm` queries supported.
- Markdown nodes: file, section, todo, note, code_block. Frontmatter with `type: todo` produces todo nodes.
- Tool calling: vLLM needs `--tool-call-parser qwen3_xml --enable-auto-tool-choice`

## NO SUBAGENTS
**NEVER use the Task tool. Do all work directly.**
