# Context: Phase 2 Bootstrap Concept

## Status: COMPLETE — V6 written

## Output files (newest first)
bootstrap/PHASE2_V6_BOOTSTRAP_CONCEPT.md  ← CURRENT (907 lines, 10 sections)
bootstrap/PHASE2_V5_BOOTSTRAP_CONCEPT.md  ← superseded by V6
bootstrap/PHASE2_V4_BOOTSTRAP_CONCEPT.md  ← superseded by V5
bootstrap/PHASE2_V3_BOOTSTRAP_CONCEPT.md  ← superseded by V4
.scratch/projects/phase2-v3-concept/RESEARCH.md
.scratch/projects/phase2-v3-concept/RESEARCH_2_MIXIN_ERGONOMICS.md
.scratch/projects/phase2-v3-concept/RESEARCH_3_YAML_WORKSPACE_DEFINITION.md

## V6 core insight: two primitives, three stores, all tools are .pym

read(store, selector)    →  value
write(store, key, value) →  ok

Three stores:
  workspace  — per-agent Cairn key-value (SQLite). Write: no side effects.
  graph      — shared directed property graph (SQLite). Write: no side effects.
  events     — shared append-only log (SQLite, WAL). Write: notifies subscribers.

Six Python bedrock functions (only Python agents can't see):
  _cairn_read / _cairn_write
  _graph_read / _graph_write
  _event_read / _event_write

All named operations are .pym Grail scripts:
  System tools:    bootstrap/tools/*.pym (9 tools)
  Agent tools:     workspace/tools/*.pym (synthesized)
  @external boundary enforced by Grail compiler.

Delivery plan: M0 (bedrock) → M1 (system tools) → M2 (turn executor)
  → M3 (self-bootstrap) → M4 (graph seed) → M5 (companion) → M6 (synthesis)

## Process
Large documents: Write ToC first, then Bash append (cat >> file << 'SECTION_END')
NEVER use Edit for large document sections.
