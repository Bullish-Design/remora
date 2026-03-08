# Research: YAML/TOML Workspace Definitions as the Core Agent Model

> Building on RESEARCH_2_MIXIN_ERGONOMICS.md §2.3 (YAML/TOML definition
> files). This document goes deep on making file-based agent definitions
> the primary authoring and self-bootstrapping mechanism.
>
> Core thesis: The agent's cairn workspace IS its identity. Structured text
> files (YAML schema, Markdown notes, JSONL log) serve as the agent's memory,
> definition, and self-description simultaneously — readable by humans in the
> companion sidebar and writable by the agent from within its own turn.

---

## Table of Contents

1. [The Workspace-as-Identity Model](#1-the-workspace-as-identity-model)
   What files live in every agent's cairn workspace. What each file is for.
   How the workspace is the single source of truth for everything an agent is
   and knows.

2. [The schema.yaml Format](#2-the-schemayaml-format)
   Full design of the YAML turn definition format. Template variables.
   Context step syntax. Tools, subscriptions, capabilities. YAML vs TOML
   for each file type. The built-in workspace read/write steps every agent gets.

3. [YAML Composition: Extends and Anchors](#3-yaml-composition-extends-and-anchors)
   Reuse without duplication. The `extends` key as a single-inheritance
   mechanism. YAML anchors for inline reuse. Base schema files.
   Capability preset bundles.

4. [The Self-Bootstrapping Path](#4-the-self-bootstrapping-path)
   Step-by-step: new node → DEFAULT_SCHEMA → agent writes schema.yaml →
   subsequent activations use it. What the LLM is prompted to produce
   and why YAML is uniquely suited for LLM generation.

5. [Notes, Logs, and Working Memory](#5-notes-logs-and-working-memory)
   The workspace as persistent cross-activation memory. notes.md, log.jsonl,
   todo.md, working_memory.md. How the runtime makes these first-class.
   Accumulation, pruning, and episodic recall.

6. [Companion Sidebar Rendering](#6-companion-sidebar-rendering)
   How workspace files map to sidebar sections. ASCII mockup of the sidebar.
   Why file-based definitions are perfect for the companion view.
   Real-time update when agents write to their workspace.

7. [Developer Authoring Workflow](#7-developer-authoring-workflow)
   Writing agent definitions as YAML files in bootstrap/agents/. Hot-reload.
   Validation feedback. How developer-authored YAML and agent-authored YAML
   coexist in the same workspace.

8. [Runtime Loading and Validation](#8-runtime-loading-and-validation)
   How the runtime finds and loads schema.yaml. Pydantic as the validator.
   Template variable resolution. Schema version migration and backward
   compatibility.

9. [Capability Declaration in YAML](#9-capability-declaration-in-yaml)
   How capabilities appear in the YAML format. Preset bundles. The
   request/grant flow for earning new capabilities. How the runtime
   enforces the declared set.

10. [Trade-offs and Open Questions](#10-trade-offs-and-open-questions)
    What YAML does well (emergence, readability, LLM generation). What
    YAML does poorly (type safety, composition depth). When to fall back
    to Python. The Pydantic bridge as the answer.

---

## 1. The Workspace-as-Identity Model

### 1.1 The core reframe

In the Pydantic-class approach, an agent's definition lives in Python files
that agents cannot write. In the YAML workspace approach, an agent's
definition lives in its own cairn workspace — files that the agent can
read and write in every turn using nothing more than the base externals
(`read_file`, `write_file`).

The cairn workspace is already persistent across activations. An agent
that writes `role.md` in its first activation finds it there on every
subsequent one. Extending this to `schema.yaml` means: **the agent authors
its own definition in the same way it authors its own notes**.

There is no separate "definition store." There is no external registry the
agent writes to. The agent's workspace IS its definition, its memory, and
its self-description — all in the same place.

### 1.2 The complete workspace layout

Every agent's cairn workspace contains a set of well-known files. Some are
written by the runtime on agent creation. Most are written by the agent
itself across its lifecycle:

```
.remora/<swarm_id>/agents/<agent_id>/workspace.db
 (Cairn key-value store; paths below are keys)

 role.md                 ← Who this agent is and what it's responsible for.
                           Written by the agent on first activation.
                           Read as the system prompt preamble on every turn.

 schema.yaml             ← The agent's TurnSchema definition.
                           Written by the agent (via emit_schema tool).
                           Loaded by the runtime on every activation.
                           If absent: DEFAULT_SCHEMA runs instead.

 capabilities.yaml       ← The capability set this agent currently holds.
                           Written by the runtime when capabilities change
                           (grant/revoke events). Read-only for the agent.

 notes.md                ← Accumulated working notes.
                           Written and appended by the agent across turns.
                           Included in context on every turn (optional step).

 log.jsonl               ← Activation log: one JSON line per activation.
                           Appended by the agent at the end of each turn.
                           Used for introspection and pattern detection.

 todo.md                 ← Pending tasks the agent has identified.
                           Optional — agent creates it if it wants one.
                           Can be emptied/updated across turns.

 working_memory.md       ← Scratchpad for current analysis.
                           Often overwritten (not accumulated like notes.md).
                           Used for multi-step reasoning within a turn.

 tools/                  ← Agent-synthesized .pym tools (TOOL_SYNTHESIZE cap).
   *.pym

 index.yaml              ← Runtime-maintained index of all workspace files.
                           Used by the companion sidebar to enumerate sections.
```

The runtime creates `capabilities.yaml` and `index.yaml`. The agent creates
everything else. Developers who want to seed an agent can pre-populate
`role.md` and `schema.yaml` — the agent finds them on first activation and
uses them directly.

### 1.3 Why this model fits the bootstrap thesis

The bootstrap thesis is: "specify the substrate, let structure emerge."
The workspace-as-identity model applies this at the agent level:

- **Substrate specified:** the runtime provides the cairn workspace, the
  `read_file`/`write_file` externals, the `emit_schema` tool, and the
  well-known file names it looks for (`schema.yaml`, `role.md`)
- **Structure emerges:** every other file — `notes.md`, `todo.md`,
  `working_memory.md`, custom tool files — is created by the agent if and
  when it decides it's useful

An agent that never needs notes doesn't create `notes.md`. An agent that
needs rich structured memory invents its own format. The runtime doesn't
prescribe it. The only contractual files are `role.md` (for the system
prompt) and `schema.yaml` (for the turn definition).

### 1.4 Two classes of workspace files

| Class | Files | Who writes | Runtime reads |
|-------|-------|-----------|---------------|
| **Contractual** | `role.md`, `schema.yaml`, `capabilities.yaml` | Agent (role.md, schema.yaml) / Runtime (capabilities.yaml) | Yes — used on every activation |
| **Conventional** | `notes.md`, `log.jsonl`, `todo.md`, `working_memory.md` | Agent | Only if schema.yaml includes them in context steps |
| **Synthesized** | `tools/*.pym` | Agent (with TOOL_SYNTHESIZE) | Yes — added to tool discovery path |

The conventional files are a strong default that the bootstrap should
recommend. The DEFAULT_SCHEMA includes a notes step. But an agent is free
to replace `notes.md` with `notes/2026-03.md` and `notes/2026-04.md` if
monthly notes make more sense for its use case.

---

## 2. The schema.yaml Format

### 2.1 Guiding principles

The format must satisfy three audiences simultaneously:

1. **Developers** writing it by hand in an editor — clear structure,
   minimal boilerplate, obvious meaning
2. **LLMs** generating it during self-bootstrapping — common YAML patterns,
   no unusual syntax, machine-verifiable against a JSON Schema
3. **The runtime** parsing and executing it — must map cleanly to `TurnSchema`
   / `ContextPipeline` / `Step` / `ToolRef` / `InputGate`

### 2.2 The full format

```yaml
# schema.yaml — agent turn definition
# Written by the agent to its own cairn workspace via the emit_schema tool.
# Runtime loads this on every activation; falls back to DEFAULT_SCHEMA if absent.

version: "1"

# ── Identity ─────────────────────────────────────────────────────────────────
name: events_module_agent
extension_name: EventsModuleAgent   # optional; recorded in agent graph node

# ── Capabilities ──────────────────────────────────────────────────────────────
# The agent declares what it needs. Runtime validates against its granted set.
# If a declared capability isn't granted, activation is rejected with an error.
capabilities:
  - file_read
  - file_write
  - graph_read
  - event_emit
  - schema_evolve

# ── System prompt ─────────────────────────────────────────────────────────────
# Multiline string. Template variables: {node.*}, {agent.*}
# The literal string "{{role}}" is replaced with the contents of role.md.
system: |
  You are responsible for the events module at {node.file_path}.
  {{role}}
  Work carefully. Append to notes.md when you learn something important.
  Always append one line to log.jsonl at the end of every turn.

# ── Context pipeline ──────────────────────────────────────────────────────────
# Steps run before the LLM turn. Each step's output is stored as $step_name
# for interpolation in later steps' args.
context:
  - name: role
    tool: read_file
    args:
      path: role.md

  - name: notes
    tool: read_file
    args:
      path: notes.md
    optional: true      # skipped (not failed) if notes.md doesn't exist yet

  - name: source
    tool: read_file
    args:
      path: "{node.file_path}"

  - name: recent_events
    tool: read_recent_events
    args:
      node_id: "{node.id}"
      limit: 10

  - name: callers
    tool: graph_neighbors
    args:
      node_id: "{node.id}"
      direction: in
      limit: 20

# ── Interactive tools ─────────────────────────────────────────────────────────
# Named .pym tools the LLM can call during the turn.
tools:
  - write_file           # write to workspace (notes.md, log.jsonl, todo.md, etc.)
  - emit_event           # signal other agents
  - emit_schema          # evolve own schema.yaml
  - graph_add_edge       # record discovered relationships
  - graph_neighbors      # query neighbors interactively

# ── Event subscriptions ───────────────────────────────────────────────────────
# What events trigger this agent.
subscriptions:
  - event_type: ContentChangedEvent
    node_id: "{node.id}"
  - event_type: DirectMessageEvent
    to_agent: "{agent.id}"

# ── Turn control ──────────────────────────────────────────────────────────────
max_turns: 5
termination: "done"
```

### 2.3 Template variables

Template variables are resolved at activation time from static agent context —
things known before the LLM sees anything:

| Variable | Resolves to |
|----------|------------|
| `{node.id}` | The agent's code node ID |
| `{node.file_path}` | The file path the agent is responsible for |
| `{node.name}` | The name of the function/class/module |
| `{node.full_name}` | Fully qualified name (e.g., `remora.core.events.events`) |
| `{node.kind}` | Node kind from discovery (e.g., `python:module`) |
| `{agent.id}` | The runtime agent ID |
| `{agent.name}` | The agent's name field |
| `{{role}}` | Inline substitution: full contents of `role.md` |
| `{{notes}}` | Inline substitution: full contents of `notes.md` |

The double-brace `{{...}}` form inlines file contents directly into a string
field. The single-brace `{...}` form substitutes scalar values. Both are
resolved before the context pipeline runs.

### 2.4 The `optional` step flag

Context steps can be marked `optional: true`. An optional step that fails
(file not found, tool error) contributes an empty string to `$step_name`
and the pipeline continues. A non-optional failed step aborts the turn with
a `CONTEXT_STEP_FAILURE` outcome.

This is critical for first-activation resilience: `notes.md` doesn't exist
yet on first activation, so the notes step must be optional. The agent writes
`notes.md` during that turn; on the next activation it exists.

### 2.5 The `input_gate` step type

For interactive steps where the agent needs human input before proceeding:

```yaml
context:
  - name: human_clarification
    type: input_gate          # pauses pipeline, prompts user in companion
    prompt: |
      I found a potential issue with {node.name}. Please clarify:
      What is the expected behavior when the input is None?
    timeout: 300              # seconds; if no response, skip and continue
```

This maps directly to the `InputGate` primitive in `primitives.py`.

### 2.6 YAML vs TOML for each file

| File | Format | Rationale |
|------|--------|-----------|
| `schema.yaml` | YAML | Multi-line system prompt, nested context steps, anchors for reuse |
| `role.md` | Markdown | Free-form prose, no structure needed, human-readable |
| `notes.md` | Markdown | Accumulated prose, occasional headers for organization |
| `log.jsonl` | JSONL | One structured record per activation; easy to append; grep-friendly |
| `todo.md` | Markdown | Free-form task list; agent uses `- [ ]` / `- [x]` syntax |
| `capabilities.yaml` | YAML | Short list, runtime-written; YAML is clean for lists |
| `working_memory.md` | Markdown | Scratchpad; overwritten not accumulated |
| `tools/*.pym` | Grail | Grail source; compiled by the Grail compiler |

TOML is deliberately NOT used for `schema.yaml`. Multi-line strings in TOML
require `"""..."""` syntax which is awkward for LLMs to generate inside a
larger document. YAML's `|` block scalar is more natural for system prompts.

---

## 3. YAML Composition: Extends and Anchors

### 3.1 The composition problem

Without composition, every `schema.yaml` duplicates the same boilerplate:
the `role` step, the `notes` step, the common tools. The YAML equivalent of
class inheritance is needed.

YAML has two built-in mechanisms (anchors/aliases and merge keys) that cover
inline reuse within a single file. The `extends` keyword handles cross-file
inheritance at the application level.

### 3.2 YAML anchors for inline reuse

Anchors (`&anchor`) and aliases (`*alias`) allow inline reuse within a
single document:

```yaml
# Common context steps defined once at the top of the file
_base_steps: &base_steps
  - name: role
    tool: read_file
    args: {path: role.md}
  - name: notes
    tool: read_file
    args: {path: notes.md}
    optional: true
  - name: source
    tool: read_file
    args: {path: "{node.file_path}"}

_base_tools: &base_tools
  - write_file
  - emit_event
  - emit_schema

# The schema body uses anchors:
context:
  - *base_steps                     # inline the three base steps
  - name: current_doc
    tool: extract_docstring
    args: {path: "{node.file_path}"}

tools:
  - *base_tools                     # inline the three base tools
  - rewrite_docstring
```

Anchors are agent-local — useful for structuring a complex single `schema.yaml`
without repetition. They can't reference another file.

### 3.3 The `extends` keyword (application-level)

The runtime interprets an `extends` key as a filename of a base schema to
load. The base schema is loaded first; the child schema's fields are merged
on top:

```yaml
# bootstrap/agents/bases/code_agent.yaml
version: "1"
capabilities:
  - file_read
  - file_write
  - graph_read
  - event_emit
  - schema_evolve
context:
  - name: role
    tool: read_file
    args: {path: role.md}
  - name: notes
    tool: read_file
    args: {path: notes.md}
    optional: true
  - name: source
    tool: read_file
    args: {path: "{node.file_path}"}
tools:
  - write_file
  - emit_event
  - emit_schema
max_turns: 5
termination: "done"
```

```yaml
# docstring_reviewer.yaml (agent workspace OR bootstrap/agents/definitions/)
extends: code_agent         # resolved from bootstrap/agents/bases/
name: docstring_reviewer

# context.append adds steps AFTER the base context (does not replace it)
context:
  append:
    - name: current_doc
      tool: extract_docstring
      args: {path: "{node.file_path}"}
    - name: drift_score
      tool: score_docstring_alignment
      args: {docstring: "$current_doc", source: "$source", threshold: "0.75"}

# tools.append adds to the base tool list (union)
tools:
  append:
    - rewrite_docstring

# scalar overrides
max_turns: 3
```

### 3.4 Merge semantics

| Field type | Merge behavior |
|------------|---------------|
| Scalar (`name`, `max_turns`, `termination`) | Child overrides parent |
| `system` | Child replaces parent; `system: append: "..."` appends to parent |
| `context` list | Parent steps first; `context.append` adds after |
| `context.replace` | Replaces parent context entirely |
| `tools` list | Union of parent + child; `tools.replace` replaces |
| `capabilities` list | Union of parent + child |
| `subscriptions` list | Union of parent + child |

**Single inheritance only.** One `extends` per schema, max two levels deep
(base → concrete). More than two levels of inheritance creates fragile,
hard-to-read definitions — the same lesson from v1's agent architecture.

### 3.5 Capability preset bundles

Named capability presets stored in `bootstrap/agents/capabilities/` that
schemas can reference by name:

```yaml
# bootstrap/agents/capabilities/code_reader.yaml
capabilities:
  - file_read
  - graph_read
  - event_read

# bootstrap/agents/capabilities/code_writer.yaml
extends: code_reader
capabilities:
  append:
    - file_write
    - event_emit
    - schema_evolve

# bootstrap/agents/capabilities/graph_author.yaml
extends: code_writer
capabilities:
  append:
    - graph_write
```

A schema references a preset:

```yaml
capabilities_preset: code_writer   # loads the preset
capabilities:
  append:
    - graph_read                   # add anything beyond the preset
```

The presets ARE the capability ladder in file form. They're human-readable
documentation of what each tier means, version-controllable, and browsable
from the companion sidebar's capabilities section.

---

## 4. The Self-Bootstrapping Path

### 4.1 Why YAML is uniquely suited for LLM generation

When an agent runs `DEFAULT_SCHEMA` on first activation, the LLM must
produce a `schema.yaml` from scratch. This works well because:

1. **LLMs know YAML deeply.** It's ubiquitous in training data (CI/CD
   configs, Kubernetes manifests, GitHub Actions). LLMs generate valid
   YAML reliably without fine-tuning.

2. **The format is self-describing.** Comments in the format (like those
   in §2.2) can be included in the `emit_schema` tool description as a
   live template, giving the LLM a clear pattern to follow.

3. **Validation gives clear feedback.** If the LLM produces invalid YAML
   or a schema that requests capabilities it doesn't have, `emit_schema`
   returns a structured error. The LLM corrects it in the same turn.

4. **The schema IS documentation.** A developer reading `schema.yaml`
   immediately understands what the agent does. No code to trace.

### 4.2 The DEFAULT_SCHEMA for YAML-based bootstrapping

The DEFAULT_SCHEMA is defined in Python (since it's runtime-provided) but
prompts the agent to produce YAML:

```python
DEFAULT_SCHEMA = TurnSchema(
    system=Concat(parts=(
        "You are a Remora agent node responsible for: ",
        ToolRef("read_file", {"path": "role.md"}),
        "\n\nYour workspace is currently empty. Your job this turn:\n"
        "1. Read your node's source file to understand your responsibility\n"
        "2. Write role.md: clear prose describing your purpose\n"
        "3. Write notes.md: one initial note about what you're responsible for\n"
        "4. Call emit_schema with a schema.yaml definition for your future turns\n"
        "5. Append one line to log.jsonl recording this activation\n\n"
        "The emit_schema tool description shows the exact schema.yaml format.",
    )),
    context=ContextPipeline(steps=(
        Step("role", ToolRef("read_file", {"path": "role.md"})),
        Step("source", ToolRef("read_file", {"path": "{node.file_path}"})),
    )),
    tools=("read_file", "write_file", "emit_schema"),
    max_turns=3,
    termination="done",
)
```

The `emit_schema` tool description (in its `.pym` docstring or runtime
description) includes the minimal template from §4.4 — the LLM fills it in.

### 4.3 Step-by-step: first activation to mature agent

```
Phase 0: Node discovered
  runtime: creates agent node in graph (kind="agent.profile")
  runtime: creates empty cairn workspace
  workspace: {} (empty)

Phase 1: First activation → DEFAULT_SCHEMA
  Context pipeline:
    $role = "" (role.md absent, optional step)
    $source = <full source of the node's file>

  LLM receives: system prompt + source
  LLM calls: write_file("role.md", "I am responsible for...")
  LLM calls: write_file("notes.md", "# Notes\n## [date] — activation #1\nInitial note...")
  LLM calls: emit_schema("<schema.yaml content>")
    → runtime validates YAML
    → runtime checks declared capabilities ⊆ granted capabilities
    → runtime stores schema.yaml atomically
    → returns: {"status": "ok", "context_steps": 5, "tools": 4}
  LLM calls: write_file("log.jsonl", append one JSON line)
  LLM outputs: "done"

  workspace now contains: role.md, notes.md, schema.yaml, log.jsonl

Phase 2: Second activation (triggered by ContentChangedEvent)
  runtime: finds schema.yaml → loads it → resolves template vars
  Context pipeline (from schema.yaml):
    $role = <contents of role.md>
    $notes = <contents of notes.md>
    $source = <current source of the node's file>
    $recent_events = [ContentChangedEvent, ...]
    $callers = [caller graph nodes...]

  LLM: does its actual job
  LLM calls: write_file("notes.md", appends new entry)
  LLM calls: emit_event("SchemaStableEvent", {...})
  LLM calls: write_file("log.jsonl", appends)
  LLM outputs: "done"

Phase N: Mature agent (after many activations)
  schema.yaml has evolved: more context steps, richer tools, refined subscriptions
  notes.md has grown: periodic summaries, accumulated insights
  log.jsonl has history: 50+ activations, pattern visible in outcomes
  todo.md: tracking multi-activation tasks
  The agent knows itself.
```

### 4.4 What the LLM is guided to write

The `emit_schema` tool shows the LLM a minimal template in its description:

```yaml
# Minimal schema.yaml template
# Customize this for your specific node. Comments are allowed.

version: "1"
name: your_agent_name_here      # use snake_case

capabilities:
  # Start with what you've been granted. Check capabilities.yaml.
  - file_read
  - file_write
  - schema_evolve
  # Add if needed (only if granted):
  # - graph_read
  # - event_emit

system: |
  You are responsible for {node.full_name} at {node.file_path}.
  {{role}}
  Keep notes.md updated. Log every activation to log.jsonl.

context:
  - name: role
    tool: read_file
    args: {path: role.md}
  - name: notes
    tool: read_file
    args: {path: notes.md}
    optional: true
  - name: source
    tool: read_file
    args: {path: "{node.file_path}"}
  # Add more steps as you discover you need them

tools:
  - write_file         # for notes.md, log.jsonl, todo.md
  - emit_schema        # to evolve this schema
  # Add tools as granted

max_turns: 5
termination: "done"
```

### 4.5 Iterative schema evolution

Self-bootstrapping is not one-time. Agents evolve their schemas continuously:

| Activation | Schema change |
|-----------|---------------|
| 1 | Write initial schema.yaml (minimal: role + notes + source) |
| 5 | Add `graph_neighbors` step (discovered it needs caller context) |
| 12 | Add `drift_score` step (adopted from neighbor via schema diffusion) |
| 20 | Request `graph_write` capability; add `graph_add_edge` tool after grant |
| 30 | Add `input_gate` step (learned it needs human confirmation for risky edits) |
| 50+ | Schema is mature — changes are rare refinements |

Each evolution: the agent calls `emit_schema` with the updated YAML string.
The runtime stores the new version atomically; `schema.prev.yaml` retains the
previous version for rollback.

---

## 5. Notes, Logs, and Working Memory

### 5.1 The case for workspace-as-memory

v2 proposed specific memory model: `memory.episode` and `memory.insight` as
first-class graph node kinds with defined fields, TTLs, and distillation
workflows. v3 rejects this as over-specification.

The workspace-as-memory model offers something better: the agent's cairn
workspace IS its memory, in whatever form it finds useful. The substrate
provides `read_file` and `write_file`. The agent decides what to store.

But there are strong conventional defaults — file names the companion sidebar
knows to render, that the DEFAULT_SCHEMA includes in context by default, and
that developers expect to find when inspecting an agent.

### 5.2 notes.md — accumulated knowledge

`notes.md` is an append-mostly Markdown file. The agent adds entries as it
learns things across activations:

```markdown
# Notes — src/remora/core/events/events.py

## 2026-03-08T14:32:01Z — activation #12
ContentChangedEvent is imported by 33 modules. Signature should be considered
frozen — changes have very high blast radius. Flagged to maintainer.

## 2026-03-08T09:15:44Z — activation #8
StructuredEvent union type has 14 variants and growing. Consider proposing
a discriminated union pattern. Added to todo.md.

## 2026-03-07T16:00:12Z — activation #1
Initialized. Primary responsibility: keeping event type signatures stable
and coherent as the codebase evolves.
```

The format is agent-defined. The runtime doesn't parse `notes.md`. The
companion sidebar renders it as Markdown. The agent reads it as `$notes` in
its context pipeline — its long-term memory, always available.

**Growth management:** `notes.md` will eventually grow too large for the
context window. The agent is expected to prune or summarize it periodically:
overwrite old notes with summaries, archive sections to `notes/archive/`.
This self-management is the agent's responsibility — emergence in action.
An agent that ignores notes growth will notice context bloat and learn to
manage it. The runtime provides no automatic pruning.

### 5.3 log.jsonl — activation log

One structured JSON line per activation, appended by the agent at turn end:

```jsonl
{"ts":"2026-03-08T14:32:01Z","activation":12,"trigger":"ContentChangedEvent:evt_abc","outcome":"done","turns":3,"tools":["write_file","emit_event"],"emitted":["SignatureChangeProposedEvent"]}
{"ts":"2026-03-08T09:15:44Z","activation":8,"trigger":"ContentChangedEvent:evt_def","outcome":"done","turns":2,"tools":["write_file"],"emitted":[]}
{"ts":"2026-03-07T16:00:12Z","activation":1,"trigger":"NodeDiscoveredEvent:node_xyz","outcome":"bootstrapped","turns":1,"tools":["write_file","emit_schema"],"emitted":[]}
```

**Why JSONL:**
- Appendable: one line per turn, no full-file rewrite needed
- Grep-friendly: `grep "SignatureChangeProposedEvent" log.jsonl`
- Structured: any log line is parseable by other agents or developer tools
- Human-readable: `jq . log.jsonl | head -5` gives pretty output

The companion sidebar parses `log.jsonl` for the LOG section, showing the
last N activations with timestamps and outcomes.

### 5.4 todo.md — pending work

```markdown
# Todo — src/remora/core/events/events.py

- [ ] Investigate why ContentChangedEvent is imported by 33 modules
- [ ] Propose discriminated union for StructuredEvent (see notes activation #8)
- [x] Write role.md (activation #1)
- [x] Add graph_neighbors context step to schema (activation #5)
```

Standard Markdown checkbox syntax. The agent maintains this across activations.
The companion sidebar can render checkboxes as interactive — a developer can
check/uncheck items directly, writing back to the workspace. The agent sees
the change on next activation.

### 5.5 working_memory.md — turn scratchpad

Unlike `notes.md` (accumulated) and `log.jsonl` (structured history),
`working_memory.md` is typically overwritten each activation. It's the agent's
scratchpad for the current turn's reasoning:

```markdown
# Working Memory — activation #12, 2026-03-08T14:32:01Z

## Trigger analysis
ContentChangedEvent: events.py changed. File hash: abc123 → def456.

## My current understanding
- ContentChangedEvent signature: UNCHANGED ✓
- StructuredEvent union: NullResponseEvent added (new variant)
- NullResponseEvent callers via graph: 0 callers (new type, no adopters yet)

## Decision
- Low risk: no existing code depends on NullResponseEvent yet
- Will emit SchemaStableEvent to signal callers don't need to update
- Will note the new variant in notes.md for future reference
```

The LLM writes this as it works through the problem. On the next activation,
it's overwritten with fresh analysis. `notes.md` gets the distilled insight;
`working_memory.md` gets the live reasoning.

Whether to include `working_memory.md` in the context pipeline is up to the
agent — some agents include it for continuity in long multi-turn analyses,
others don't because last turn's scratchpad isn't relevant to this turn.

### 5.6 Making memory first-class in DEFAULT_SCHEMA

The DEFAULT_SCHEMA prompts agents to establish their memory files from the
very first activation:

```
Your workspace contains these conventional files. Create them now:
- role.md:           Who you are and what you're responsible for
- schema.yaml:       Your turn definition (via emit_schema)
- notes.md:          Start with one entry about your initial assessment
- log.jsonl:         One JSON line per activation — write one now

These are YOUR files. Read them in every turn. Write to them whenever
you learn something worth remembering or complete a significant action.
```

Memory management as a habit from activation 1, not something agents
discover they need on activation 20.

---

## 6. Companion Sidebar Rendering

### 6.1 The sidebar as a workspace file viewer

The companion sidebar (Neovim plugin) shows the focused node's agent state.
With workspace-as-identity, the sidebar is a structured viewer of the agent's
workspace files — no special protocol, no separate data format. It reads the
same files the agent reads:

```
┌─────────────────────────────────────────────────────────┐
│ ◈ AGENT  events_module_agent              [idle] [↺]    │
│   src/remora/core/events/events.py                      │
│   CAPS: file_r file_w graph_r event_e schema_e          │
├─────────────────────────────────────────────────────────┤
│ ▸ ROLE                                          [edit]  │
│   I maintain the events module. My primary              │
│   responsibility is keeping event type signatures       │
│   stable and coherent as the codebase evolves.          │
├─────────────────────────────────────────────────────────┤
│ ▸ SCHEMA  (5 context steps, 5 tools)           [open]   │
│   context: role → notes → source → recent_events        │
│            → callers                                    │
│   tools: write_file, emit_event, emit_schema,           │
│          graph_add_edge, graph_neighbors                │
│   subs: ContentChangedEvent, DirectMessageEvent         │
├─────────────────────────────────────────────────────────┤
│ ▸ NOTES  (activation #12, 3 entries)           [open]   │
│   2026-03-08  ContentChangedEvent: 33 imports.          │
│              Signature flagged as frozen.               │
│   2026-03-08  StructuredEvent: 14 variants. Propose     │
│              discriminated union? (todo)                │
│                                           [+1 earlier]  │
├─────────────────────────────────────────────────────────┤
│ ▸ TODO  (2 open, 2 done)                       [edit]   │
│   ○ Investigate 33-module ContentChangedEvent imports   │
│   ○ Propose discriminated union for StructuredEvent     │
│   ● Write role.md                                       │
│   ● Add graph_neighbors context step                    │
├─────────────────────────────────────────────────────────┤
│ ▸ LOG  (12 activations)                                 │
│   14:32  ContentChanged → done (3 turns)                │
│   09:15  ContentChanged → done (2 turns)                │
│   yesterday  NodeDiscovered → bootstrapped (1 turn)     │
└─────────────────────────────────────────────────────────┘
```

### 6.2 Sidebar section → workspace file mapping

| Sidebar section | Source file | Rendering |
|----------------|-------------|-----------|
| Header (name, status, caps) | `capabilities.yaml` + graph node | Parsed metadata |
| ROLE | `role.md` | Markdown → plain text, truncated to ~4 lines |
| SCHEMA | `schema.yaml` | Parsed: context step names, tool names, sub count |
| NOTES | `notes.md` | Markdown headings → entries; show last 2, link to rest |
| TODO | `todo.md` | Parsed `- [ ]` / `- [x]`; interactive checkboxes |
| LOG | `log.jsonl` | Parsed JSON lines; timestamp + outcome summary |

### 6.3 Sidebar interactivity

**[edit] buttons:** Open the workspace file in a floating Neovim buffer.
Saving writes back to the cairn workspace (via the companion LSP write API).

**[open] buttons:** Open the full file in a read-only preview buffer,
with `e` to switch to edit mode.

**TODO checkboxes:** Click (or `<Space>` in the sidebar buffer) to toggle.
Writes `- [x]` or `- [ ]` directly to `todo.md`. The agent sees the change
on its next activation.

**[↺] refresh button:** Manually re-read all workspace files and update the
sidebar. Normally this happens automatically after each agent activation.

**[+N earlier]:** Expands to show older notes entries in the sidebar buffer.

### 6.4 Real-time update loop

```
Developer edits source code
  → ContentChangedEvent fires
  → Agent activates
  → Agent writes notes.md (append), log.jsonl (append), emits event
  → submit_result() → AgentActivationCompleteEvent
  → Companion receives event, re-reads workspace files
  → Sidebar sections refresh
  → Developer sees updated NOTES and LOG in sidebar
```

The workspace is the source of truth. The sidebar is a live view of it.
No special notification protocol — the companion just re-reads files after
each activation complete signal.

### 6.5 Why this beats a custom data format

The alternative would be a custom companion protocol where agents report
their state via structured API calls. The workspace approach is better:

- **Agent changes are self-describing.** The agent writes to `notes.md`
  with no knowledge of who's reading it. The companion reads `notes.md`
  with no knowledge of who wrote it. There's no coupling.
- **Developers can read the same files.** Open `.remora/<swarm_id>/agents/<id>/`
  in any text editor and you see exactly what the companion sidebar shows.
- **No format drift.** The companion renders whatever the agent writes.
  If the agent evolves its notes format, the sidebar renders the new format.
- **External tools work.** `grep`, `jq`, `ripgrep` against workspace files
  work exactly as expected. No custom tooling needed.

---

## 7. Developer Authoring Workflow

### 7.1 File layout for developer-authored definitions

```
bootstrap/agents/
  bases/
    code_agent.yaml         ← base for code-responsible agents
    meta_agent.yaml         ← base for coordination/meta agents
  capabilities/
    code_reader.yaml        ← FILE_READ + GRAPH_READ + EVENT_READ
    code_writer.yaml        ← extends code_reader + FILE_WRITE + EVENT_EMIT + SCHEMA_EVOLVE
    graph_author.yaml       ← extends code_writer + GRAPH_WRITE
    privileged.yaml         ← extends graph_author + PRIVILEGED + TOOL_SYNTHESIZE
  definitions/
    docstring_reviewer.yaml ← extends code_writer
    signature_watcher.yaml  ← extends graph_author
    test_coverage.yaml      ← extends code_writer
  seed/
    maintainer.yaml         ← the bootstrap maintainer (privileged, pre-seeded)
    tool_builder.yaml       ← the tool synthesis agent (tool_synthesize, pre-seeded)
```

The runtime discovers all `.yaml` files in `definitions/` and `seed/` at
startup and loads them into the `AgentCatalog`. These are the seed definitions
that initialize agent workspaces on first activation.

### 7.2 Developer authoring in practice

A developer creating a new agent type:

1. Create `bootstrap/agents/definitions/my_agent.yaml`
2. Choose a base (`extends: code_writer`) and a capability preset
3. Add domain-specific context steps and tools
4. Save → runtime hot-reloads the catalog
5. Validation result appears in editor diagnostics (LSP)
6. On next `NodeDiscoveredEvent` matching this definition's scope, the agent
   gets the definition's content as its initial `role.md` and `schema.yaml`

### 7.3 Seeding vs. letting agents self-define

Two modes for agent initialization:

**Seeded (developer-defined):**
Developer writes `bootstrap/agents/definitions/docstring_reviewer.yaml`.
When a node matching this type is discovered, the runtime writes the
definition's `schema.yaml` content directly to the agent's workspace.
The agent's first activation runs with the developer-provided schema.

**Self-defined (DEFAULT_SCHEMA):**
No developer definition matches this node type. The runtime uses
DEFAULT_SCHEMA. The agent writes its own `role.md` and `schema.yaml` on
first activation based on what it discovers about its code node.

Both modes result in the same file in the workspace: `schema.yaml`. The
agent can't tell whether it was developer-seeded or self-written. On
subsequent activations, both paths run the same loading pipeline.

This is intentional: seed definitions are suggestions. The agent may evolve
beyond the seed. The seed is just a faster first-activation.

### 7.4 Hot-reload

YAML files in `bootstrap/agents/` support hot-reload during development:

1. Runtime watches `bootstrap/agents/**/*.yaml` for mtime changes
2. On change: re-parse, update `AgentCatalog`, validate
3. Mark agents whose workspace schema derives from the changed definition
   as `needs_refresh`
4. On next activation: re-generate `schema.yaml` from updated definition
   (if the agent hasn't diverged from its seed)

No restart required. The development loop: edit YAML → save → next agent
activation uses the updated schema.

---

## 8. Runtime Loading and Validation

### 8.1 The loading pipeline

On each activation:

```
1. Read schema.yaml from cairn workspace
   → Absent: use DEFAULT_SCHEMA, skip to step 7

2. Parse YAML → dict
   → Parse error: log SCHEMA_PARSE_FAILURE, use DEFAULT_SCHEMA

3. Resolve extends chain (max 1 hop from workspace schema)
   → Load base from bootstrap/agents/bases/{name}.yaml
   → Merge fields per §3.4 semantics

4. Resolve capabilities_preset
   → Load from bootstrap/agents/capabilities/{name}.yaml
   → Merge capability list

5. Validate against Pydantic model
   → AgentSchemaYaml.model_validate(merged_dict)
   → Failure: log SCHEMA_VALIDATION_FAILURE, use DEFAULT_SCHEMA

6. Check declared capabilities ⊆ granted capabilities
   → Read capabilities.yaml (runtime-maintained)
   → Violation: CAPABILITY_VIOLATION, reject activation

7. Resolve template variables {node.*}, {agent.*}
   → Replace all occurrences in system, context args, subscription filters

8. Convert to TurnSchema
   → AgentSchemaYaml.to_turn_schema() → TurnSchema

9. Run turn executor with TurnSchema
```

### 8.2 The Pydantic validation model

```python
class ContextStepYaml(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    tool: str = ""
    args: dict[str, str] = Field(default_factory=dict)
    optional: bool = False
    type: Literal["tool", "input_gate"] = "tool"
    prompt: str | None = None   # for input_gate only
    timeout: int | None = None  # for input_gate only

class AgentSchemaYaml(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    name: str = ""
    extension_name: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    capabilities_preset: str | None = None
    extends: str | None = None
    system: str = ""
    context: list[ContextStepYaml] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    subscriptions: list[dict[str, str]] = Field(default_factory=list)
    max_turns: int = Field(default=5, ge=1, le=20)
    termination: str = "done"

    @field_validator("tools")
    def tools_must_exist(cls, tools):
        """All tool names must be in the known tool catalog."""
        ...

    def to_turn_schema(self, template_vars: dict) -> TurnSchema:
        """Resolve template vars and convert to runtime TurnSchema."""
        ...
```

`extra="forbid"` catches unknown keys immediately — no silent typo failures.
The `tools_must_exist` validator checks tool names against the catalog at
load time, not at execution time.

### 8.3 The emit_schema tool

`emit_schema` is a `.pym` system tool available to all agents with the
`SCHEMA_EVOLVE` capability. It takes the YAML content as a string:

```python
# Pseudocode for emit_schema.pym behavior
@external
def read_file(path: str) -> str: ...

@external
def write_file(path: str, content: str) -> str: ...

# The tool:
def emit_schema(yaml_content: str) -> str:
    """
    Validate and store a new schema.yaml for this agent.

    Args:
        yaml_content: The complete schema.yaml content as a string.

    Returns:
        Success: {"status": "ok", "context_steps": N, "tools": M}
        Failure: {"status": "error", "message": "...", "line": N}

    Format reference:
    [the minimal template from §4.4 is shown here]
    """
    # runtime handles actual validation + storage
```

The return value gives the LLM immediate feedback. On failure, the message
is specific ("line 14: unknown capability 'graph_synthesize'") so the LLM
can correct it in the same turn without a new activation.

### 8.4 Schema versioning and migration

The `version: "1"` field enables forward migration. When the format changes:

1. Increment version → `version: "2"`
2. Write migration: `migrate_schema_v1_to_v2(d: dict) -> dict`
3. Runtime detects `version: "1"` at load time, runs migration, stores migrated
   schema (atomically, preserving `schema.prev.yaml`)

Agents don't manually update their schemas — the runtime migrates transparently.
The agent's next `emit_schema` call produces a v2 schema naturally (the tool
description shows the current version template).

---

## 9. Capability Declaration in YAML

### 9.1 Capabilities in schema.yaml

The `capabilities` list in `schema.yaml` is the agent's **declaration** of
what it needs, not an assertion of what it has. The runtime enforces the grant:

```yaml
capabilities:
  - file_read
  - file_write
  - schema_evolve
  # Requesting graph_read → will fail activation until granted
  - graph_read
```

If any declared capability is not in the agent's granted set (from
`capabilities.yaml`), activation fails with a clear error:

```
CAPABILITY_VIOLATION: schema.yaml declares 'graph_read' but agent has not been
granted this capability yet.
Current grants: file_read, file_write, schema_evolve
To request it: use write_file to create capability_requests.md and emit
RequestCapabilityEvent with {"capability": "graph_read", "evidence_path": "capability_requests.md"}
```

The agent learns: it can't just declare capabilities. It must request them,
justify the request, and wait for the grant.

### 9.2 capabilities.yaml — the runtime grant file

The runtime writes and maintains this file in every agent workspace:

```yaml
# capabilities.yaml
# Runtime-maintained. Read-only for the agent.
# Updated when GrantCapabilityEvent or RevokeCapabilityEvent is processed.

version: "1"
agent_id: "agent:events_module_abc123"

granted:
  - file_read
  - file_write
  - schema_evolve
  - graph_read     # granted 2026-03-08

history:
  - capability: graph_read
    granted_at: "2026-03-08T10:00:00Z"
    granted_by: "agent:maintainer_001"
    justification: >
      Agent demonstrated stable file_write behavior over 10 activations.
      Requested graph_read to track caller relationships.
```

The companion sidebar reads this for the CAPS display. Developers can see
exactly what capabilities are granted and why, and the full grant history.

### 9.3 The request/grant flow via workspace files

```
Agent (events_module) wants graph_read:

1. Agent writes capability_requests.md:
   "# Capability Request: graph_read
   I discovered that ContentChangedEvent is imported by 33 modules (see notes.md).
   I need graph_read to query caller relationships and include them in my context.
   Evidence: activations #8, #10, #12 all needed caller info."

2. Agent emits RequestCapabilityEvent:
   {"capability": "graph_read", "agent_id": "...", "evidence_path": "capability_requests.md"}

3. Maintainer agent activates:
   - Reads capability_requests.md from requester's workspace
   - Reads requester's notes.md and log.jsonl for context
   - Evaluates: does the justification make sense? is the agent stable?
   - Decides: grant

4. Maintainer emits GrantCapabilityEvent:
   {"capability": "graph_read", "to_agent": "...", "rationale": "..."}

5. Runtime updates capabilities.yaml (requester's workspace)
   Runtime rebuilds agent's externals dict for next activation

6. Next activation: agent's schema.yaml's graph_read declaration is now valid
   Agent gets graph_node, graph_neighbors, graph_find_nodes in its dict
```

The entire flow is auditable. The evidence is in the workspace. The decision
is in the grant history. Any developer can read the full story in the sidebar.

---

## 10. Trade-offs and Open Questions

### 10.1 What YAML does exceptionally well

**Emergent self-definition:** An agent that writes `schema.yaml` is authoring
its own definition in the same workspace where it keeps its notes. The format
is data, not code. The LLM can generate it without fine-tuning. The agent
can iterate on it across many activations.

**Companion sidebar legibility:** Every file in the workspace is a sidebar
section. The sidebar doesn't need a special protocol. A developer reading the
sidebar and a developer opening the raw files see the same thing.

**Mutual authorship:** Developer-authored seed schemas and agent-authored
evolved schemas use exactly the same format. A developer can inspect any
agent's `schema.yaml` and understand what it does without knowing whether
a human or the agent wrote it.

**LLM validation loop:** The `emit_schema` tool returns structured errors
with line numbers. The LLM can correct YAML in the same turn. The format's
simplicity makes correction obvious.

**Audit trail:** `log.jsonl` + `notes.md` + `capabilities.yaml.history` +
`schema.prev.yaml` together give a complete audit trail of what the agent
has done, learned, and evolved into. Nothing is lost.

### 10.2 What YAML does poorly

**Complex composition:** Beyond one `extends` level, YAML composition becomes
fragile. A Python developer who wants to express a three-level hierarchy needs
either to flatten it (write a longer YAML file) or accept that agents use the
Pydantic authoring layer. The mitigation: YAML is the substrate format;
Pydantic classes are the developer authoring format. Agents write YAML;
developers can write either.

**Conditional logic:** No conditional expressions in YAML. An agent that needs
"if node is a function, include the function context step; if a class, include
the class context step" can't express this. Mitigation: write a custom `.pym`
tool that checks the node kind and returns the appropriate context. Keeps the
schema.yaml clean.

**Dynamic step counts:** A pipeline where the number of steps depends on
runtime data (e.g., "one step per caller") can't be expressed in YAML. Same
mitigation: write a `.pym` tool that assembles the combined result as a single
step output.

**Type safety:** Tool name typos produce activation-time errors rather than
load-time errors — unless the schema validation catches them (§8.2 validator
checks tool names against catalog). This is the key mitigation.

### 10.3 The Pydantic bridge: two formats, one runtime

YAML and Pydantic are complementary, not competing:

```
Developer authors:     Python AgentDefinition class (Pydantic)
                              ↓
                       serialize to YAML → bootstrap/agents/definitions/
                              ↓
                       stored in agent workspace as schema.yaml
                              ↓
Agent authors:         YAML string → emit_schema
                              ↓
                       AgentSchemaYaml.model_validate(yaml.safe_load(content))
                              ↓
                       AgentSchemaYaml.to_turn_schema(template_vars)
                              ↓
Runtime executes:      TurnSchema (the same runtime object either way)
```

At runtime, both paths converge on the same `TurnSchema`. The Pydantic model
is the authoritative schema definition. YAML is the serialization format that
both humans and LLMs can author. There is no impedance mismatch.

### 10.4 Open questions

**Cross-agent workspace reads:** Can a context step read from another agent's
workspace? Currently: no (cairn-only). But `role.md` and `notes.md` from
neighboring agents would be very useful context. A new external:
`read_agent_file(agent_id, path)` with permission gating (only agents the
maintainer has granted cross-read access can use it) would enable this. Worth
exploring for M4+.

**notes.md growth management:** Currently left entirely to the agent. Two
options: (1) provide a `summarize_notes` tool backed by an LLM call, or
(2) recommend the agent use dated subdirectories (`notes/2026-03.md`) as a
natural archive pattern. Option (2) preserves emergence; option (1) pre-answers
a question agents might solve differently.

**schema.yaml as the single source of truth vs. graph node:** Currently the
agent's `capabilities` frozenset is stored in the graph node (kind="agent.profile").
`capabilities.yaml` in the workspace is the runtime-maintained copy. These
must stay in sync. The graph is the authoritative source (for queries);
`capabilities.yaml` is the workspace copy (for agent reads). The runtime
writes both atomically on grant/revoke.

**Companion write-back and agent activation:** When a developer edits
`todo.md` via the sidebar, should this trigger an agent activation? Currently:
no, the edit is passive. But a useful pattern: `DirectMessageEvent` fires
when the developer edits `todo.md`, triggering the agent to respond to the
developer's task change. This would make the sidebar a two-way communication
channel, not just a view.

**schema.yaml in version control:** Agent-authored `schema.yaml` files live in
`.remora/` which is likely gitignored. Developer-authored seed definitions
live in `bootstrap/agents/` which IS version-controlled. The two are separate.
But a developer might want to snapshot a mature agent's evolved `schema.yaml`
into version control to make it a new seed definition. A `remora agents
extract <agent_id> --to bootstrap/agents/definitions/` command would handle this.
