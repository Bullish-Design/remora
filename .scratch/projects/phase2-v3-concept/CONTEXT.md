# Context: Phase 2 v3 Concept

## Status: ACTIVE — YAML workspace deep-dive complete

## Session history

### Session 1
Wrote PHASE2_V3_BOOTSTRAP_CONCEPT.md in bootstrap/.

### Session 2
Wrote RESEARCH.md: v1 AgentNode pattern → bootstrap v3 mapping.
Wrote RESEARCH_2_MIXIN_ERGONOMICS.md: mixin patterns, developer ergonomics,
schema diffusion.
Updated PHASE2_V3_BOOTSTRAP_CONCEPT.md with §6 "The Agent Model" (BootstrapAgent,
Capability enum, mixin marker classes, AgentDefinition, capability ladder,
developer visibility table).

### Session 3 (current)
Wrote RESEARCH_3_YAML_WORKSPACE_DEFINITION.md: deep dive on YAML/TOML workspace
definitions as the core agent model. All 10 sections complete.

## Key decisions

1. v3 philosophy: specify the substrate only, let structure emerge.
2. .pym scripts are the ONLY tool interface (enforced by Grail @external).
3. Graph navigation via new graph_* externals in BootstrapExternals.
4. Graph library: SQLite (M0-M3) + Rustworkx (M4+).
5. Agent model: BootstrapAgent (flat runtime) + Capability enum (access control)
   + mixin marker classes (capability composition at authoring time)
   + AgentDefinition (Pydantic authoring model).
6. YAML workspace definitions: the agent's cairn workspace IS its identity.
   Contractual files: role.md, schema.yaml, capabilities.yaml.
   Conventional files: notes.md, log.jsonl, todo.md, working_memory.md.
7. schema.yaml format: version, name, capabilities, system, context steps,
   tools, subscriptions, max_turns, termination.
   Template vars: {node.*}, {agent.*}, {{role}}, {{notes}}.
8. Composition: `extends` key (one level) + YAML anchors (inline reuse).
   Capability presets in bootstrap/agents/capabilities/*.yaml.
9. Pydantic bridge: developers write Pydantic AgentDefinition → serialized
   to YAML. Agents write YAML → validated by AgentSchemaYaml.model_validate().
   Same TurnSchema at runtime either way.
10. Developer workflow: CRITICAL_RULES §5 — large docs use Write-append pattern,
    NOT Edit text-matching inside the document.

## Process note (CRITICAL_RULES §5)
For large documents:
- Write ToC first, save to file
- Append sections using Bash `cat >> file` or Write with growing content
- NEVER use Edit to text-match inside a large document

## Output files
bootstrap/PHASE2_V3_BOOTSTRAP_CONCEPT.md (updated with §6 Agent Model)
.scratch/projects/phase2-v3-concept/RESEARCH.md
.scratch/projects/phase2-v3-concept/RESEARCH_2_MIXIN_ERGONOMICS.md
.scratch/projects/phase2-v3-concept/RESEARCH_3_YAML_WORKSPACE_DEFINITION.md
