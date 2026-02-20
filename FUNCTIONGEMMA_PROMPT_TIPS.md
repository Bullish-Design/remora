# FunctionGemma Prompt Tips (vLLM)

This guide summarizes practical lessons from recent FunctionGemma tool‑calling experiments using vLLM with `--tool-call-parser functiongemma` and a FunctionGemma chat template.

## Recommended Server Flags

Use a FunctionGemma‑compatible parser and template:

```
vllm serve google/functiongemma-270m-it \
  --enable-auto-tool-choice \
  --tool-call-parser functiongemma \
  --chat-template /path/to/tool_chat_template_functiongemma.jinja \
  --chat-template-content-format openai
```

## Minimal Single‑Turn Tool Call (Works Reliably)

FunctionGemma responds best when you include a developer message that activates function calling and keep the request short.

```
{
  "model": "google/functiongemma-270m-it",
  "messages": [
    {"role": "developer", "content": "You are a model that can do function calling with the following functions"},
    {"role": "user", "content": "What directory am I in?"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "pwd",
        "description": "Return current directory",
        "parameters": {"type": "object", "properties": {}}
      }
    }
  ],
  "tool_choice": "auto",
  "temperature": 0,
  "max_tokens": 64
}
```

Expected response:

```
"tool_calls": [{"function": {"name": "pwd", "arguments": "{}"}}]
```

## Use a Developer Prompt

The FunctionGemma guide calls out a developer prompt as essential. Keep it simple and consistent:

```
{"role": "developer", "content": "You are a model that can do function calling with the following functions"}
```

## Use `tool_choice: "auto"` or a Single Named Function

FunctionGemma emits tagged tool calls, not JSON lists. Using `tool_choice: "required"` can trigger structured outputs that expect JSON lists and often fails with EOF parse errors.

Recommended:

- `"tool_choice": "auto"`
- `"tool_choice": {"type": "function", "function": {"name": "pwd"}}`

Avoid with FunctionGemma:

- `"tool_choice": "required"` (often tries to parse incomplete JSON arrays)

## Tool Calls in Conversation History Must Include `id`

When you include previous assistant tool calls inside `messages`, vLLM requires an `id` field:

```
{"role":"assistant","tool_calls":[{"id":"toolcall-1","type":"function","function":{"name":"pwd","arguments":"{}"}}]}
```

## Tool Response Format (Important)

FunctionGemma expects tool responses in a name/response mapping. The OpenAI `tool_call_id` format will be rejected.

Use one of these:

**Option A: name + response in content**
```
{"role":"tool","content":"{\"name\":\"find\",\"response\":[\"error_log.txt\"]}"}
```

**Option B: name field at top level**
```
{"role":"tool","name":"find","content":"[\"error_log.txt\"]"}
```

## Multi‑Turn Pattern (Two Sequential Tool Calls)

FunctionGemma is more reliable when you ask for one tool at a time.

1) Ask for the first tool call.
2) Append the tool call to history (with `id`).
3) Add a tool response message using the `name/response` format.
4) Ask the next question.

### Example: Two‑Turn Sequence

**Turn 1: request a tool call**

```
{
  "model": "google/functiongemma-270m-it",
  "messages": [
    {"role": "developer", "content": "You are a model that can do function calling with the following functions"},
    {"role": "user", "content": "Find all files with \"log\" in the name."}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "find",
        "description": "Find files by name",
        "parameters": {
          "type": "object",
          "properties": {
            "path": {"type": "string", "default": "."},
            "name": {"type": "string"}
          },
          "required": ["path", "name"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "temperature": 0,
  "max_tokens": 64
}
```

**Turn 1 expected response**

```
"tool_calls": [
  {"id": "toolcall-1", "type": "function", "function": {"name": "find", "arguments": "{\"path\":\".\",\"name\":\"log\"}"}}
]
```

**Turn 2: provide tool response, then ask next question**

```
{
  "model": "google/functiongemma-270m-it",
  "messages": [
    {"role": "developer", "content": "You are a model that can do function calling with the following functions"},
    {"role": "user", "content": "Find all files with \"log\" in the name."},
    {"role": "assistant", "tool_calls": [
      {"id": "toolcall-1", "type": "function", "function": {"name": "find", "arguments": "{\"path\":\".\",\"name\":\"log\"}"}}
    ]},
    {"role": "tool", "content": "{\"name\":\"find\",\"response\":[\"error_log.txt\"]}"},
    {"role": "user", "content": "Show me the last 5 lines of error_log.txt."}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "tail",
        "description": "Show last lines of file",
        "parameters": {
          "type": "object",
          "properties": {
            "file_name": {"type": "string"},
            "lines": {"type": "integer", "default": 10}
          },
          "required": ["file_name"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "temperature": 0,
  "max_tokens": 64
}
```

## Named Function Example (Strict Harness Test)

Use a named tool choice when you want a deterministic single tool call:

```
{
  "model": "google/functiongemma-270m-it",
  "messages": [
    {"role": "developer", "content": "You are a model that can do function calling with the following functions"},
    {"role": "user", "content": "List the files here."}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "ls",
        "description": "List files",
        "parameters": {"type": "object", "properties": {}}
      }
    }
  ],
  "tool_choice": {"type": "function", "function": {"name": "ls"}},
  "temperature": 0,
  "max_tokens": 64
}
```

## Multiple Tools (Emphasis)

FunctionGemma can see many tools, but it will still emit only one tool call per assistant turn most reliably. When you provide multiple tools in the request:

- Include the full tool list in every request where you want the model to choose.
- Keep each tool’s schema minimal to reduce failure rates.
- Expect a single tool call per turn even if the user asks for multiple actions.

If the model returns multiple tool calls in a single response, you must execute them in order and provide a separate tool response for each call using the name/response mapping:

```
{"role":"tool","content":"{\"name\":\"find\",\"response\":[\"error_log.txt\"]}"}
{"role":"tool","content":"{\"name\":\"tail\",\"response\":\"<tail output>\"}"}
```

### Parallel Tool Calls (When It Happens)

vLLM may return multiple `tool_calls` in one assistant message. Your harness should:

1) Iterate each tool call in order.
2) Execute each tool.
3) Append **one tool response message per tool call**, in the same order.

Example response sequence (two tool calls):

```
{"role":"assistant","tool_calls":[
  {"id":"toolcall-1","type":"function","function":{"name":"find","arguments":"{\"path\":\".\",\"name\":\"log\"}"}},
  {"id":"toolcall-2","type":"function","function":{"name":"tail","arguments":"{\"file_name\":\"error_log.txt\",\"lines\":5}"}}
]}
{"role":"tool","content":"{\"name\":\"find\",\"response\":[\"error_log.txt\"]}"}
{"role":"tool","content":"{\"name\":\"tail\",\"response\":\"<tail output>\"}"}
```

For multi‑step tasks, prefer multi‑turn prompts: ask for one tool call, append the tool response, then ask the next question.

## Keep Prompts Short and Concrete

FunctionGemma is a small model and degrades with long prompts. Prefer short, direct instructions and include explicit arguments in the user message when possible.

## Common Failure Modes

- **Whitespace or empty `arguments`**: the model never emitted values. Reduce prompt length, set `temperature: 0`, and keep schema minimal.
- **`Invalid JSON: EOF while parsing a list`**: `tool_choice: "required"` or named structured outputs expecting a JSON array, but the model returned tagged output or got truncated.
- **Plain text output instead of tool calls**: missing developer prompt or template/parser mismatch.

## Quick Debug Checklist

- Confirm server flags match FunctionGemma parser and template.
- Ensure developer prompt exists.
- Use `tool_choice: "auto"` for FunctionGemma.
- Keep tools list minimal per request.
- Use `temperature: 0` for stable outputs.
- Ensure tool responses include `name` + `response` mapping.
