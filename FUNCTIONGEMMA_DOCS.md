# FunctionGemma Docs (Combined Guide)

This guide consolidates three FunctionGemma documentation pages into a single reference:

- Formatting and best practices
- Full function calling sequence
- Fine‑tuning FunctionGemma

It focuses on how FunctionGemma formats tool calls, its supported workflows, and the fine‑tuning workflow for improving tool selection.

## Overview

FunctionGemma is a Gemma‑3‑based 270M model optimized for function calling. It uses a specialized chat format and function‑calling tokens to separate natural language from tool definitions, tool calls, and tool responses.

## Base Prompt Structure

FunctionGemma uses the Gemma chat format:

- `<start_of_turn>role` … `<end_of_turn>` to delimit turns
- Roles are typically `developer`, `user`, and `model`

Function‑specific control tokens appear inside turns.

### Control Tokens

| Token Pair | Purpose |
| --- | --- |
| `<start_function_declaration>` / `<end_function_declaration>` | Define tools | 
| `<start_function_call>` / `<end_function_call>` | Model issues a tool call | 
| `<start_function_response>` / `<end_function_response>` | Provide tool results to the model |

> Note: `<start_function_response>` is an additional stop sequence for inference.

### String Delimiter

All string values inside tool data are wrapped with `<escape>`:

```
key:<escape>string value<escape>
```

This ensures special characters inside strings do not break the tool format.

## Training Scope and Limitations

FunctionGemma is trained for **single‑turn** and **parallel** tool calling.

### Supported Workflows

- **Single‑turn**: one tool call for a user request
- **Parallel**: multiple independent tool calls in a single model response

Example of parallel:

- User: “What is the weather in Tokyo and the stock price of Google?”
- Model: calls `get_weather(Tokyo)` and `get_stock_price(GOOG)` in one response

### Unsupported (Not Explicitly Trained)

- **Multi‑step chaining**: where output of Tool A becomes input for Tool B
- **Multi‑turn stateful dialogs**: where tool parameters are derived across multiple back‑and‑forth turns

The model may generalize to these cases, but it is not trained to do them reliably without fine‑tuning or external orchestration.

### Semantic Nuances

FunctionGemma can miss indirect cues (e.g., “is it cold in Paris?”). Improvements:

- **Enrich tool descriptions** with semantic keywords
- **Make user prompts explicit**
- **Fine‑tune** on domain‑specific phrasing

## Example: Weather Tool Flow (Formatted Sequence)

**Turn 1: Developer defines tools**

```
<start_of_turn>developer
You are a model that can do function calling with the following functions
<start_function_declaration>declaration:get_current_weather{description:<escape>Gets the current weather in a given location.<escape>,parameters:{properties:{location:{description:<escape>The city and state, e.g. "San Francisco, CA" or "Tokyo, JP"<escape>,type:<escape>STRING<escape>},unit:{description:<escape>The unit to return the temperature in.<escape>,enum:[<escape>celsius<escape>,<escape>fahrenheit<escape>],type:<escape>STRING<escape>}},required:[<escape>location<escape>],type:<escape>OBJECT<escape>}}<end_function_declaration><end_of_turn>
```

**Turn 2: User request**

```
<start_of_turn>user
Hey, what's the weather in Tokyo right now?<end_of_turn>
```

**Turn 3: Model issues tool call**

```
<start_function_call>call:get_current_weather{location:<escape>Tokyo, Japan<escape>}<end_function_call>
```

**Turn 4: Developer provides tool response**

```
<start_function_response>response:get_current_weather{temperature:15,weather:<escape>sunny<escape>}<end_function_response>
```

**Turn 5: Model final response**

```
The current weather in Tokyo is sunny with a temperature of 15 degrees Celsius.
```

## Full Function Calling Sequence (Transformers Example)

The Hugging Face flow uses `AutoProcessor` + `AutoModelForCausalLM`:

1) Build the chat template with the developer prompt and user prompt.
2) Generate model output and parse `<start_function_call>` content.
3) Execute the tool and append a `tool`‑role response.
4) Generate the final response.

Key trigger prompt:

```
{"role": "developer", "content": "You are a model that can do function calling with the following functions"}
```

## Fine‑Tuning FunctionGemma (High‑Level)

FunctionGemma benefits from fine‑tuning when you need:

- Better tool selection between overlapping tools
- Domain‑specific tool schemas
- Shorter prompts (baking tool definitions into weights)

### Common Use Cases

- Distillation from a larger model
- Non‑standard schemas
- Policy‑specific tool choice (internal vs external search)

### Simple Tool‑Calling Dataset Pattern

Each training sample includes:

- Developer prompt
- User prompt
- Assistant tool call
- Tool definitions

Example structure:

```
{
  "messages": [
    {"role": "developer", "content": "You are a model that can do function calling with the following functions"},
    {"role": "user", "content": "What is the reimbursement limit for travel meals?"},
    {"role": "assistant", "tool_calls": [{"type": "function", "function": {"name": "search_knowledge_base", "arguments": {"query": "travel meal reimbursement limit policy"}}}]}
  ],
  "tools": [
    {"type": "function", "function": {"name": "search_knowledge_base", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "search_google", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
  ]
}
```

### Training Outline (TRL + SFTTrainer)

- Install `transformers`, `datasets`, `trl`, `accelerate`, and `torch`
- Build dataset with message/tool schema
- Create `SFTTrainer` with a `SFTConfig`
- Train, then evaluate on a held‑out test split

### Typical Results

- **Before fine‑tuning**: low tool selection accuracy
- **After fine‑tuning**: substantially higher correct tool choice

## Practical Takeaways

- Always include the developer function‑calling trigger in the prompt.
- Use `<escape>` for all string values in FunctionGemma formatted output.
- Prefer single‑turn or parallel tool calls unless fine‑tuned for chaining.
- Expand tool descriptions to include semantic cues (e.g., hot/cold ⇒ temperature tool).
- Fine‑tune to resolve tool‑selection ambiguity in production workflows.
