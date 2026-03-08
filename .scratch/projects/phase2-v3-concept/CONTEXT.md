# Context: Phase 2 v3/v4 Concept

## Status: COMPLETE — V4 written

## Session history

### Session 1
Wrote PHASE2_V3_BOOTSTRAP_CONCEPT.md in bootstrap/.

### Session 2
Wrote RESEARCH.md: v1 AgentNode pattern → bootstrap v3 mapping.
Wrote RESEARCH_2_MIXIN_ERGONOMICS.md: mixin patterns, developer ergonomics.
Updated PHASE2_V3_BOOTSTRAP_CONCEPT.md with §6 "The Agent Model".

### Session 3
Wrote RESEARCH_3_YAML_WORKSPACE_DEFINITION.md: full deep-dive on YAML workspace
definitions as the core agent model (10 sections).

### Session 4 (current)
After distillation conversation ("two tools + one convention"), wrote
PHASE2_V4_BOOTSTRAP_CONCEPT.md — complete rewrite superseding v3.

## V4 key principles

1. **The absolute core is two tools**: `read_file` + `write_file` (always
   available, no capability gate, sufficient to close the bootstrapping loop)
2. **One convention**: if `schema.yaml` exists in workspace, use it; else DEFAULT_SCHEMA
3. **The workspace IS the agent**: identity (role.md + schema.yaml), memory
   (notes.md + log.jsonl + todo.md), capability record (capabilities.yaml)
4. **Capability ladder is earned**: CORE (read+write) → SCHEMA_EVOLVE →
   EVENT_EMIT+GRAPH_READ → GRAPH_WRITE → TOOL_SYNTHESIZE → PRIVILEGED
5. **Workspace-first delivery**: M0 (workspace) → M1 (turn executor) →
   M2 (self-bootstrapping) → M3 (graph) → M4 (events) → M5 (capability
   governance) → M6 (companion sidebar) → M7 (adapter)
6. **Companion sidebar** = structured viewer of workspace files; no special
   protocol; todo.md is interactive (developer toggles checkboxes)
7. **Process**: large docs use Bash append (cat >> file << 'EOF') not Edit

## Output files
bootstrap/PHASE2_V3_BOOTSTRAP_CONCEPT.md (superseded)
bootstrap/PHASE2_V4_BOOTSTRAP_CONCEPT.md (current — 946 lines, 9 sections)
.scratch/projects/phase2-v3-concept/RESEARCH.md
.scratch/projects/phase2-v3-concept/RESEARCH_2_MIXIN_ERGONOMICS.md
.scratch/projects/phase2-v3-concept/RESEARCH_3_YAML_WORKSPACE_DEFINITION.md
