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
