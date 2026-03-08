# Bootstrap Primitives

`src/remora_bootstrap/primitives.py` — six types, nothing else.

---

## The problem these solve

The current `bundle.yaml` + `_build_prompt()` approach hardcodes the shape of context assembly in
Python. An agent gets whatever `_build_prompt` puts in the prompt: source code, trigger event,
recent chat history. It cannot change this shape. It cannot say "also give me the parent node's
source" or "show me the recent test results" without modifying `turn_context.py`.

The primitives make the shape of a turn **data-describable**. An agent can construct a `TurnSchema`
using grail tools on its cairn workspace and return it to the runtime. The runtime resolves it. No
Python changes needed.

---

## The six types

```
PromptNode = str | ToolRef | Concat | InputGate
```

**`str`** — literal text. Already resolved.

**`ToolRef`** — call a grail tool *before the LLM sees the prompt* and use the output as content.
This is how an agent reads its own source code, fetches recent history, or inspects related nodes
without making the LLM do it.

```python
ToolRef("read_file", args={"path": "$node.file_path"})
ToolRef("read_recent_events", args={"node": "$node.id", "limit": "5"}, extract="events")
```

**`Concat`** — join multiple `PromptNode`s. Parts that resolve to `""` are skipped, so conditional
inclusion works naturally: a `ToolRef` that returns `""` when a condition isn't met is omitted.

```python
Concat((
    "## Current source\n",
    ToolRef("read_file", {"path": "$node.file_path"}),
), separator="\n")
```

**`InputGate`** — pause and ask the user. Resolves to their response. Falls back to `default` in
non-interactive mode.

```python
InputGate("objective", prompt="What would you like to accomplish?", default="")
```

---

**`Step`** — one named step in the context pipeline. Its output is stored as `"$name"` and is
available in all subsequent `ToolRef` args via interpolation.

**`ContextPipeline`** — ordered tuple of `Step`s. Runs before the first LLM turn. All resolved
outputs are appended to the user message.

```python
ContextPipeline(steps=(
    Step("source", ToolRef("read_file", {"path": "$node.file_path"})),
    Step("history", ToolRef("read_events", {"node": "$node.id", "limit": "5"})),
    # $history is now available to any subsequent Step's args
    Step("related", ToolRef("find_related", {"context": "$history"})),
))
```

---

**`TurnSchema`** — the root. Combines a system `PromptNode`, a `ContextPipeline`, a list of grail
tool names the LLM can call during its turn, and loop bounds.

```python
TurnSchema(
    system=Concat((
        "You are responsible for: ",
        ToolRef("read_role", {"node": "$node.id"}),
    )),
    context=ContextPipeline(steps=(
        Step("code",    ToolRef("read_file",   {"path": "$node.file_path"})),
        Step("history", ToolRef("read_events", {"node": "$node.id"})),
    )),
    tools=("write_code", "message_node", "request_review"),
    max_turns=5,
    termination="done",
)
```

---

## What's intentionally not here

**No execution logic.** `TurnSchema` describes what to do. The runtime (existing structured-agents +
cairn) does the doing.

**No workflow protocols.** Multi-step workflows, state machines, retry policies — none of that is in
these types. An agent that needs a multi-step workflow constructs a sequence of `TurnSchema`s and
returns them. The swarm runtime sequences them.

**No memory model.** Memory is whatever a grail tool reads. An agent that wants episodic memory
implements a `read_memory` grail tool. The primitive doesn't care.

**No agent identity.** `TurnSchema` is the shape of one turn, not a description of an agent. Agent
identity, subscriptions, and capabilities remain in the registry (`BootstrapAgent`).

**No LLM config.** Model selection, grammar/decoding constraints, and token budgets are resolved by
the runtime from the existing config chain (bundle.yaml → remora.yaml → default). The schema doesn't
override these — that would recreate the config sprawl we're trying to avoid.

---

## How agents build themselves

The bootstrap goal is for agent nodes to build their own `TurnSchema` using grail tools on their
cairn workspace. The flow:

1. Agent node triggers (e.g., `FileSavedEvent`)
2. Runtime gives the agent a minimal default `TurnSchema` (system=role, context=empty, tools=bootstrap_tools)
3. Agent calls grail tools: reads its own source, reads constraints, reads related nodes
4. Agent constructs and returns a richer `TurnSchema` for its next turn
5. Runtime executes that schema

The agent bootstraps its own context. The primitives are just the container.
