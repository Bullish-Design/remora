# How to Use Qwen3 Model with structured-agents

A guide for developers integrating Qwen/Qwen3-4B-Instruct-2507-FP8 into their applications using structured-agents.

---

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Capabilities](#capabilities)
5. [Limitations](#limitations)
6. [Things to Watch Out For](#things-to-watch-out-for)
7. [Grammar Constraints](#grammar-constraints)
8. [Tool Calling](#tool-calling)
9. [Using Grail Scripts with Qwen](#using-grail-scripts-with-qwen)
   - [Pattern 1: xgrammar Structured Function Calling](#pattern-1-xgrammar-structured-function-calling)
   - [Pattern 2: Text-Only with Manual Tool Execution](#pattern-2-text-only-with-manual-tool-execution)
   - [Comparing the Two Patterns](#comparing-the-two-patterns)
   - [Hybrid Approach: Use Both](#hybrid-approach-use-both)
10. [Batched Inference with Concurrent Requests](#batched-inference-with-concurrent-requests)
11. [API Reference](#api-reference)
12. [Troubleshooting](#troubleshooting)

---

## Overview

The `QwenPlugin` in structured-agents provides first-class support for Qwen3 models, including:

- Message and tool formatting (OpenAI-compatible)
- Response parsing from both structured output and raw content
- Grammar constraint support (EBNF, structural_tag, JSON Schema)
- Raw content parsing for `<function=tool><parameter=k>v</parameter></function>` format

**Supported Models:**
- `Qwen/Qwen3-4B-Instruct-2507-FP8` (recommended)
- Other Qwen3 instruct models

---

## Installation

### Prerequisites

```bash
# Install structured-agents
pip install structured-agents

# Ensure vLLM is running with Qwen3
# See: https://qwen.readthedocs.io/en/latest/deployment/vllm.html
```

### vLLM Server Setup

```bash
vllm serve Qwen/Qwen3-4B-Instruct-2507-FP8 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_xml \
    --max-num-seqs 32 \
    --max-model-len 32768 \
    --enable-prefix-caching
```

**Important:** Use `--tool-call-parser qwen3_xml` instead of `qwen3_coder` due to a known bug (see [QwenLM/Qwen3#1700](https://github.com/QwenLM/Qwen3/issues/1700)).

---

## Quick Start

```python
import asyncio
from structured_agents import (
    AgentKernel,
    KernelConfig,
    Message,
    QwenPlugin,
)
from structured_agents.tool_sources.protocol import ToolSource

# Minimal setup
config = KernelConfig(
    base_url="http://localhost:8000/v1",
    model="Qwen/Qwen3-4B-Instruct-2507-FP8",
    temperature=0.1,
    max_tokens=512,
)

plugin = QwenPlugin()

# Create a minimal tool source (required by AgentKernel)
class NoOpToolSource(ToolSource):
    async def execute(self, tool_call, tool_schema, context): pass
    def list_tools(self): return []
    def resolve(self, name): return None
    def resolve_all(self, names): return []
    def context_providers(self): return []

kernel = AgentKernel(
    config=config,
    plugin=plugin,
    tool_source=NoOpToolSource(),
)

# Run a simple prompt
messages = [
    Message(role="user", content="What is 2 + 2?"),
]

result = await kernel.run(messages, [], max_turns=1)
print(result.final_message.content)
```

---

## Capabilities

### 1. Text Generation

The Qwen plugin produces high-quality text completions:

```python
response = await client.chat_completion(
    messages=[Message(role="user", content="Explain recursion.")],
    tools=None,
    tool_choice="none",
)
print(response.content)
```

### 2. Tool Calling (via vLLM)

Qwen3 models support function calling when served with vLLM:

```python
# With grammar constraints
from structured_agents.grammar.config import GrammarConfig

grammar_config = GrammarConfig(
    mode="ebnf",  # or "structural_tag", "json_schema"
    allow_parallel_calls=False,
)

# Note: structural_tag mode has known issues with some vLLM versions
# See Limitations section below
```

### 3. Raw Content Parsing

The plugin can parse tool calls from raw model output:

```python
# Model outputs: <function=tool_name><parameter=key>value</parameter></function>
content, tool_calls = plugin.parse_response(raw_content, None)
```

### 4. Concurrent Requests

Qwen3 works well with batched inference:

```python
tasks = [summarize_file(client, plugin, f) for f in files]
results = await asyncio.gather(*tasks)
```

---

## Limitations

### 1. structural_tag Grammar Mode

**Status: Limited Support**

The `structural_tag` grammar mode may cause issues with certain vLLM versions:
- Empty responses
- Validation errors

**Workaround:** Use EBNF mode instead:

```python
grammar_config = GrammarConfig(
    mode="ebnf",  # Recommended over "structural_tag"
    allow_parallel_calls=False,
)
```

### 2. JSON Schema Mode

**Status: Incompatible**

JSON Schema grammar mode (`mode="json_schema"`) is not compatible with the current vLLM version:

```
ValueError: You must use one kind of structured outputs constraint but none are specified
```

**Workaround:** Use EBNF mode.

### 3. vLLM Tool Parser Bugs

The `qwen3_coder` parser has a bug causing endless generation with structured output.

**Solution:** Use `--tool-call-parser qwen3_xml` when starting vLLM.

### 4. Model Size

The 4B parameter model may not have optimal tool-calling accuracy compared to larger models. Consider:
- More complex prompts with few-shot examples
- Grammar constraints to guide output format

---

## Things to Watch Out For

### 1. Empty Responses with structural_tag

If you get empty responses, switch to EBNF:

```python
# Instead of:
grammar_config = GrammarConfig(mode="structural_tag")

# Use:
grammar_config = GrammarConfig(mode="ebnf")
```

### 2. Grammar Payload Serialization

The `StructuralTagGrammar.to_vllm_payload()` must serialize the structural tag as a JSON string:

```python
# This is handled automatically by structured-agents
# but if you're manually constructing payloads:
payload = {
    "structured_outputs": {
        "type": "structural_tag",
        "structural_tag": json.dumps(tag_dict),  # Must be JSON string!
    }
}
```

### 3. Tool Call Arguments Not Parsed

When using EBNF grammar, the model may output:

```
<function=tool><parameter=code>def foo(): pass</parameter></function>
```

But vLLM's `tool_calls_raw` may come back empty or with empty `arguments`. The plugin's `QwenResponseParser` handles this by also parsing raw content.

### 4. Temperature Settings

For reproducible tool calling, use lower temperature:

```python
config = KernelConfig(
    temperature=0.1,  # Lower for consistent tool calling
    max_tokens=512,
)
```

### 5. Context Length

The default `max_model_len` of 32768 tokens should be sufficient for most use cases. Adjust if your prompts are larger.

---

## Grammar Constraints

### EBNF Mode (Recommended)

```python
from structured_agents.grammar.config import GrammarConfig

grammar_config = GrammarConfig(
    mode="ebnf",
    allow_parallel_calls=False,  # or True for parallel tool calls
)

grammar = plugin.build_grammar(tools, grammar_config)
extra_body = plugin.to_extra_body(grammar)

response = await client.chat_completion(
    messages=formatted_messages,
    tools=formatted_tools,
    extra_body=extra_body,
)
```

**Generated grammar format:**
```
root ::= tool_call

tool_call ::= "<function=" tool_name ">" parameters "</function>"

tool_name ::= "tool_a" | "tool_b"

parameters ::= (parameter)*
parameter ::= "<parameter=" param_name ">" param_value "</parameter>"
param_name ::= [a-zA-Z_][a-zA-Z0-9_]*
param_value ::= [^<]+
```

### structural_tag Mode (Limited)

Works with some vLLM versions but may cause issues. Test thoroughly.

### json_schema Mode (Not Supported)

Do not use. Will result in validation errors.

---

## Tool Calling

### Full Tool Calling Example

```python
import asyncio
from pathlib import Path
from structured_agents import (
    AgentKernel,
    KernelConfig,
    Message,
    QwenPlugin,
    GrailBackend,
    GrailBackendConfig,
)
from structured_agents.grammar.config import GrammarConfig
from structured_agents.registries.grail import GrailRegistry, GrailRegistryConfig
from structured_agents.tool_sources import RegistryBackendToolSource

async def main():
    # Setup
    config = KernelConfig(
        base_url="http://localhost:8000/v1",
        model="Qwen/Qwen3-4B-Instruct-2507-FP8",
        temperature=0.1,
        max_tokens=512,
        tool_choice="auto",
    )

    # Load tools from Grail .pym scripts
    registry = GrailRegistry(
        GrailRegistryConfig(agents_dir=Path("agents"))
    )
    backend = GrailBackend(
        GrailBackendConfig(grail_dir=Path("agents"))
    )
    tool_source = RegistryBackendToolSource(registry, backend)

    # Setup plugin with EBNF grammar
    plugin = QwenPlugin()
    grammar_config = GrammarConfig(
        mode="ebnf",
        allow_parallel_calls=False,
    )

    kernel = AgentKernel(
        config=config,
        plugin=plugin,
        tool_source=tool_source,
        grammar_config=grammar_config,
    )

    # Run
    messages = [
        Message(role="user", content="Read file /tmp/test.txt"),
    ]
    
    result = await kernel.run(
        messages,
        registry.list_tools(),
        max_turns=5,
    )

    print(result.final_message.content)
    await kernel.close()

asyncio.run(main())
```

### Response Parsing

The plugin handles multiple response formats:

```python
# 1. From vLLM tool_calls_raw
content, tool_calls = plugin.parse_response(response.content, response.tool_calls)

# 2. From raw content (when tool_calls_raw is empty)
content, tool_calls = plugin.parse_response(
    '<function=read_file><parameter=path>/tmp/test</parameter></function>',
    None
)
```

---

## Using Grail Scripts with Qwen

structured-agents supports two primary patterns when using Qwen with Grail `.pym` scripts:

1. **xgrammar Structured Function Calling** - Model outputs structured tool calls via grammar constraints
2. **Text-Only with Manual Tool Execution** - Model outputs text, you extract and execute tools manually

### Pattern 1: xgrammar Structured Function Calling

This pattern uses grammar constraints to force the model to output tool calls in a structured format that vLLM can parse.

#### Step 1: Create Grail .pym Scripts

```python
# agents/my_tools/read_file.pym
from grail import Input

path: str = Input("path", description="File path to read")

try:
    with open(path, "r") as f:
        content = f.read()
    result = {"path": path, "content": content[:1000]}
except Exception as exc:
    result = {"error": str(exc)}

result
```

```python
# agents/my_tools/write_file.pym
from grail import Input

path: str = Input("path", description="File path to write")
content: str = Input("content", description="Content to write")

try:
    with open(path, "w") as f:
        f.write(content)
    result = {"path": path, "written": len(content)}
except Exception as exc:
    result = {"error": str(exc)}

result
```

#### Step 2: Validate with grail check

```bash
grail check agents/my_tools/read_file.pym
grail check agents/my_tools/write_file.pym
```

This generates `.grail/<tool_name>/inputs.json` files that define the tool schemas.

#### Step 3: Run with AgentKernel

```python
from pathlib import Path
from structured_agents import (
    AgentKernel,
    KernelConfig,
    Message,
    QwenPlugin,
    GrailBackend,
    GrailBackendConfig,
)
from structured_agents.grammar.config import GrammarConfig
from structured_agents.registries.grail import GrailRegistry, GrailRegistryConfig
from structured_agents.tool_sources import RegistryBackendToolSource

# Setup
config = KernelConfig(
    base_url="http://localhost:8000/v1",
    model="Qwen/Qwen3-4B-Instruct-2507-FP8",
    temperature=0.1,
    max_tokens=512,
    tool_choice="auto",
)

# Load Grail tools
registry = GrailRegistry(
    GrailRegistryConfig(agents_dir=Path("agents/my_tools"))
)
backend = GrailBackend(
    GrailBackendConfig(grail_dir=Path("agents/my_tools"))
)
tool_source = RegistryBackendToolSource(registry, backend)

# Use EBNF grammar for structured output
plugin = QwenPlugin()
grammar_config = GrammarConfig(
    mode="ebnf",
    allow_parallel_calls=False,
)

kernel = AgentKernel(
    config=config,
    plugin=plugin,
    tool_source=tool_source,
    grammar_config=grammar_config,
)

# Run
messages = [
    Message(role="user", content="Write 'hello world' to /tmp/test.txt then read it back"),
]

result = await kernel.run(
    messages,
    registry.list_tools(),
    max_turns=5,
)
```

#### How It Works

1. **Grammar Constraint**: EBNF grammar tells the model exactly what format to output:
   ```
   <function=write_file><parameter=path>/tmp/test.txt</parameter><parameter=content>hello world</parameter></function>
   ```

2. **vLLM Parsing**: The model outputs in this format, and vLLM extracts `tool_calls_raw` 

3. **Plugin Parsing**: `QwenResponseParser.parse_response()` converts to `ToolCall` objects

4. **Tool Execution**: AgentKernel executes the tool via GrailBackend

5. **Result Handling**: Tool result is appended to conversation for next turn

### Pattern 2: Text-Only with Manual Tool Execution

This pattern skips grammar constraints entirely. The model outputs plain text, and you extract tool calls manually.

#### When to Use

- When grammar constraints cause issues (empty responses, etc.)
- When you need full control over parsing
- For simpler use cases where the model naturally outputs structured text

#### Example

```python
import asyncio
import re
from pathlib import Path
from structured_agents import (
    KernelConfig,
    Message,
    QwenPlugin,
    GrailBackend,
    GrailBackendConfig,
)
from structured_agents.registries.grail import GrailRegistry, GrailRegistryConfig
from structured_agents.tool_sources import RegistryBackendToolSource

# Pattern to match tool calls in text
TOOL_CALL_PATTERN = re.compile(
    r"<function=(\w+)><parameter=(\w+)>([^<]+)</parameter></function>"
)

async def extract_and_execute(
    content: str,
    tool_source: RegistryBackendToolSource,
    tools: list,
) -> str:
    """Extract tool calls from text and execute them."""
    matches = TOOL_CALL_PATTERN.findall(content)
    
    if not matches:
        return content  # No tool calls, return as-is
    
    results = []
    for tool_name, param_name, param_value in matches:
        tool_schema = next((t for t in tools if t.name == tool_name), None)
        if not tool_schema:
            results.append(f"Error: Unknown tool {tool_name}")
            continue
        
        tool_call = type('ToolCall', (), {
            'id': f'call_{id(content)}',
            'name': tool_name,
            'arguments': {param_name: param_value}
        })()
        
        result = await tool_source.execute(tool_call, tool_schema, {})
        results.append(str(result.output))
    
    return "\n".join(results)

async def main():
    config = KernelConfig(
        base_url="http://localhost:8000/v1",
        model="Qwen/Qwen3-4B-Instruct-2507-FP8",
        temperature=0.1,
        max_tokens=512,
        tool_choice="none",  # No grammar constraint!
    )

    registry = GrailRegistry(
        GrailRegistryConfig(agents_dir=Path("agents/my_tools"))
    )
    backend = GrailBackend(
        GrailBackendConfig(grail_dir=Path("agents/my_tools"))
    )
    tool_source = RegistryBackendToolSource(registry, backend)

    plugin = QwenPlugin()
    tools = registry.resolve_all(registry.list_tools())

    # Build messages - prompt for structured output
    messages = [
        Message(
            role="user",
            content="""Read the file /tmp/test.txt and write its contents to /tmp/output.txt.
Use this exact format for tool calls:
<function=read_file><parameter=path>/tmp/test.txt</parameter></function>
<function=write_file><parameter=path>/tmp/output.txt</parameter><parameter=content>CONTENT</parameter></function>"""
        ),
    ]

    # Get model response
    formatted = plugin.format_messages(messages, tools)
    response = await client.chat_completion(
        messages=formatted,
        tools=None,  # No tools in request
        tool_choice="none",
    )

    # Extract and execute tools from text
    tool_results = await extract_and_execute(
        response.content or "",
        tool_source,
        tools,
    )

    print("Tool results:", tool_results)

asyncio.run(main())
```

### Comparing the Two Patterns

| Aspect | Pattern 1: Grammar | Pattern 2: Text-Only |
|--------|-------------------|----------------------|
| Reliability | Higher (model forced to format) | Lower (model may deviate) |
| vLLM Integration | Uses vLLM tool parsing | Manual extraction |
| Error Handling | Automatic via tool_calls_raw | Manual regex/callback |
| Complexity | Simpler integration | More code needed |
| Grammar Issues | May cause empty responses | Avoids grammar issues |

### Hybrid Approach: Use Both

The recommended approach is to try grammar first, then fall back to text parsing:

```python
plugin = QwenPlugin()

# Try grammar-based first
grammar_config = GrammarConfig(mode="ebnf")
grammar = plugin.build_grammar(tools, grammar_config)
extra_body = plugin.to_extra_body(grammar)

response = await client.chat_completion(
    messages=formatted,
    tools=formatted_tools,
    extra_body=extra_body,
)

# Parse - handles both tool_calls_raw AND raw content fallback
content, tool_calls = plugin.parse_response(
    response.content,
    response.tool_calls
)

if not tool_calls:
    # Fallback: parse from raw text
    tool_calls = parse_from_text(content)
```

This gives you the best of both worlds - structured output when grammar works, with graceful fallback.

---

## Batched Inference with Concurrent Requests

Qwen3 works well with concurrent requests for batched inference. This is useful for:

- Processing multiple files in parallel
- Running many independent tasks
- Maximizing vLLM throughput

### Example: Batch File Summarization

```python
import asyncio
import random
from pathlib import Path

from structured_agents import KernelConfig, Message, QwenPlugin
from structured_agents.client.factory import build_client

async def summarize_file(client, plugin, file_path: Path, max_chars: int = 3000):
    """Summarize a single file."""
    content = file_path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    
    messages = [
        Message(role="user", content=f"Summarize this code in 2-3 sentences:\n\n```{content}```"),
    ]
    
    formatted = plugin.format_messages(messages, [])
    
    response = await client.chat_completion(
        messages=formatted,
        tools=None,
        tool_choice="none",
    )
    
    return file_path.name, response.content or ""

async def main():
    config = KernelConfig(
        base_url="http://localhost:8000/v1",
        model="Qwen/Qwen3-4B-Instruct-2507-FP8",
        temperature=0.1,
        max_tokens=256,
    )
    
    plugin = QwenPlugin()
    client = build_client(config)
    
    # Get random Python files
    src_dir = Path("src")
    files = random.sample(list(src_dir.rglob("*.py")), min(10, len(list(src_dir.rglob("*.py")))))
    
    # Process concurrently
    tasks = [summarize_file(client, plugin, f) for f in files]
    results = await asyncio.gather(*tasks)
    
    for name, summary in results:
        print(f"{name}: {summary[:100]}...")
    
    await client.close()

asyncio.run(main())
```

### Performance Notes

- vLLM handles batching automatically with `--max-num-seqs 32` (or higher)
- Use `asyncio.gather()` for concurrent requests
- Keep `max_tokens` reasonable to avoid long-running requests blocking the batch

---

## API Reference

### QwenPlugin

```python
from structured_agents import QwenPlugin

plugin = QwenPlugin()

# Properties
plugin.name  # "qwen"
plugin.supports_ebnf  # True
plugin.supports_structural_tags  # True
plugin.supports_json_schema  # True

# Methods
formatted_messages = plugin.format_messages(messages, tools)
formatted_tools = plugin.format_tools(tools)
grammar = plugin.build_grammar(tools, grammar_config)
extra_body = plugin.to_extra_body(grammar)
content, tool_calls = plugin.parse_response(content, tool_calls_raw)
```

### GrammarConfig

```python
from structured_agents.grammar.config import GrammarConfig

config = GrammarConfig(
    mode="ebnf",  # "ebnf", "structural_tag", "json_schema"
    allow_parallel_calls=True,
    args_format="permissive",  # "permissive", "escaped_strings", "json"
)
```

---

## Troubleshooting

### Issue: Empty response from model

**Cause:** Using `structural_tag` grammar mode with incompatible vLLM.

**Solution:** Switch to EBNF mode:
```python
grammar_config = GrammarConfig(mode="ebnf")
```

### Issue: `tool_calls_raw` is empty but model generated tool call

**Cause:** vLLM's tool parser didn't extract the tool call.

**Solution:** The plugin automatically falls back to parsing raw content:
```python
content, tool_calls = plugin.parse_response(response.content, response.tool_calls)
# If tool_calls_raw was empty, parses from content
```

### Issue: BadRequestError with structural_tag

**Cause:** vLLM expects a JSON string, not a dict.

**Solution:** This is handled by `StructuralTagGrammar.to_vllm_payload()`. Ensure you're using the latest structured-agents.

### Issue: Model not calling tools

**Cause:** Prompt may not encourage tool usage.

**Solution:** Add explicit instruction:
```python
messages = [
    Message(role="developer", content="You are a helpful assistant. Use tools when appropriate."),
    Message(role="user", content=user_input),
]
```

### Issue: Invalid arguments in tool call

**Cause:** Model may output malformed arguments.

**Solution:** The plugin's response parser handles this gracefully, returning empty dict on parse failure.

---

## Additional Resources

- [structured-agents GitHub](https://github.com/anomalyco/structured-agents)
- [Qwen Documentation](https://qwen.readthedocs.io/)
- [vLLM Tool Parsers](https://docs.vllm.ai/en/latest/api/vllm/tool_parsers/)
- [xGrammar Documentation](https://xgrammar.mlc.ai/docs/)
