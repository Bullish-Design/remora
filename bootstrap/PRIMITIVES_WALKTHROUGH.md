# Bootstrap Primitives: Example Walkthrough

> A progressive guide through `primitives.py` with concrete scenarios.
> Each example builds on the previous. The final scenario shows the
> self-bootstrapping pattern the whole system is designed around.

---

## Table of Contents

1. [The evaluation model](#1-the-evaluation-model)
   How the runtime resolves a TurnSchema into an actual LLM call.

2. [Scenario A: Static schema](#2-scenario-a-static-schema)
   The base case. No tool calls, no context pipeline, just text.

3. [Scenario B: Reading context with ToolRef](#3-scenario-b-reading-context-with-toolref)
   A schema that reads the agent's own source file before the LLM sees it.

4. [Scenario C: Chaining steps](#4-scenario-c-chaining-steps)
   Using `$step_name` to feed one step's output into the next step's args.

5. [Scenario D: Composing the system prompt with Concat](#5-scenario-d-composing-the-system-prompt-with-concat)
   Building a dynamic system prompt from multiple ToolRef pieces.

6. [Scenario E: Collecting user input with InputGate](#6-scenario-e-collecting-user-input-with-inputgate)
   Pausing context assembly to ask the user a question.

7. [Scenario F: The self-bootstrapping agent](#7-scenario-f-the-self-bootstrapping-agent)
   An agent that reads its own role definition from a cairn workspace
   file and constructs its own richer TurnSchema. The core pattern.

---

## 1. The Evaluation Model

Before looking at any examples, it helps to understand what the runtime
does with a `TurnSchema`. The evaluation model is simple and sequential.

### Step 1 — Resolve the system prompt

The runtime walks the `system` PromptNode tree and resolves it to a string.
`str` nodes are used as-is. `ToolRef` nodes call the named grail tool via
the cairn workspace and substitute the output. `Concat` nodes join their
resolved parts. `InputGate` nodes block until the user responds.

```
system PromptNode
    └─ Concat
        ├─ "You are responsible for: "      →  "You are responsible for: "
        └─ ToolRef("read_role", {...})       →  "reviewing docstrings"
                                             ─────────────────────────────
                                             "You are responsible for: reviewing docstrings"
```

### Step 2 — Run the ContextPipeline

Steps execute in order. Each step resolves its `content` PromptNode to
a string and stores it under `"$step_name"`. That value is then available
in any subsequent step's `ToolRef` args via string interpolation.

```
Step "source" → ToolRef("read_file", {"path": "$node.file_path"})
     output: "def add(a, b):\n    return a + b"
     stored as: $source

Step "history" → ToolRef("read_events", {"node": "$node.id", "limit": "5"})
     receives: node.id resolved from runtime env
     output: "2025-03-07: agent reviewed, approved"
     stored as: $history

Step "related" → ToolRef("find_related", {"context": "$history"})
     receives: $history = "2025-03-07: agent reviewed, approved"
     output: "test_add, add_integers, subtract"
     stored as: $related
```

All non-empty step outputs are joined with newlines and appended to the
user-visible message. The LLM sees the resolved system prompt and the
assembled context — it does not see the ToolRef calls that produced it.

### Step 3 — Run the LLM loop

The LLM is given the resolved messages and the declared `tools` (grail
tool names). It calls tools, gets results, and iterates up to `max_turns`
times. When it outputs the `termination` string, the loop ends.

The tools in `TurnSchema.tools` are the **interactive** tools — the ones
the LLM invokes itself during the turn. They are different from the
ToolRefs in the system/context, which are **pre-turn reads** that the
LLM never sees as tool calls.


---

## 2. Scenario A: Static Schema

The simplest possible schema. No tool calls, no context pipeline. Just a
static system prompt and a tool the LLM can call during its turn.

This is equivalent to the current `bundle.yaml` with `system_prompt: "..."` and
`agents_dir: ./agents`. The difference is it's a Python object, not a config file.

```python
from remora_bootstrap.primitives import TurnSchema, ContextPipeline

schema = TurnSchema(
    system="You are a docstring reviewer. Read the code and suggest improvements.",
    context=ContextPipeline.empty(),
    tools=("suggest_docstring",),
    max_turns=3,
    termination="done",
)
```

**What the LLM sees:**

```
[system]
You are a docstring reviewer. Read the code and suggest improvements.

[user]
(empty — no context pipeline steps resolved)
```

**When to use it:** Agents whose context comes entirely from the triggering
event payload (e.g., a `HumanChatEvent` that already contains the relevant
text). No pre-turn reads needed.

---

## 3. Scenario B: Reading Context with ToolRef

Now the agent reads its own source file before the LLM turn starts.
The LLM receives the file content as part of its context, without having
to call a tool to get it.

```python
from remora_bootstrap.primitives import (
    TurnSchema, ContextPipeline, Step, ToolRef
)

schema = TurnSchema(
    system="You are a docstring reviewer. Analyze the code below and suggest improvements.",
    context=ContextPipeline(steps=(
        Step(
            name="source",
            content=ToolRef(
                tool="read_file",
                args={"path": "$node.file_path"},
            ),
        ),
    )),
    tools=("suggest_docstring", "message_node"),
    max_turns=3,
    termination="done",
)
```

The runtime calls `read_file` with the node's file path (injected by the
runtime from the `AgentNode` being executed), gets back the file content
as a string, and includes it in the user message.

**What the LLM sees:**

```
[system]
You are a docstring reviewer. Analyze the code below and suggest improvements.

[user]
def add(a, b):
    """Add two numbers."""
    return a + b

class Calculator:
    def multiply(self, a, b):
        return a * b
```

**Key point:** `$node.file_path` is a runtime variable, not a pipeline
step reference. The runtime resolves a small set of variables from the
current `AgentNode` before the pipeline runs:

| Variable | Value |
|----------|-------|
| `$node.id` | the node's stable identifier |
| `$node.file_path` | path to the source file |
| `$node.name` | the node's short name |
| `$node.full_name` | qualified name (e.g., `module.ClassName.method`) |
| `$node.type` | node type string (e.g., `function`, `class`) |

These are always available. `$step_name` references (described next) are
available only after the named step has resolved.

---

## 4. Scenario C: Chaining Steps

Steps run in order. Each step's output is stored under `"$step_name"` and
is available in all subsequent `ToolRef` args. This is how "nested function
chains that build up context" works in practice.

Scenario: a reviewer agent that reads the source, reads the test file for
that module, and then asks a tool what's missing between the two.

```python
from remora_bootstrap.primitives import (
    TurnSchema, ContextPipeline, Step, ToolRef, Concat
)

schema = TurnSchema(
    system="You are a test coverage reviewer. Identify untested behaviors.",
    context=ContextPipeline(steps=(
        # Step 1: read the implementation file
        Step(
            name="impl",
            content=ToolRef(
                tool="read_file",
                args={"path": "$node.file_path"},
            ),
        ),
        # Step 2: find and read the corresponding test file.
        # $node.name is available from the runtime.
        Step(
            name="test_path",
            content=ToolRef(
                tool="find_test_file",
                args={"module_name": "$node.name"},
                extract="path",  # pull the "path" field out of the JSON response
            ),
        ),
        # Step 3: read the test file. $test_path from step 2 is now available.
        Step(
            name="tests",
            content=ToolRef(
                tool="read_file",
                args={"path": "$test_path"},
            ),
        ),
        # Step 4: ask a tool to diff what the impl exposes vs what tests cover.
        # Both $impl and $tests are now available.
        Step(
            name="gap_analysis",
            content=ToolRef(
                tool="coverage_gap_analysis",
                args={
                    "impl_source": "$impl",
                    "test_source": "$tests",
                },
                extract="summary",
            ),
        ),
    )),
    tools=("propose_test", "message_node"),
    max_turns=4,
    termination="done",
)
```

**What the LLM sees (assembled user message):**

```
[user]
def add(a, b):
    return a + b

class Calculator:
    ...

(test file content)

Gap analysis: add() has no edge-case tests (negative numbers, floats).
Calculator.multiply() is not tested at all.
```

The LLM gets a rich, fully assembled context. It didn't call any tools to
get it — those were all pre-turn reads. The LLM's own tools (`propose_test`,
`message_node`) are for acting on what it sees.

**The `extract` field:** When a grail tool returns a JSON object, `extract`
lets you pull out a specific field by dot-path before the value is used as
content. In step 2, `find_test_file` returns `{"path": "tests/test_calc.py",
"exists": true}` — `extract="path"` gives us just `"tests/test_calc.py"`.
In step 4, `extract="summary"` pulls the summary string out of the analysis
result rather than dumping the whole JSON blob into the prompt.

---

## 5. Scenario D: Composing the System Prompt with Concat

The system prompt doesn't have to be static. `Concat` can build a system
prompt from multiple pieces, including tool call outputs.

Scenario: an agent whose role description lives in a cairn workspace file
(so it can be edited by the agent itself or by another agent without
touching Python code).

```python
from remora_bootstrap.primitives import (
    TurnSchema, ContextPipeline, Step, ToolRef, Concat
)

schema = TurnSchema(
    system=Concat(
        parts=(
            # Static header
            "You are a Remora agent node.\n\n",

            # Dynamic: read the role file from the cairn workspace
            "Your responsibilities:\n",
            ToolRef(
                tool="read_workspace_file",
                args={"path": "role.md"},
            ),

            # Dynamic: read any current constraints
            "\n\nActive constraints:\n",
            ToolRef(
                tool="read_workspace_file",
                args={"path": "constraints.md"},
                # If constraints.md doesn't exist, the tool returns "".
                # An empty part is skipped by Concat, so the
                # "Active constraints:" header is also skipped... except
                # it won't be, because it's a separate static str part.
                # See below for how to handle conditional headers.
            ),
        ),
        separator="",
    ),
    context=ContextPipeline(steps=(
        Step("source", ToolRef("read_file", {"path": "$node.file_path"})),
    )),
    tools=("rewrite_self", "message_node"),
    max_turns=5,
    termination="done",
)
```

**Conditional headers with Concat:** The `Concat` type skips empty parts.
But if you have `("## Constraints\n", ToolRef(...))` and the ToolRef
returns `""`, the header is still emitted. To handle this cleanly, wrap
the header and body together in a nested `Concat`:

```python
Concat(
    parts=(
        "You are a Remora agent node.\n\n",
        "Your responsibilities:\n",
        ToolRef("read_workspace_file", {"path": "role.md"}),

        # This entire inner Concat resolves to "" if constraints.md is empty,
        # so neither the header nor the body appears.
        Concat(
            parts=(
                "\n\nActive constraints:\n",
                ToolRef("read_workspace_file", {"path": "constraints.md"}),
            ),
            separator="",
        ),
    ),
    separator="",
)
```

Wait — that still doesn't work. `Concat` skips parts that resolve to `""`,
but `"\n\nActive constraints:\n"` is not empty — it always emits. The
correct pattern: treat the header as part of the tool output by having
the tool return the formatted section (including header) or `""`. The tool
handles the conditional logic; the schema just receives its output.

```python
# Better: let the tool decide whether to include the section at all
ToolRef(
    tool="read_workspace_section",
    args={"path": "constraints.md", "header": "Active constraints"},
    # Tool returns "## Active constraints\n...\n" or "" if file is empty/missing
),
```

This is the right division of labor: **tool handles logic, schema handles
structure**.

---

## 6. Scenario E: Collecting User Input with InputGate

`InputGate` pauses the context pipeline and asks the user a question.
The response becomes a named step output, available to subsequent steps.

Scenario: a planning agent that asks the user what they want to accomplish
before reading any files, then uses that objective to decide what context
to load.

```python
from remora_bootstrap.primitives import (
    TurnSchema, ContextPipeline, Step, ToolRef, InputGate, Concat
)

schema = TurnSchema(
    system="You are a planning assistant. Help the user break down their objective.",
    context=ContextPipeline(steps=(
        # Pause and ask the user before loading any context
        Step(
            name="objective",
            content=InputGate(
                name="user_objective",
                prompt="What would you like to accomplish?",
                default="",  # used in non-interactive (batch) mode
            ),
        ),

        # Use the objective to fetch relevant files
        # $objective is now the user's response string
        Step(
            name="relevant_files",
            content=ToolRef(
                tool="find_relevant_files",
                args={"query": "$objective"},
                extract="summary",
            ),
        ),

        # Read the project's current constraints for context
        Step(
            name="constraints",
            content=ToolRef(
                tool="read_workspace_file",
                args={"path": "CONSTRAINTS.md"},
            ),
        ),
    )),
    tools=("create_plan", "message_node", "request_clarification"),
    max_turns=3,
    termination="done",
)
```

**What the runtime does:**

```
Runtime:  "What would you like to accomplish?"
User:     "Refactor the event store to support multiple backends"

$objective = "Refactor the event store to support multiple backends"

Runtime calls find_relevant_files(query="Refactor the event store...")
  → "src/remora/core/store/event_store.py, tests/unit/test_event_store.py"
$relevant_files = "src/remora/core/store/event_store.py, tests/..."

Runtime calls read_workspace_file(path="CONSTRAINTS.md")
  → "- Must not break existing API surface\n- SQLite is the default backend"
$constraints = "- Must not break existing API surface\n..."
```

The LLM then receives all of this assembled — including the user's stated
objective — and can immediately produce a meaningful plan.

**The `InputGate.prompt` is itself a `PromptNode`:** This means the prompt
shown to the user can also be dynamic. For example, showing the user the
current state of something before asking:

```python
InputGate(
    name="review_decision",
    prompt=Concat(
        parts=(
            "The proposed change is:\n\n",
            ToolRef("read_workspace_file", {"path": "proposal.md"}),
            "\n\nApprove, reject, or request changes?",
        ),
        separator="",
    ),
    default="approve",
)
```

---

## 7. Scenario F: The Self-Bootstrapping Agent

This is the core pattern the whole design is built around.

An agent node starts with a **minimal default schema** provided by the
runtime. Its first act is to read its own role definition and any
accumulated workspace state, then **return a richer schema** that the
runtime uses for subsequent turns.

The agent bootstraps its own context without any hardcoded Python changes.

### The minimal default schema

The runtime starts every agent node with something like this:

```python
# runtime.py — the schema every agent gets on its very first activation
DEFAULT_SCHEMA = TurnSchema(
    system="You are a Remora agent node. Read your workspace to understand your role.",
    context=ContextPipeline(steps=(
        Step(
            name="role",
            content=ToolRef(
                tool="read_workspace_file",
                args={"path": "role.md"},
            ),
        ),
    )),
    tools=("read_workspace_file", "write_workspace_file", "emit_schema"),
    max_turns=2,
    termination="done",
)
```

The `emit_schema` tool is the key: it takes a structured schema definition
as its argument and tells the runtime "use this schema from now on." The
agent calls `emit_schema` once and then terminates (`"done"`).

### What the agent does on first activation

```
[system]
You are a Remora agent node. Read your workspace to understand your role.

[user]
(role.md content, if it exists, otherwise empty)
```

If `role.md` is empty or missing, the agent is truly new. It might call
`write_workspace_file` to create its own role definition based on its
name, node type, and the trigger event that caused it to activate.

Once it has a role, it calls `emit_schema` with a fully specified schema:

```python
# This is the schema the agent builds and emits via the emit_schema tool.
# It's represented here as Python for clarity, but the agent produces it
# as a structured tool call argument (JSON).

agent_built_schema = TurnSchema(
    system=Concat(
        parts=(
            "You are responsible for: ",
            ToolRef("read_workspace_file", {"path": "role.md"}),
            "\n\nOperating constraints:\n",
            ToolRef("read_workspace_file", {"path": "constraints.md"}),
        ),
        separator="",
    ),
    context=ContextPipeline(steps=(
        Step("source",   ToolRef("read_file",        {"path": "$node.file_path"})),
        Step("history",  ToolRef("read_recent_events", {"node": "$node.id", "limit": "10"})),
        Step("siblings", ToolRef("list_sibling_nodes", {"node": "$node.id"})),
    )),
    tools=("rewrite_self", "message_node", "subscribe", "request_review"),
    max_turns=6,
    termination="done",
)
```

On every subsequent activation, the runtime uses this schema — not the
default. The agent does not need to re-bootstrap.

### Evolving the schema over time

The agent can update its own schema at any point by calling `emit_schema`
again. This might happen when:

- The agent discovers a new type of event it needs to handle
- The agent's role changes (another agent rewrites its `role.md`)
- The agent has accumulated enough history to want a different context window

The schema itself is just data sitting in the cairn workspace. Another
agent can propose a change to it, a reviewer can approve, and the
change takes effect on the next activation — no deployment, no config
file edits, no Python changes.

### The full bootstrap sequence

```
1.  NodeDiscoveredEvent fires (new function found in source tree)
2.  Runtime creates an AgentNode for it
3.  Runtime activates it with DEFAULT_SCHEMA
4.  Agent reads role.md → empty (new node, no role yet)
5.  Agent calls write_workspace_file("role.md", "Review docstrings for $node.full_name")
6.  Agent calls emit_schema({
        system: Concat([...role.md...]),
        context: [...read source, read history...],
        tools: ["suggest_docstring", "message_node"],
        max_turns: 3,
        termination: "done"
    })
7.  Agent outputs "done"
8.  Runtime stores the emitted schema in the cairn workspace
9.  FileSavedEvent fires (the source file is modified)
10. Runtime activates the same agent with the STORED schema (not default)
11. Agent reads its own source, reads history, reasons, calls suggest_docstring
12. Agent outputs "done"
```

Steps 1–8 happen once. Steps 9–12 happen every time the file is saved.
The agent built itself from scratch using nothing but its workspace and
two grail tools.

---

### What this means in practice

The primitives do not define *what* agents do — they define *the shape of
the container* agents work within. Everything domain-specific lives in:

- **grail `.pym` tools**: the operations agents can invoke (`read_file`,
  `suggest_docstring`, `emit_schema`, ...)
- **cairn workspace files**: the agent's own state (`role.md`,
  `constraints.md`, `schema.json`, ...)
- **the schema the agent emits**: the agent's own description of how it
  wants to be run

The primitives just wire these together into a turn the runtime can execute.

---

## Appendix: Three Paths to Emergent Capabilities

The primitives define the container. What emerges depends on what agents
do within it. Below are three distinct mechanisms — each building on the
same six types — that produce qualitatively different kinds of emergence.

---

### I. Schema Fitness Selection (single-agent, longitudinal)

**The idea:** An agent learns which parts of its own context pipeline
actually matter. Steps that consistently produce content the LLM ignores
are overhead. Steps that consistently change the LLM's output are load-
bearing. Over many activations the agent trims the former and reinforces
the latter. The schema adapts to fit the agent's real workload.

**How it works:** At the end of each turn, a `score_turn` grail tool
inspects what happened: which `$step_name` values were referenced in LLM
tool call arguments, which tool calls were skipped, and whether any
downstream agent sent a correction event. It appends a usage record to
`step_usage.jsonl` in the cairn workspace. Periodically — say, every ten
activations — the agent reads its accumulated usage data and calls
`emit_schema` with a revised pipeline that demotes or removes consistently
unused steps.

```python
# The schema the agent uses after it has been running for a while.
# The context pipeline is now generated by a tool rather than hardcoded.

schema = TurnSchema(
    system=Concat(
        parts=(
            "You are responsible for: ",
            ToolRef("read_workspace_file", {"path": "role.md"}),
        ),
        separator="",
    ),
    context=ContextPipeline(steps=(

        # Step 1: read accumulated usage data from past turns
        Step(
            name="usage",
            content=ToolRef(
                tool="read_workspace_file",
                args={"path": "step_usage.jsonl"},
            ),
        ),

        # Step 2: ask a tool to compute which steps are load-bearing
        # given the usage log. Returns a ranked list of step names.
        Step(
            name="fit_steps",
            content=ToolRef(
                tool="rank_steps_by_fitness",
                args={"usage_log": "$usage", "min_use_rate": "0.3"},
                extract="ranked_steps",
            ),
        ),

        # Step 3: build context using only the fit steps.
        # This tool reads fit_steps (a JSON list of step names),
        # executes each one, and returns the combined output.
        Step(
            name="context",
            content=ToolRef(
                tool="execute_fit_pipeline",
                args={
                    "steps": "$fit_steps",
                    "node_id": "$node.id",
                    "file_path": "$node.file_path",
                },
            ),
        ),

    )),
    tools=("rewrite_self", "message_node", "score_turn", "emit_schema"),
    max_turns=5,
    termination="done",
)
```

**What emerges:** Two agents with the same initial schema but different
activation histories end up with different context pipelines — not because
someone configured them differently, but because their actual usage patterns
diverged. A docstring agent activated mostly on small utility functions
drops the `read_siblings` step (rarely useful). The same agent on a module
with many interdependencies keeps it. Same primitive types, different
emergent specialization.

**The key:** `step_usage.jsonl` is just a file in the cairn workspace.
The agent writes it, reads it, and reasons about it. No external system
tracks fitness — the agent is its own evolutionary pressure.

---

### II. Schema Diffusion (multi-agent, horizontal)

**The idea:** When one agent finds a useful schema pattern, it packages
that pattern as a message and sends it to neighboring agents via
`message_node`. Recipients can inspect the fragment, try it, and if it
helps them too, forward it further. Useful patterns propagate across the
graph without anyone designing the propagation path.

**How it works:** An agent that has recently improved its schema (via
fitness selection or manual inspection) extracts the useful fragment and
sends it as a `schema_fragment` message. Receiving agents have a
`process_incoming_fragments` step in their pipeline that checks for
pending fragments, evaluates whether the fragment is applicable to their
node type, and optionally integrates it.

```python
# Sender side: after a successful emit_schema, broadcast the fragment

# The LLM calls message_node with a structured payload:
#
#   message_node(
#       to="file:src/remora/core/",    # broadcast to all agents in this directory
#       content=json.dumps({
#           "type": "schema_fragment",
#           "fragment_id": "sibling-context-v2",
#           "description": "Read sibling nodes before responding — reduces repeated work",
#           "applicable_to": ["function", "class"],
#           "steps": [
#               {
#                   "name": "siblings",
#                   "tool": "list_sibling_nodes",
#                   "args": {"node": "$node.id"},
#               }
#           ],
#           "observed_improvement": "fewer correction events from reviewer agents",
#       })
#   )


# Receiver side: a schema that checks for incoming fragments each activation

receiver_schema = TurnSchema(
    system=Concat(
        parts=(
            "You are responsible for: ",
            ToolRef("read_workspace_file", {"path": "role.md"}),
        ),
        separator="",
    ),
    context=ContextPipeline(steps=(
        Step("source", ToolRef("read_file", {"path": "$node.file_path"})),

        # Check for pending schema_fragment messages from other agents
        Step(
            name="pending_fragments",
            content=ToolRef(
                tool="read_inbox",
                args={"node": "$node.id", "type_filter": "schema_fragment"},
                extract="fragments",
            ),
        ),

        # Ask a tool: do any of these fragments apply to my node type,
        # and have enough other agents adopted them to be worth trying?
        Step(
            name="fragment_eval",
            content=ToolRef(
                tool="evaluate_fragments",
                args={
                    "fragments": "$pending_fragments",
                    "node_type": "$node.type",
                    "adoption_threshold": "3",  # trust after 3 other adopters
                },
                extract="recommended",
            ),
        ),

        # If a fragment was recommended, it's included here as additional context.
        # The LLM can then call emit_schema to adopt it.
        Step(
            name="siblings",
            content=ToolRef("list_sibling_nodes", {"node": "$node.id"}),
        ),
    )),
    tools=("rewrite_self", "message_node", "emit_schema", "dismiss_fragment"),
    max_turns=4,
    termination="done",
)
```

**What emerges:** Schema improvements propagate organically. An agent in
`core/store/` discovers that reading the event schema before responding
reduces its error rate. It messages its siblings. Three of them try it
and keep it. They each message their neighbors. Within a few activation
cycles, a useful context pattern has spread to every agent in the module
— without any central coordination, without any config change, without
anyone programming the propagation.

**The key distinction from Approach I:** fitness selection improves a
single agent based on its own history. Diffusion improves agents based on
each other's history. One is introspective; the other is social. Both use
the same primitives — `message_node` in the tool set, `read_inbox` in the
context pipeline.

---

### III. Tool Synthesis (capability extension)

**The idea:** An agent can write a new grail `.pym` tool to its cairn
workspace by calling `write_workspace_file`. That new tool is a composition
of lower-level operations — it might read a file, parse it, and return a
structured summary that the agent needs frequently. The agent then emits a
schema that references the new tool. The tool didn't exist in the bootstrap
set; the agent invented it.

**How it works:** The agent identifies a recurring multi-step operation in
its context pipeline — three steps that always run in sequence and whose
intermediate outputs are never useful on their own. It writes a single
`.pym` script that encapsulates all three, gives it a descriptive name,
and rewrites its schema to call the new tool instead of the three steps.

```python
# The agent's current verbose pipeline (before synthesis):

verbose_schema = TurnSchema(
    system="...",
    context=ContextPipeline(steps=(
        Step("raw_source",    ToolRef("read_file",      {"path": "$node.file_path"})),
        Step("ast_summary",   ToolRef("parse_ast",      {"source": "$raw_source", "depth": "2"})),
        Step("public_api",    ToolRef("extract_public",  {"ast": "$ast_summary"}, extract="api")),
        # $raw_source and $ast_summary are never used directly in LLM tool calls.
        # Only $public_api matters. The first two steps are scaffolding noise.
    )),
    tools=("suggest_docstring",),
    max_turns=3,
    termination="done",
)


# The agent writes a new tool to its workspace.
# The LLM produces this content and calls write_workspace_file with it.
#
# File: agents/read_public_api.pym
# (Grail pym format — simplified for illustration)
#
#   name: read_public_api
#   description: Read a source file and return its public API surface
#   params:
#     file_path: str
#
#   source = read_file(file_path)
#   ast    = parse_ast(source, depth=2)
#   return extract_public(ast).api


# After writing the tool, the agent emits a cleaner schema:

synthesized_schema = TurnSchema(
    system="...",
    context=ContextPipeline(steps=(
        # Three steps collapsed into one.
        # The new tool lives in the agent's own cairn workspace.
        Step(
            name="public_api",
            content=ToolRef(
                tool="read_public_api",           # the agent's own new tool
                args={"file_path": "$node.file_path"},
            ),
        ),
    )),
    tools=("suggest_docstring",),
    max_turns=3,
    termination="done",
)
```

**What emerges:** The tool ecosystem grows from the bottom up. Agents that
work on similar problems independently invent similar composite tools —
and via Approach II's diffusion mechanism, can share those tools with
neighbors. A tool that one agent writes to solve its own friction becomes
a reusable primitive for other agents who receive it as a fragment.

Over time, the bootstrap tool set (a handful of low-level grail tools)
gives rise to a layered library of domain-specific tools — each one
invented by an agent to reduce its own overhead, without anyone designing
the library.

**The key constraint:** Tool synthesis only works if agents have
`write_workspace_file` in their `tools` set. This is a privileged
capability — not every agent should have it. The runtime gives it to
agents that have demonstrated stable behavior (e.g., low correction rate
over N activations). This creates a natural tiering: new agents are
consumers of the existing tool set; mature, trusted agents are contributors
to it.

---

### Comparing the three

| | Schema Fitness | Schema Diffusion | Tool Synthesis |
|---|---|---|---|
| **Scope** | Single agent | Multi-agent graph | Single agent |
| **Input** | Agent's own history | Other agents' schemas | Agent's own friction |
| **Output** | Slimmer, tuned pipeline | Propagated pattern | New grail tool |
| **Timescale** | Many activations | Cross-agent cascade | Single activation |
| **Gating** | Always available | Requires `message_node` | Requires `write_workspace_file` |
| **Risk** | Over-pruning useful steps | Fragment spam, bad fragments | Buggy tools proliferating |

All three can run simultaneously on the same graph. They don't conflict —
they interact. An agent that synthesizes a new tool (III) then broadcasts
a schema fragment referencing it (II), and other agents that adopt the
fragment begin accumulating fitness data on it (I). The cycle runs without
any central orchestrator, because the primitives already carry everything
needed: tool calls in context pipelines, message_node in the tool set, and
workspace files as shared persistent state.

---

## Appendix II: Three Concrete Capabilities

Where the first appendix described emergent *mechanisms*, this one shows
emergent *products* — specific useful things the system can do that would
otherwise require bespoke tooling or manual effort.

---

### 1. Docstring Drift Detection

**The problem:** Naive reactive agents rewrite the docstring every time a
file is saved, even for trivial changes (whitespace, a renamed variable).
This creates noise, wastes LLM turns, and trains the developer to ignore
agent output. What you actually want is: only act when the code's *meaning*
has drifted from what the docstring describes.

**The capability:** A docstring agent that reads both the current docstring
and the current implementation, asks a tool to score semantic alignment,
and only proceeds if the alignment score falls below a threshold. Otherwise
it exits silently. No noise, no wasted turns.

```python
schema = TurnSchema(
    system=Concat(
        parts=(
            "You maintain docstrings for: ",
            ToolRef("read_workspace_file", {"path": "role.md"}),
            "\n\nOnly rewrite if the existing docstring is meaningfully out of date.",
        ),
        separator="",
    ),
    context=ContextPipeline(steps=(

        # Read current implementation
        Step(
            name="code",
            content=ToolRef("read_file", {"path": "$node.file_path"}),
        ),

        # Extract just this node's source (not the whole file)
        Step(
            name="node_source",
            content=ToolRef(
                tool="extract_node_source",
                args={"source": "$code", "node": "$node.full_name"},
            ),
        ),

        # Read the existing docstring separately (structured extraction)
        Step(
            name="current_doc",
            content=ToolRef(
                tool="extract_docstring",
                args={"source": "$node_source"},
            ),
        ),

        # Score semantic alignment: 0.0 (completely wrong) to 1.0 (accurate)
        # Returns "" if score >= threshold, "DRIFT DETECTED: <reason>" if not.
        # Concat skips empty parts, so if score is fine the LLM sees nothing
        # under this step and knows to exit immediately.
        Step(
            name="drift_signal",
            content=ToolRef(
                tool="score_docstring_alignment",
                args={
                    "docstring": "$current_doc",
                    "implementation": "$node_source",
                    "threshold": "0.75",
                },
                extract="signal",   # "" or "DRIFT DETECTED: ..."
            ),
        ),

    )),
    tools=("rewrite_docstring", "message_node"),
    max_turns=2,
    termination="done",
)
```

**What the LLM sees when there is no drift:**

```
[system]
You maintain docstrings for: src/remora/core/store/event_store.py :: append()
Only rewrite if the existing docstring is meaningfully out of date.

[user]
def append(self, graph_id: str, event: _FrozenEvent) -> None:
    ...

"""Append a frozen event to the store for the given graph."""

(drift_signal is empty — skipped by Concat)
```

The LLM reads the empty context, outputs `done`, and nothing is written.
Zero noise. One short LLM call.

**What the LLM sees when drift is detected:**

```
[user]
def append(self, graph_id: str, event: _FrozenEvent, *, flush: bool = True) -> None:
    ...

"""Append a frozen event to the store for the given graph."""

DRIFT DETECTED: docstring does not mention the flush parameter added in last commit
```

Now the LLM has a specific, actionable signal. It calls `rewrite_docstring`
with a targeted update, not a full rewrite.

**The step that makes it work:** `score_docstring_alignment` returns `""` or
a human-readable reason. Because `Concat` skips empty parts, the LLM's
effective context is either rich (drift) or minimal (no drift). The schema
doesn't branch — the tool does the branching by controlling what it emits.

---

### 2. Signature Change Propagation

**The problem:** A function's signature changes — a parameter is added,
renamed, or its type changes. Every caller in the codebase is now
potentially broken, but finding them all, assessing each one, and proposing
fixes is tedious. It's the kind of thing that slips through until CI fails.

**The capability:** When a function node's source changes in a way that
affects its public signature, the agent automatically finds all callers,
reads each caller's context, assesses compatibility, and either fixes
compatible callers directly or sends a structured impact message to the
relevant agent nodes for them to handle.

This is two schemas working together: the **signature watcher** on the
changed function, and the **call site handler** on each caller.

```python
# Schema for the function that changed — the signature watcher

watcher_schema = TurnSchema(
    system="You detect and propagate signature changes for the function you own.",
    context=ContextPipeline(steps=(

        # What does the current signature look like?
        Step(
            name="current_sig",
            content=ToolRef(
                tool="extract_signature",
                args={"source": "$node.file_path", "node": "$node.full_name"},
            ),
        ),

        # What did it look like before this save? (stored in workspace)
        Step(
            name="previous_sig",
            content=ToolRef(
                tool="read_workspace_file",
                args={"path": "last_known_signature.txt"},
            ),
        ),

        # Diff the signatures. Returns "" if unchanged, or a structured
        # change description: {"added": [...], "removed": [...], "renamed": {...}}
        Step(
            name="sig_diff",
            content=ToolRef(
                tool="diff_signatures",
                args={"before": "$previous_sig", "after": "$current_sig"},
                extract="diff",
            ),
        ),

        # Find all call sites across the project (only runs if diff is non-empty,
        # because if sig_diff is "" this step's output is also "" via the tool)
        Step(
            name="callers",
            content=ToolRef(
                tool="find_callers",
                args={"function": "$node.full_name", "only_if": "$sig_diff"},
                extract="caller_nodes",
            ),
        ),

    )),
    tools=("message_node", "write_workspace_file"),
    max_turns=3,
    termination="done",
)
```

The watcher LLM receives the diff and the caller list. It calls
`write_workspace_file("last_known_signature.txt", current_sig)` to update
the baseline, then calls `message_node` once per caller with a structured
payload describing exactly what changed and what the caller needs to update.

```python
# Schema for each call site — the call site handler
# Activated when it receives a signature_change message

callsite_schema = TurnSchema(
    system=Concat(
        parts=(
            "You maintain call sites that use external functions. ",
            "When a function you call changes its signature, update your code.",
        ),
        separator="",
    ),
    context=ContextPipeline(steps=(

        # Read the incoming message (the structured change description)
        Step(
            name="change_notice",
            content=ToolRef(
                tool="read_inbox",
                args={"node": "$node.id", "type_filter": "signature_change"},
                extract="latest",
            ),
        ),

        # Read the call site's current source
        Step(
            name="source",
            content=ToolRef("read_file", {"path": "$node.file_path"}),
        ),

        # Find the specific call expression in this file
        Step(
            name="call_expr",
            content=ToolRef(
                tool="find_call_expression",
                args={
                    "source": "$source",
                    "function": "$change_notice.function",
                },
                extract="expression",
            ),
        ),

    )),
    tools=("rewrite_self", "message_node"),
    max_turns=2,
    termination="done",
)
```

**What emerges:** One function change triggers a cascade. Each caller
handles its own update autonomously. No developer has to run a project-wide
find-and-replace. No CI failure surfaces the issue three commits later.
The propagation is fast because it runs in parallel — each caller agent
activates independently when it receives the message.

---

### 3. Persistent Pair Programmer

**The problem:** LLM assistants are stateless. Every conversation starts
cold. You have to re-explain what you're working on, what you tried, what
went wrong. The LLM gives generic advice because it has no accumulated
understanding of your specific codebase, your current task, or the last
two hours of context.

**The capability:** An agent that maintains a running session model across
multiple file saves. As you work, it observes what you change and
accumulates a structured understanding of your task in its cairn workspace.
When you invoke it interactively, it already knows your context. It asks
clarifying questions grounded in what it has observed, not generic ones.

```python
# The background observer — activates on every FileSavedEvent,
# updates the session model, never interacts with the user

observer_schema = TurnSchema(
    system="You maintain a running model of the developer's current task.",
    context=ContextPipeline(steps=(

        # What did the developer just change?
        Step(
            name="diff",
            content=ToolRef(
                tool="get_file_diff",
                args={"path": "$node.file_path"},
                extract="unified_diff",
            ),
        ),

        # What does the current session model say?
        Step(
            name="session",
            content=ToolRef(
                tool="read_workspace_file",
                args={"path": "session_model.md"},
            ),
        ),

        # What was the last stated intent (if any)?
        Step(
            name="last_intent",
            content=ToolRef(
                tool="read_workspace_file",
                args={"path": "current_intent.md"},
            ),
        ),

    )),
    # The LLM updates session_model.md based on the diff.
    # It writes a concise running narrative: what the developer seems
    # to be doing, what changed, what might be next.
    tools=("write_workspace_file",),
    max_turns=1,
    termination="done",
)


# The interactive pair — activated on demand (HumanChatEvent or ManualTriggerEvent)
# This is the schema the developer actually talks to

pair_schema = TurnSchema(
    system=Concat(
        parts=(
            "You are a pair programmer with full context on what the developer ",
            "has been working on. Do not ask them to re-explain their task — ",
            "you already know it from the session model.",
        ),
        separator="",
    ),
    context=ContextPipeline(steps=(

        # Load the accumulated session model
        Step(
            name="session",
            content=ToolRef(
                tool="read_workspace_file",
                args={"path": "session_model.md"},
            ),
        ),

        # Load the current file the developer is in
        Step(
            name="current_file",
            content=ToolRef("read_file", {"path": "$node.file_path"}),
        ),

        # Load recent events: what has happened in the swarm lately
        Step(
            name="recent_activity",
            content=ToolRef(
                tool="read_recent_events",
                args={"limit": "20", "filter": "AgentCompleteEvent,RewriteProposalEvent"},
                extract="summary",
            ),
        ),

        # Ask what they want — but the prompt itself includes the session model
        # so the user sees what the agent knows before they type
        Step(
            name="question",
            content=InputGate(
                name="user_question",
                prompt=Concat(
                    parts=(
                        "Session context:\n",
                        ToolRef("read_workspace_file", {"path": "session_model.md"}),
                        "\n\nWhat's on your mind?",
                    ),
                    separator="",
                ),
            ),
        ),

    )),
    tools=("rewrite_self", "message_node", "write_workspace_file", "search_codebase"),
    max_turns=6,
    termination="done",
)
```

**What the developer experiences:**

The developer has been refactoring `EventStore.append()` for the past
hour — moving the flush logic into a separate method. They've saved the
file four times. They trigger the pair and see:

```
Session context:
- Refactoring EventStore.append() — extracting flush logic into _flush_pending()
- append() signature unchanged externally; internal flow reorganized
- 3 callers messaged with no-op notice (signature unchanged)
- Last change: removed inline flush block, added call to self._flush_pending()

What's on your mind?
```

They type: "why does the test keep failing"

The pair already knows what they changed, which tests exist, and what the
recent agent activity was. It doesn't ask "which test?" or "what are you
working on?" It looks at the test file directly and reasons about it in
context.

**The session model file** is the key. It's plain text in the cairn
workspace, updated after every file save by the silent observer. The
interactive pair reads it as part of its context pipeline before the user
says a word. The InputGate prompt includes it so the user can see — and
correct — what the agent knows before the conversation starts.

**What emerges:** A pair programmer that gets smarter over the course of a
work session without any persistent infrastructure beyond a file in a
workspace directory. The observer and the pair are two separate schemas on
the same node, activated by different event types. They share state through
the workspace. Neither knows the other exists at the code level.
