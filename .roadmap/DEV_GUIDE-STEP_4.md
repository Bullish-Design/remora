# DEV GUIDE STEP 4: Subagent Definition Format

## Goal
Parse and validate YAML subagent definition files; build the `SubagentDefinition` model and tool schema objects consumed by the FunctionGemmaRunner.

## Why This Matters
The subagent YAML is the contract between the operator (who writes the definition) and the FunctionGemmaRunner (which executes it). If this layer is loose or permissive, bad YAML silently produces broken runners. Strong validation here means problems are caught at load time, not mid-run.

## Implementation Checklist
- Implement `ToolDefinition`, `InitialContext`, and `SubagentDefinition` Pydantic models.
- Implement YAML loader that reads a YAML file and returns a validated `SubagentDefinition`.
- Resolve `model` and `pym` paths relative to `agents_dir` (passed at load time).
- Validate that every subagent definition includes a `submit_result` tool; raise `AGENT_001` if missing.
- Implement `SubagentDefinition.tool_schemas` property returning an OpenAI-style tool list.
- Implement `InitialContext.render(node: CSTNode) -> str` using Jinja2 to interpolate `{{ node_text }}`, `{{ node_name }}`, `{{ node_type }}`, `{{ file_path }}`.

## Suggested File Targets
- `remora/subagent.py` (models + loader)

## Models

```python
class ToolDefinition(BaseModel):
    name: str
    pym: Path                          # Absolute path after resolution
    description: str
    parameters: dict                   # JSON Schema object
    context_providers: list[Path] = [] # Absolute paths after resolution

class InitialContext(BaseModel):
    system_prompt: str
    node_context: str  # Jinja2 template

    def render(self, node: CSTNode) -> str:
        tmpl = jinja2.Template(self.node_context)
        return tmpl.render(
            node_text=node.text,
            node_name=node.name,
            node_type=node.node_type,
            file_path=str(node.file_path),
        )

class SubagentDefinition(BaseModel):
    name: str
    model: Path          # Absolute path to GGUF file after resolution
    max_turns: int = 20
    initial_context: InitialContext
    tools: list[ToolDefinition]

    @property
    def tool_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                    "strict": True,
                }
            }
            for t in self.tools
        ]

    @property
    def tools_by_name(self) -> dict[str, ToolDefinition]:
        return {t.name: t for t in self.tools}
```

## Validation Rules
- Every `SubagentDefinition` must contain exactly one tool named `submit_result`.
- All `pym` paths and `context_providers` paths must be resolvable (warn if not found — GGUF may be absent during development, but `.pym` scripts should always exist once committed).
- `parameters` must be a valid JSON Schema object (has a `type: object` key).
- `additionalProperties: false` should be present on all tool parameter schemas (strict mode); warn if absent.

## Implementation Notes
- Keep path resolution in a single helper: `resolve_path(base: Path, relative: str) -> Path`.
- The `model` path warning (not error) for missing GGUF allows development to proceed without trained models during infrastructure steps.
- Jinja2 rendering happens at runner instantiation time, not at YAML load time.

## Testing Overview
- **Unit test:** Loading a valid YAML fixture returns a `SubagentDefinition` with correct tool count.
- **Unit test:** `tool_schemas` property returns list with correct `type`, `strict`, and parameter structure.
- **Unit test:** YAML missing `submit_result` tool raises `AGENT_001`.
- **Unit test:** `render()` correctly interpolates all CSTNode fields into `node_context` template.
- **Unit test:** `tools_by_name` lookup returns correct `ToolDefinition` for a named tool.
