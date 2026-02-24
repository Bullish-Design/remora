# V2 Pydantic Integration Options

> Deep dive into Pydantic integration opportunities for Remora V2

---

## Executive Summary

This guide explores advanced Pydantic integration options for Remora V2. The key insight: **what if agents themselves were Pydantic models?**

---

## 1. Agents as Pydantic Models

### The Concept

Instead of defining agents as data (bundle name + target code), what if agents were actual Python classes that inherit from a base `AgentNode`?

```python
class LintAgent(AgentNode):
    """An agent that lints code."""
    
    # Define inputs as Pydantic fields
    target_file: str = Field(description="File path to lint")
    strict: bool = Field(default=False, description="Enable strict mode")
    
    # Define outputs  
    errors_found: int = 0
    fixed_files: list[str] = []
    
    async def run(self) -> "LintAgent":
        """Execute the linting agent."""
        # Agent has full access to its own config
        config = f"--strict={self.strict}" if self.strict else ""
        result = await self.execute_tool("run_linter", {
            "file": self.target_file,
            "config": config
        })
        
        self.errors_found = result["error_count"]
        self.fixed_files = result.get("fixed", [])
        
        return self

# Usage
agent = LintAgent(target_file="src/main.py", strict=True)
result = await agent.execute()
print(result.errors_found)
```

### How It Works

```python
class AgentNode(BaseModel):
    """Base class for all agents."""
    model_config = ConfigDict(frozen=False)  # Allow mutation during execution
    
    # Identity
    id: str = Field(default_factory=lambda: f"agent-{uuid.uuid4().hex[:8]}")
    
    # State
    state: AgentState = AgentState.PENDING
    
    # Inbox for user interaction
    inbox: AgentInbox = Field(default_factory=AgentInbox)
    
    # Execution context (set during run)
    _context: dict = {}
    
    def execute_tool(self, name: str, args: dict) -> dict:
        """Execute a tool from the bundle."""
        # ...
    
    async def run(self) -> "AgentNode":
        """Override in subclasses."""
        raise NotImplementedError


class LintAgent(AgentNode):
    """Concrete agent implementation."""
    target_file: str
    strict: bool = False
    
    async def run(self) -> "LintAgent":
        self.state = AgentState.RUNNING
        # ... execution logic
        self.state = AgentState.COMPLETED
        return self
```

### Pros

| Pro | Explanation |
|-----|-------------|
| **Type safety** | IDE autocomplete, catch typos at development time |
| **Self-documenting** | Field descriptions become tool descriptions |
| **Validation** | Invalid configs rejected at creation |
| **Inheritance** | Share behavior via class hierarchy |
| **Introspection** | Inspect agent class for tool generation |

### Cons

| Con | Explanation |
|-----|-------------|
| **Learning curve** | More OOP than current data-driven approach |
| **Serialization** | Complex to serialize/deserialize class instances |
| **Performance** | Pydantic overhead vs simple dataclass |
| **Bundle coupling** | Harder to swap bundles dynamically |

### Implications

1. **Tool generation is automatic**: Each field becomes a tool parameter
2. **Documentation is automatic**: Field descriptions become tool descriptions
3. **Composition via inheritance**: Common behavior in base classes
4. **Serialization needs care**: Use `model_dump()` for persistence

---

## 2. Context-Aware Field Descriptors

### The Concept

A custom Pydantic Field that automatically generates tool descriptions from code:

```python
class LintAgent(AgentNode):
    # Description from docstring
    target_file: str = AgentField(
        description="The file to lint",
        tool_name="lint_file",
    )
    
    # Auto-generate from type annotation
    max_errors: int = AgentField(default=10)
    
    # Type triggers UI rendering
    output_format: Literal["json", "table", "html"] = AgentField(
        default="table",
        ui_renderer="format_selector"
    )
```

### Implementation

```python
from pydantic import Field
from typing import Any, Callable, TypeVar, Generic

T = TypeVar("T")

class AgentField:
    """Custom descriptor for agent fields.
    
    Generates tool descriptions, UI hints, and validation.
    """
    
    def __init__(
        self,
        default: Any = ...,
        *,
        description: str | None = None,
        tool_name: str | None = None,
        ui_renderer: str | None = None,
        required: bool = False,
        validator: Callable | None = None,
    ):
        self.default = default
        self.description = description
        self.tool_name = tool_name
        self.ui_renderer = ui_renderer
        self.required = required
        self.validator = validator
    
    def __repr__(self):
        return f"AgentField(default={self.default!r}, description={self.description!r})"


def AgentField(
    default: T = ...,
    *,
    description: str | None = None,
    tool_name: str | None = None,
    ui_renderer: str | None = None,
    required: bool = False,
) -> T:
    """Create an agent field with automatic tool generation."""
    # This would be processed by a custom validator
    ...
```

### Pros

| Pro | Explanation |
|-----|-------------|
| **Single source of truth** | Description written once, used everywhere |
| **UI hints** | Custom renderers for different field types |
| **Type-aware** | Can infer descriptions from types |

### Cons

| Con | Explanation |
|-----|-------------|
| **Magic** | Behavior not obvious from reading code |
| **Complexity** | Custom descriptor adds indirection |

---

## 3. Method-Based Tool Generation

### The Concept

Automatically expose agent methods as tools:

```python
class DocstringAgent(AgentNode):
    """Generates docstrings for Python code."""
    
    target_source: str = ""
    style: str = "google"
    
    async def generate_docstring(self, node_type: str) -> str:
        """Generate a docstring for a code node.
        
        This becomes a tool the agent can call!
        """
        prompt = f"Generate {self.style} docstring for:\n{self.target_source}"
        result = await self.execute_tool("llm_generate", {"prompt": prompt})
        return result["docstring"]
    
    async def validate_docstring(self, docstring: str) -> bool:
        """Validate a docstring matches the style."""
        # Tool for validation
        return True
```

### How Tools Are Generated

```python
class AgentNode(BaseModel):
    """Base class with automatic tool generation."""
    
    @property
    def tools(self) -> list[dict]:
        """Auto-generate tools from methods."""
        tools = []
        
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if name.startswith("_"):
                continue
            
            # Check if method should be a tool
            if hasattr(method, "__tool__"):
                tools.append({
                    "name": method.__tool_name__ or name,
                    "description": method.__doc__ or "",
                    "parameters": method.__tool_params__ or {},
                })
        
        return tools


def tool(name: str | None = None, description: str = ""):
    """Decorator to mark a method as a tool."""
    def decorator(func):
        func.__tool__ = True
        func.__tool_name__ = name or func.__name__
        func.__tool_description__ = description
        return func
    return decorator


class MyAgent(AgentNode):
    @tool(name="calculate", description="Perform a calculation")
    async def calculate(self, expression: str) -> str:
        """Evaluate a math expression."""
        return str(eval(expression))
```

### Pros

| Pro | Explanation |
|-----|-------------|
| **Natural** | Methods ARE the tools |
| **Self-documenting** | Docstrings become tool descriptions |
| **Type-safe** | Parameters validated by Pydantic |

### Cons

| Con | Explanation |
|-----|-------------|
| **Complex** | Need to handle async/sync, serialization |
| **Testing** | Harder to test tools in isolation |

---

## 4. Agent Registry with Pydantic Models

### The Concept

Register agents as Pydantic model classes:

```python
# Registry of available agents
AGENT_REGISTRY: dict[str, type[AgentNode]] = {}

def register_agent(cls: type[AgentNode]) -> type[AgentNode]:
    """Decorator to register an agent class."""
    AGENT_REGISTRY[cls.__name__] = cls
    return cls

@register_agent
class LintAgent(AgentNode):
    """Lints code files."""
    target_file: str
    
    async def run(self):
        ...

# Later, instantiate from registry
agent_class = AGENT_REGISTRY["LintAgent"]
agent = agent_class(target_file="src/main.py")
```

### Registry with Validation

```python
class AgentRegistry(BaseModel):
    """Registry of available agents with validation."""
    
    agents: dict[str, type[AgentNode]] = Field(default_factory=dict)
    
    def register(self, name: str, cls: type[AgentNode]) -> None:
        # Validate class is actually an AgentNode
        if not issubclass(cls, AgentNode):
            raise ValueError(f"{name} must inherit from AgentNode")
        
        self.agents[name] = cls
    
    def create(self, name: str, **config) -> AgentNode:
        if name not in self.agents:
            raise KeyError(f"Unknown agent: {name}")
        return self.agents[name](**config)
    
    def list_agents(self) -> list[dict]:
        """List all registered agents with their schemas."""
        return [
            {
                "name": name,
                "description": cls.__doc__,
                "fields": cls.model_fields,
            }
            for name, cls in self.agents.items()
        ]
```

---

## 5. Event Schema with Pydantic

### The Concept

Define all event types as Pydantic models for strict typing:

```python
# Event base
class BaseEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: datetime = Field(default_factory=datetime.now)
    agent_id: str

# Specific events
class AgentStartedEvent(BaseEvent):
    type: Literal["agent_started"] = "agent_started"

class AgentBlockedEvent(BaseEvent):
    type: Literal["agent_blocked"] = "agent_blocked"
    question: str
    options: list[str] | None = None
    timeout: float = 300.0

class ToolCalledEvent(BaseEvent):
    type: Literal["tool_called"] = "tool_called"
    tool_name: str
    arguments: dict

# Discriminated union
Event = Annotated[
    AgentStartedEvent | AgentBlockedEvent | ToolCalledEvent,
    Field(discriminator="type")
]
```

### Pros

- Complete type safety for all events
- Validation on event creation
- IDE autocomplete for event payloads

### Cons

- More verbose than current approach
- Adding new events requires code changes

---

## 6. "Out There" Ideas

### 6.1 Agent Composition via Mixins

```python
class HasLLM(Generic[T], BaseModel):
    """Mixin for agents that use LLM."""
    model_name: str = "gpt-4"
    
    async def llm(self, prompt: str) -> str:
        ...

class HasFilesystem(Generic[T], BaseModel):
    """Mixin for agents that work with files."""
    working_dir: Path = Path(".")
    
    async def read_file(self, path: str) -> str:
        ...

# Compose
class DocstringAgent(HasLLM, HasFilesystem, AgentNode):
    target: str
```

### 6.2 DSL for Agent Definition

```python
# Declarative agent definition
agent = (
    Agent("docstring")
    .description("Generates docstrings")
    .field("target", str, description="Code to document")
    .field("style", Literal["google", "numpy"], default="google")
    .tool("validate", description="Validate docstring")
    .depends_on("lint")  # Run after lint
    .build()
)
```

### 6.3 Runtime Agent Generation

```python
# Generate agent at runtime from config
config = {
    "name": "CustomAgent",
    "fields": {
        "input_file": {"type": "str"},
        "output_format": {"type": "literal", "values": ["json", "yaml"]}
    },
    "tools": [
        {"name": "process", "prompt": "Process the file..."}
    ]
}

AgentClass = generate_agent_class(config)
agent = AgentClass(input_file="data.txt", output_format="json")
```

### 6.4 Agent Template System

```python
# Templates that can be instantiated
class Template(AgentNode):
    """Base template - override fields."""
    
    @classmethod
    def instantiate(cls, **overrides) -> "AgentNode":
        """Create a configured instance."""
        return cls(**overrides)

class CodeReviewTemplate(Template):
    target: str = ""  # Override this
    max_files: int = 10  # Or this
    
# Usage
review_agent = CodeReviewTemplate.instantiate(
    target="src/",
    max_files=50
)
```

### 6.5 Self-Modifying Agents

```python
class AdaptiveAgent(AgentNode):
    """Agent that modifies its own behavior."""
    
    _behavior: dict = {}
    
    async def learn(self, feedback: str) -> None:
        """Learn from user feedback and adjust approach."""
        # Modify internal state based on feedback
        self._behavior["last_feedback"] = feedback
        
        # Could even modify tool parameters
```

### 6.6 Graph Composition as Data

```python
# Define graph as pure data (validated by Pydantic)
class GraphDefinition(BaseModel):
    name: str
    agents: list[AgentConfig]
    edges: list[Edge]

class Edge(BaseModel):
    from_agent: str
    to_agent: str
    condition: str | None = None  # "on_success", "always", etc.

# Serialize/validate graphs
graph = GraphDefinition(
    name="analysis",
    agents=[
        AgentConfig(name="lint", bundle="lint"),
        AgentConfig(name="docstring", bundle="docstring"),
    ],
    edges=[
        Edge(from_agent="lint", to_agent="docstring", condition="on_success"),
    ]
)
```

---

## Summary: Recommendations

### High Value, Low Complexity

1. **AgentRegistry** - Simple registry pattern with Pydantic validation
2. **Tool decorator** - Mark methods as tools with descriptions
3. **Event schemas** - Type-safe event definitions

### Medium Value, Medium Complexity

4. **Agents as Pydantic models** - Classes inheriting from AgentNode
5. **Field descriptors** - Auto-generate tool descriptions
6. **Graph as data** - Define graphs in YAML/JSON, validate with Pydantic

### Experimental, High Complexity

7. **Runtime generation** - Create agents from config
8. **Self-modifying agents** - Agents that evolve
9. **Mixin composition** - Build agents from reusable pieces

---

## Recommended Path Forward

For Remora V2, I recommend starting with:

1. **Phase 1**: Keep AgentNode as dataclass for performance
2. **Phase 2**: Add tool decorator for method→tool conversion
3. **Phase 3**: Add AgentRegistry for discovery
4. **Phase 4**: Consider Pydantic models for agents if UX proves valuable

This gives us 80% of the benefit with minimal complexity.

---

*End of Pydantic Options Guide*
