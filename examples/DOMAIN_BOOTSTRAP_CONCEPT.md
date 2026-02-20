# Domain Bootstrap System

> **Status**: Concept
> **Category**: Reactive Code Generation Pattern
> **Use Case**: Framework-specific scaffolding with LSP-driven suggestions

---

## User Guide

### What Is This?

The Domain Bootstrap System is an **intelligent scaffolding engine** that watches what you type and proactively generates framework-specific boilerplate. When you start typing a Pydantic model, FastAPI endpoint, or SQLAlchemy table, specialized agents spring into action:

- **Detect** what you're building (Pydantic model? FastAPI route?)
- **Generate** validators, tests, docstrings, and related code
- **Suggest** patterns from "gold standard" examples
- **Offer** code actions to accept or customize suggestions

It's like having a framework expert pair-programming with you.

### Why Should I Care?

| Manual Approach | Domain Bootstrap |
|-----------------|------------------|
| Write model, then validators, then tests | All generated as you type |
| Look up docs for correct patterns | Patterns suggested from embeddings |
| Copy-paste from other files | Templates applied automatically |
| Miss edge cases in validation | Validators from known patterns |
| Forget to add docstrings | Documentation generated inline |

### Supported Domains

#### Pydantic Pack
When you create a `BaseModel` subclass:
- **Validators**: Field validators for common types (email, URL, phone)
- **Config**: Model configuration suggestions
- **Tests**: pytest fixtures and test cases
- **Docstrings**: Field descriptions and class documentation

#### FastAPI Pack
When you create an endpoint:
- **Response Models**: Auto-generate Pydantic response models
- **Dependencies**: Suggest `Depends()` patterns
- **Documentation**: OpenAPI descriptions
- **Tests**: TestClient test cases

#### SQLAlchemy Pack
When you create a table:
- **Migrations**: Alembic migration stubs
- **Repositories**: CRUD repository pattern
- **Relationships**: Backref suggestions
- **Indexes**: Index recommendations

### What You See

#### Example: Creating a Pydantic Model

You start typing:

```python
class User(BaseModel):
    name: str
    email: str|
```

As soon as you type `email: str`, code actions appear:

```
💡 Use EmailStr instead of str (Recommended)
💡 Add email validator
💡 Add field description
💡 Generate User tests
```

Click "Add email validator" and code is inserted:

```python
class User(BaseModel):
    name: str
    email: EmailStr

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validate email format and normalize."""
        if not v or "@" not in v:
            raise ValueError("Invalid email format")
        return v.lower().strip()
```

Continue adding fields:

```python
class User(BaseModel):
    name: str
    email: EmailStr
    created_at: datetime|
```

More suggestions appear:

```
💡 Add default_factory for created_at (Recommended)
💡 Use UTC timezone
```

#### Example: Creating a FastAPI Endpoint

You type:

```python
@app.post("/users")
async def create_user(|
```

Suggestions appear:

```
💡 Add request body parameter (Recommended)
💡 Add response model
💡 Add dependencies
```

Accept "Add request body parameter":

```python
@app.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Create a new user.

    Args:
        user: User creation data
        db: Database session

    Returns:
        Created user with generated ID
    """
    ...
```

The system also generates related files:

```
📁 Generated files:
  └── tests/test_users.py (3 test cases)
  └── src/schemas/user.py (UserCreate, UserResponse)
```

### Template Packs

Templates are `.pym` scripts that generate Jinja templates:

```
.grail/
├── templates/
│   ├── pydantic/
│   │   ├── validator.pym      # Field validators
│   │   ├── model_config.pym   # Model configuration
│   │   └── test.pym           # Test generation
│   │
│   ├── fastapi/
│   │   ├── endpoint.pym       # Route handler
│   │   ├── dependency.pym     # Depends() pattern
│   │   └── test.pym           # TestClient tests
│   │
│   └── sqlalchemy/
│       ├── model.pym          # ORM model
│       ├── migration.pym      # Alembic migration
│       └── repository.pym     # Repository pattern
```

### Gold Standard Embeddings

The system learns from curated examples:

```yaml
# .remora/bootstrap.yaml
bootstrap:
  embeddings:
    pydantic:
      # Official documentation
      - url: https://docs.pydantic.dev/
        sections: [validators, types, config]

      # Curated "gold standard" repositories
      - repo: https://github.com/example/best-pydantic-practices
        patterns: ["**/models/**/*.py"]

      # Your own codebase patterns
      - local: src/models/
        weight: 2.0  # Prefer local patterns

    fastapi:
      - url: https://fastapi.tiangolo.com/
      - repo: https://github.com/tiangolo/full-stack-fastapi-template
```

When generating validators, the system searches these embeddings:

```
Query: "email field validation pydantic v2"
Results:
  1. [docs] Pydantic V2: Email validation with EmailStr
  2. [gold] user_model.py: Custom email validator with normalization
  3. [local] src/models/account.py: Your existing email pattern
```

### Configuration

```yaml
# .remora/bootstrap.yaml
bootstrap:
  enabled: true

  # Trigger sensitivity
  triggers:
    debounce: 500ms        # Wait for typing to pause
    min_context: 2         # Minimum lines before suggesting

  # Domain packs
  packs:
    pydantic:
      enabled: true
      auto_emailstr: true          # Auto-suggest EmailStr
      auto_validators: true        # Suggest validators
      auto_field_descriptions: true
      test_framework: pytest

    fastapi:
      enabled: true
      auto_response_model: true
      auto_dependencies: true
      auto_docs: true

    sqlalchemy:
      enabled: true
      auto_migrations: false  # Require explicit confirmation
      repository_pattern: true

  # Template customization
  templates:
    # Override built-in templates
    custom_dir: .remora/templates/

    # Variables available in all templates
    variables:
      author: "{{ git.user.name }}"
      company: "Acme Corp"

  # Code action behavior
  code_actions:
    auto_apply: false      # Always show, don't auto-apply
    group_related: true    # Group related actions together
    show_preview: true     # Show preview before applying
```

### Adding Custom Triggers

```yaml
# .remora/bootstrap.yaml
bootstrap:
  custom_triggers:
    # Trigger on specific pattern
    - name: celery_task
      pattern: '@celery_app\.task'
      actions:
        - template: celery/task_retry.pym
        - template: celery/task_test.pym

    # Trigger on class inheritance
    - name: custom_exception
      pattern: 'class\s+\w+\(Exception\)'
      actions:
        - template: exceptions/custom.pym
```

---

## Developer Guide

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                          IDE / Editor                            │
│                                                                  │
│   User types: class User(BaseModel):                            │
│                   email: str                                     │
└─────────────────────────────────────────────────────────────────┘
                    │
                    │ textDocument/didChange
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Remora LSP Server                             │
│                                                                  │
│   TriggerDetector: Detects "pydantic_field_added"               │
└─────────────────────────────────────────────────────────────────┘
                    │
                    │ Dispatches to domain agents
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│ Validator  │ │ Docstring  │ │   Test     │
│   Agent    │ │   Agent    │ │  Agent     │
│            │ │            │ │            │
│ Searches   │ │ Generates  │ │ Generates  │
│ embeddings │ │ Field()    │ │ pytest     │
│ for pattern│ │ desc       │ │ cases      │
└─────┬──────┘ └─────┬──────┘ └─────┬──────┘
      │              │              │
      └──────────────┼──────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Template Engine                               │
│                                                                  │
│   .pym scripts → Jinja templates → Code                         │
└─────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Code Actions                                  │
│                                                                  │
│   💡 Add email validator                                        │
│   💡 Add field description                                      │
│   💡 Generate User tests                                        │
└─────────────────────────────────────────────────────────────────┘
```

### Core Components

#### TriggerDetector

```python
# remora/bootstrap/triggers.py

class TriggerDetector:
    """Detects code patterns that trigger bootstrap actions."""

    def __init__(self, config: BootstrapConfig):
        self.config = config
        self.triggers = self._load_triggers()

    def detect(
        self,
        document: TextDocument,
        change: TextDocumentChange,
    ) -> list[DetectedTrigger]:
        """Detect triggers in document change.

        Args:
            document: Full document content
            change: What changed

        Returns:
            List of detected triggers
        """
        detected = []

        # Get context around change
        context = self._get_context(document, change)

        for trigger in self.triggers:
            match = trigger.matches(context)
            if match:
                detected.append(DetectedTrigger(
                    trigger=trigger,
                    match=match,
                    context=context,
                ))

        return detected

    def _load_triggers(self) -> list[Trigger]:
        """Load built-in and custom triggers."""
        triggers = []

        # Built-in Pydantic triggers
        triggers.append(Trigger(
            name="pydantic_model_created",
            pattern=r"class\s+(\w+)\(.*BaseModel.*\):",
            domain="pydantic",
            actions=["docstring", "config", "test"],
        ))

        triggers.append(Trigger(
            name="pydantic_field_added",
            pattern=r"^\s+(\w+):\s*(str|int|float|bool|EmailStr|HttpUrl|datetime)\s*(?:=|$)",
            domain="pydantic",
            actions=["validator", "description"],
            context_required=["BaseModel"],  # Must be inside BaseModel
        ))

        # Built-in FastAPI triggers
        triggers.append(Trigger(
            name="fastapi_endpoint_created",
            pattern=r"@(?:app|router)\.(get|post|put|patch|delete)\s*\(",
            domain="fastapi",
            actions=["response_model", "dependency", "test"],
        ))

        # Custom triggers from config
        for custom in self.config.custom_triggers:
            triggers.append(Trigger.from_config(custom))

        return triggers


@dataclass
class Trigger:
    """A pattern that triggers bootstrap actions."""
    name: str
    pattern: str
    domain: str
    actions: list[str]
    context_required: list[str] | None = None

    def matches(self, context: CodeContext) -> TriggerMatch | None:
        """Check if trigger matches context."""
        # Check pattern
        match = re.search(self.pattern, context.current_line)
        if not match:
            return None

        # Check required context
        if self.context_required:
            for required in self.context_required:
                if required not in context.surrounding_code:
                    return None

        return TriggerMatch(
            trigger=self,
            groups=match.groups(),
            line=context.line_number,
        )
```

#### BootstrapAgent

```python
# remora/bootstrap/agents/base.py

class BootstrapAgent(ABC):
    """Base class for domain-specific bootstrap agents."""

    domain: str

    def __init__(
        self,
        model: FunctionGemmaModel,
        embeddings: EmbeddingsStore,
        template_engine: TemplateEngine,
    ):
        self.model = model
        self.embeddings = embeddings
        self.templates = template_engine

    @abstractmethod
    async def generate_actions(
        self,
        trigger: DetectedTrigger,
        context: CodeContext,
    ) -> list[CodeAction]:
        """Generate code actions for a trigger.

        Args:
            trigger: The detected trigger
            context: Code context

        Returns:
            List of code actions to offer
        """
        ...

    async def search_patterns(
        self,
        query: str,
        limit: int = 5,
    ) -> list[PatternResult]:
        """Search embeddings for relevant patterns."""
        embedding = await self.embeddings.embed_query(query)
        return await self.embeddings.search(
            embedding,
            domain=self.domain,
            limit=limit,
        )
```

#### PydanticBootstrapAgent

```python
# remora/bootstrap/agents/pydantic.py

class PydanticBootstrapAgent(BootstrapAgent):
    """Bootstrap agent for Pydantic models."""

    domain = "pydantic"

    async def generate_actions(
        self,
        trigger: DetectedTrigger,
        context: CodeContext,
    ) -> list[CodeAction]:
        actions = []

        if trigger.name == "pydantic_field_added":
            actions.extend(await self._handle_field_added(trigger, context))

        elif trigger.name == "pydantic_model_created":
            actions.extend(await self._handle_model_created(trigger, context))

        return actions

    async def _handle_field_added(
        self,
        trigger: DetectedTrigger,
        context: CodeContext,
    ) -> list[CodeAction]:
        """Handle new field added to Pydantic model."""
        actions = []

        field_name = trigger.match.groups[0]
        field_type = trigger.match.groups[1]

        # 1. Check if we should suggest a better type
        type_suggestion = await self._suggest_type(field_name, field_type)
        if type_suggestion:
            actions.append(type_suggestion)

        # 2. Search for validator patterns
        if self._should_suggest_validator(field_name, field_type):
            validator_action = await self._generate_validator_action(
                field_name, field_type, context
            )
            if validator_action:
                actions.append(validator_action)

        # 3. Suggest field description
        if self.config.auto_field_descriptions:
            desc_action = await self._generate_description_action(
                field_name, field_type, context
            )
            actions.append(desc_action)

        return actions

    async def _generate_validator_action(
        self,
        field_name: str,
        field_type: str,
        context: CodeContext,
    ) -> CodeAction | None:
        """Generate validator code action."""
        # Search embeddings for similar validators
        patterns = await self.search_patterns(
            f"{field_name} {field_type} validator pydantic"
        )

        if not patterns:
            return None

        # Use best pattern as template
        best_pattern = patterns[0]

        # Generate validator using template
        validator_code = await self.templates.render(
            "pydantic/validator.pym",
            {
                "field_name": field_name,
                "field_type": field_type,
                "pattern": best_pattern,
                "model_name": context.get_class_name(),
            }
        )

        return CodeAction(
            title=f"Add {field_name} validator",
            kind=CodeActionKind.QuickFix,
            edit=TextEdit(
                range=self._find_insert_position(context),
                new_text=validator_code,
            ),
            is_preferred=True,  # Recommend this action
        )

    async def _suggest_type(
        self,
        field_name: str,
        field_type: str,
    ) -> CodeAction | None:
        """Suggest better type based on field name."""
        suggestions = {
            ("email", "str"): ("EmailStr", "Use EmailStr for email validation"),
            ("url", "str"): ("HttpUrl", "Use HttpUrl for URL validation"),
            ("phone", "str"): ("PhoneNumber", "Use PhoneNumber from pydantic-extra-types"),
        }

        for (name_pattern, current_type), (suggested, reason) in suggestions.items():
            if name_pattern in field_name.lower() and field_type == current_type:
                return CodeAction(
                    title=f"Use {suggested} instead of {current_type} (Recommended)",
                    kind=CodeActionKind.QuickFix,
                    edit=TextEdit(
                        range=self._get_type_range(),
                        new_text=suggested,
                    ),
                    is_preferred=True,
                )

        return None
```

#### FastAPIBootstrapAgent

```python
# remora/bootstrap/agents/fastapi.py

class FastAPIBootstrapAgent(BootstrapAgent):
    """Bootstrap agent for FastAPI endpoints."""

    domain = "fastapi"

    async def generate_actions(
        self,
        trigger: DetectedTrigger,
        context: CodeContext,
    ) -> list[CodeAction]:
        actions = []

        if trigger.name == "fastapi_endpoint_created":
            # Get HTTP method
            method = trigger.match.groups[0]  # get, post, etc.

            # 1. Suggest request body for POST/PUT/PATCH
            if method in ("post", "put", "patch"):
                body_action = await self._generate_request_body_action(context)
                actions.append(body_action)

            # 2. Suggest response model
            response_action = await self._generate_response_model_action(
                method, context
            )
            actions.append(response_action)

            # 3. Suggest common dependencies
            deps_action = await self._generate_dependencies_action(context)
            if deps_action:
                actions.append(deps_action)

            # 4. Generate test file
            test_action = await self._generate_test_action(method, context)
            actions.append(test_action)

        return actions

    async def _generate_request_body_action(
        self,
        context: CodeContext,
    ) -> CodeAction:
        """Generate request body parameter suggestion."""
        # Infer model name from endpoint path
        endpoint_name = context.get_function_name()
        model_name = self._infer_model_name(endpoint_name)

        # Generate request model
        model_code = await self.templates.render(
            "fastapi/request_model.pym",
            {
                "model_name": f"{model_name}Create",
                "endpoint_name": endpoint_name,
            }
        )

        # Generate parameter code
        param_code = f"{model_name.lower()}: {model_name}Create"

        return CodeAction(
            title="Add request body parameter (Recommended)",
            kind=CodeActionKind.QuickFix,
            edit=WorkspaceEdit(
                changes={
                    # Add parameter to function
                    context.uri: [TextEdit(
                        range=self._find_param_position(context),
                        new_text=param_code,
                    )],
                    # Create model file if needed
                    self._get_schema_uri(model_name): [TextEdit(
                        range=Range(Position(0, 0), Position(0, 0)),
                        new_text=model_code,
                    )],
                }
            ),
            is_preferred=True,
        )

    async def _generate_test_action(
        self,
        method: str,
        context: CodeContext,
    ) -> CodeAction:
        """Generate test file for endpoint."""
        endpoint_name = context.get_function_name()
        path = context.get_decorator_arg("path") or f"/{endpoint_name}"

        test_code = await self.templates.render(
            "fastapi/test.pym",
            {
                "endpoint_name": endpoint_name,
                "method": method,
                "path": path,
                "has_body": method in ("post", "put", "patch"),
            }
        )

        test_file = self._get_test_file_path(context)

        return CodeAction(
            title=f"Generate tests for {endpoint_name}",
            kind=CodeActionKind.Source,
            command=Command(
                title="Create test file",
                command="remora.createFile",
                arguments=[str(test_file), test_code],
            ),
        )
```

### Template Engine

The key innovation: `.pym` scripts that **output Jinja templates**.

```python
# remora/bootstrap/templates.py

class TemplateEngine:
    """Renders .pym template scripts."""

    def __init__(
        self,
        template_dir: Path,
        grail_executor: GrailExecutor,
    ):
        self.template_dir = template_dir
        self.grail = grail_executor
        self.jinja = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    async def render(
        self,
        template_path: str,
        variables: dict,
    ) -> str:
        """Render a template with variables.

        1. Execute .pym script to generate Jinja template
        2. Render Jinja template with variables
        3. Return final code
        """
        pym_path = self.template_dir / template_path

        # Execute .pym script
        result = await self.grail.execute(
            pym_path,
            inputs=variables,
        )

        # The .pym script returns a Jinja template
        jinja_template = result["template"]

        # Merge script variables with caller variables
        all_vars = {**result.get("variables", {}), **variables}

        # Render Jinja template
        template = self.jinja.from_string(jinja_template)
        return template.render(**all_vars)
```

#### Example .pym Template Script

```python
# .grail/templates/pydantic/validator.pym
"""Generate a field validator for a Pydantic model."""

from grail import Input, external

field_name: str = Input("field_name")
field_type: str = Input("field_type")
model_name: str = Input("model_name")
pattern: dict = Input("pattern", default={})

@external
async def search_patterns(query: str) -> list[dict]:
    """Search embeddings for patterns."""
    ...

async def main() -> dict:
    # Search for similar validators if not provided
    if not pattern:
        patterns = await search_patterns(
            f"{field_type} validator pydantic"
        )
        if patterns:
            pattern = patterns[0]

    # Determine validation logic based on field type/name
    validation_logic = _get_validation_logic(field_name, field_type, pattern)

    # Generate Jinja template
    template = '''
@field_validator("{{ field_name }}")
@classmethod
def validate_{{ field_name }}(cls, v: {{ field_type }}) -> {{ field_type }}:
    """Validate {{ field_name }}."""
    {% if validation_logic %}
    {{ validation_logic }}
    {% endif %}
    return v
'''

    return {
        "template": template,
        "variables": {
            "field_name": field_name,
            "field_type": field_type,
            "validation_logic": validation_logic,
        },
        "outcome": "success",
    }


def _get_validation_logic(
    field_name: str,
    field_type: str,
    pattern: dict,
) -> str:
    """Determine validation logic."""
    # Use pattern if available
    if pattern and pattern.get("validation_code"):
        return pattern["validation_code"]

    # Fall back to heuristics
    if "email" in field_name.lower():
        return '''if not v or "@" not in v:
        raise ValueError("Invalid email format")
    v = v.lower().strip()'''

    if "phone" in field_name.lower():
        return '''import re
    if not re.match(r"^\\+?[1-9]\\d{1,14}$", v):
        raise ValueError("Invalid phone number format")'''

    if "url" in field_name.lower():
        return '''if not v.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")'''

    return ""
```

### Embeddings Integration

```python
# remora/bootstrap/embeddings.py

class BootstrapEmbeddings:
    """Embeddings store for bootstrap patterns."""

    def __init__(
        self,
        project_root: Path,
        config: EmbeddingsConfig,
    ):
        self.project_root = project_root
        self.config = config
        self.store = EmbeddingsStore(project_root / ".remora" / "embeddings.db")

    async def index_all(self) -> None:
        """Index all configured sources."""
        for domain, sources in self.config.embeddings.items():
            for source in sources:
                await self._index_source(domain, source)

    async def _index_source(
        self,
        domain: str,
        source: EmbeddingsSource,
    ) -> None:
        """Index a single source."""
        if source.url:
            # Fetch and index documentation
            docs = await self._fetch_docs(source.url, source.sections)
            for doc in docs:
                await self.store.index(
                    key=f"doc:{domain}:{doc.path}",
                    content=doc.content,
                    metadata={
                        "domain": domain,
                        "type": "documentation",
                        "source": source.url,
                    },
                )

        elif source.repo:
            # Clone and index repository
            patterns = await self._fetch_repo_patterns(
                source.repo,
                source.patterns,
            )
            for pattern in patterns:
                await self.store.index(
                    key=f"gold:{domain}:{pattern.path}",
                    content=pattern.code,
                    metadata={
                        "domain": domain,
                        "type": "gold_standard",
                        "source": source.repo,
                        "file": pattern.file,
                    },
                )

        elif source.local:
            # Index local patterns with higher weight
            local_patterns = await self._scan_local(source.local)
            weight = source.weight or 1.0

            for pattern in local_patterns:
                await self.store.index(
                    key=f"local:{domain}:{pattern.path}",
                    content=pattern.code,
                    metadata={
                        "domain": domain,
                        "type": "local",
                        "weight": weight,
                    },
                )

    async def search(
        self,
        embedding: list[float],
        domain: str,
        limit: int = 5,
    ) -> list[PatternResult]:
        """Search for patterns in a domain."""
        results = await self.store.search(
            embedding=embedding,
            filter={"domain": domain},
            limit=limit * 2,  # Fetch more, then apply weights
        )

        # Apply weights
        weighted = []
        for result in results:
            weight = result.metadata.get("weight", 1.0)
            weighted.append(PatternResult(
                key=result.key,
                content=result.content,
                score=result.score * weight,
                metadata=result.metadata,
            ))

        # Sort by weighted score
        weighted.sort(key=lambda x: x.score, reverse=True)

        return weighted[:limit]
```

### LSP Integration

```python
# remora/bootstrap/lsp.py

class BootstrapLSPProvider:
    """LSP provider for bootstrap code actions."""

    def __init__(
        self,
        trigger_detector: TriggerDetector,
        agents: dict[str, BootstrapAgent],
        config: BootstrapConfig,
    ):
        self.triggers = trigger_detector
        self.agents = agents
        self.config = config
        self._debouncer = Debouncer(config.triggers.debounce)

    async def handle_did_change(
        self,
        params: DidChangeTextDocumentParams,
    ) -> None:
        """Handle document change - detect triggers."""
        # Debounce rapid changes
        await self._debouncer.wait()

        document = self._get_document(params.text_document.uri)
        change = params.content_changes[-1]

        # Detect triggers
        triggers = self.triggers.detect(document, change)

        if triggers:
            # Store pending actions for code action request
            self._pending_triggers[params.text_document.uri] = triggers

    async def handle_code_action(
        self,
        params: CodeActionParams,
    ) -> list[CodeAction]:
        """Handle code action request - return bootstrap actions."""
        actions = []

        # Get pending triggers for this document
        triggers = self._pending_triggers.get(params.text_document.uri, [])

        # Get context
        context = CodeContext(
            uri=params.text_document.uri,
            document=self._get_document(params.text_document.uri),
            range=params.range,
        )

        # Generate actions from each trigger
        for trigger in triggers:
            agent = self.agents.get(trigger.domain)
            if agent:
                trigger_actions = await agent.generate_actions(trigger, context)
                actions.extend(trigger_actions)

        # Group related actions
        if self.config.code_actions.group_related:
            actions = self._group_actions(actions)

        return actions

    def _group_actions(
        self,
        actions: list[CodeAction],
    ) -> list[CodeAction]:
        """Group related actions together."""
        # Create parent action for groups
        groups = defaultdict(list)

        for action in actions:
            group_key = action.data.get("group") if action.data else None
            if group_key:
                groups[group_key].append(action)
            else:
                groups["ungrouped"].append(action)

        result = []
        for group_key, group_actions in groups.items():
            if len(group_actions) > 1 and group_key != "ungrouped":
                # Create parent action
                result.append(CodeAction(
                    title=f"📦 {group_key} ({len(group_actions)} actions)",
                    kind=CodeActionKind.Source,
                    command=Command(
                        title="Show bootstrap actions",
                        command="remora.showBootstrapActions",
                        arguments=[group_actions],
                    ),
                ))
            else:
                result.extend(group_actions)

        return result
```

---

## Related Concepts

- [Learning Assistant](./LEARNING_ASSISTANT_CONCEPT.md) - Real-time IDE help
- [Feature Assembly Line](./FEATURE_ASSEMBLY_LINE_CONCEPT.md) - Pipeline feature development
- [Continuous Health](./CONTINUOUS_HEALTH_CONCEPT.md) - Background code quality
