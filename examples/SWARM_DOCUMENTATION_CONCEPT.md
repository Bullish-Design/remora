# Swarm Documentation Generation

> **Status**: Concept
> **Category**: Multi-Agent Pattern
> **Use Case**: Automated documentation generation from multiple perspectives

---

## User Guide

### What Is This?

Swarm Documentation Generation uses multiple specialized AI agents to create different types of documentation from the same codebase—simultaneously. Each agent has a different "lens" on your code:

- **API Docs Agent**: Generates OpenAPI specs and docstrings
- **Tutorial Agent**: Creates how-to guides and getting-started content
- **Architecture Agent**: Produces system diagrams and component overviews

Instead of one general-purpose tool trying to do everything, you get specialists that excel at their specific task.

### Why Should I Care?

| Pain Point | How Swarm Docs Helps |
|------------|----------------------|
| Documentation is always out of date | Agents run on file changes, keeping docs fresh |
| Writing docs is tedious and repetitive | Automated generation from code structure |
| Different docs have inconsistent style | Each agent is fine-tuned for its output type |
| Cross-referencing is manual and error-prone | Hub provides caller/callee relationships automatically |
| One person can't write all doc types well | Specialized agents for each documentation style |

### Example Workflow

```bash
# Start the documentation swarm
$ remora swarm docs --project ./my-api

# Agents spin up and begin processing
[api-docs] Scanning 47 endpoints...
[tutorial] Analyzing usage patterns...
[architecture] Building dependency graph...

# Output generated
[api-docs] Generated: docs/api/openapi.yaml (47 endpoints)
[tutorial] Generated: docs/tutorials/getting-started.md
[architecture] Generated: docs/ARCHITECTURE.md (3 diagrams)
```

### What Gets Generated

**API Documentation Agent:**
```yaml
# openapi.yaml (auto-generated)
paths:
  /users/{id}:
    get:
      summary: Retrieve a user by ID
      description: |
        Fetches user details including profile and preferences.
        Requires authentication.
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
```

**Tutorial Agent:**
```markdown
# Getting Started with UserService

This guide walks you through common user management tasks.

## Creating a User

The `UserService.create()` method handles user creation with
automatic validation:

    from myapp.services import UserService

    user = await UserService.create(
        email="user@example.com",
        name="Jane Doe"
    )

> **Note**: Email addresses are validated automatically using
> the `EmailValidator` middleware.

## Next Steps
- [Managing User Permissions](./permissions.md)
- [User Authentication Flow](./auth.md)
```

**Architecture Agent:**
```markdown
# System Architecture

## Component Overview

    ┌─────────────┐     ┌─────────────┐
    │   API       │────►│  Services   │
    │  (FastAPI)  │     │             │
    └─────────────┘     └──────┬──────┘
                               │
                        ┌──────▼──────┐
                        │ Repository  │
                        │  (SQLAlchemy)│
                        └──────┬──────┘
                               │
                        ┌──────▼──────┐
                        │  Database   │
                        │ (PostgreSQL)│
                        └─────────────┘

## Dependency Flow

UserRouter → UserService → UserRepository → Database
```

### Configuration

```yaml
# .remora/swarm_docs.yaml
swarm:
  documentation:
    agents:
      - name: api-docs
        model: functiongemma-api-docs-v1
        output: docs/api/
        formats: [openapi, markdown]

      - name: tutorial
        model: functiongemma-tutorial-v1
        output: docs/tutorials/
        analyze_patterns: true  # Look at test files for usage examples

      - name: architecture
        model: functiongemma-architecture-v1
        output: docs/
        diagram_format: mermaid

    triggers:
      - on: file_change
        patterns: ["src/**/*.py"]
        debounce: 5s

      - on: manual
        command: "remora swarm docs"
```

### Incremental Updates

When you modify a file, only affected documentation updates:

```
File changed: src/services/user.py

[api-docs] Updating: UserService.create() signature changed
[api-docs] Updated: docs/api/openapi.yaml (1 endpoint)

[tutorial] Checking: getting-started.md examples still valid
[tutorial] No changes needed

[architecture] No structural changes detected
```

---

## Developer Guide

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Codebase (Copy-on-Write View)               │
└─────────────────────────────────────────────────────────────────┘
                              │
                    Hub provides context
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  API Docs     │    │  Tutorial     │    │  Architecture │
│  Agent        │    │  Agent        │    │  Agent        │
│               │    │               │    │               │
│ FunctionGemma │    │ FunctionGemma │    │ FunctionGemma │
│ (fine-tuned)  │    │ (fine-tuned)  │    │ (fine-tuned)  │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                    │                    │
        ▼                    ▼                    ▼
   openapi.yaml         tutorials/*.md      ARCHITECTURE.md
```

### Core Components

#### SwarmOrchestrator

Coordinates multiple agents running in parallel on the same codebase snapshot.

```python
# remora/swarm/orchestrator.py

class SwarmOrchestrator:
    """Orchestrates parallel documentation agents."""

    def __init__(
        self,
        project_root: Path,
        hub_client: HubClient,
        agents: list[DocumentationAgent],
    ):
        self.project_root = project_root
        self.hub_client = hub_client
        self.agents = agents

    async def run(
        self,
        changed_files: list[Path] | None = None,
    ) -> SwarmResult:
        """Run all agents in parallel.

        Args:
            changed_files: If provided, only process these files.
                          If None, process entire codebase.

        Returns:
            Combined results from all agents.
        """
        # Get Hub context for all relevant nodes
        context = await self._gather_context(changed_files)

        # Run agents in parallel with copy-on-write isolation
        tasks = [
            agent.generate(context, changed_files)
            for agent in self.agents
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        return SwarmResult(
            agents=self.agents,
            results=results,
            changed_files=changed_files,
        )
```

#### DocumentationAgent Base Class

```python
# remora/swarm/agents/base.py

class DocumentationAgent(ABC):
    """Base class for documentation generation agents."""

    def __init__(
        self,
        name: str,
        model: FunctionGemmaModel,
        output_dir: Path,
    ):
        self.name = name
        self.model = model
        self.output_dir = output_dir

    @abstractmethod
    async def generate(
        self,
        context: HubContext,
        changed_files: list[Path] | None,
    ) -> GenerationResult:
        """Generate documentation.

        Args:
            context: Hub context with node metadata
            changed_files: Files that changed (for incremental updates)

        Returns:
            Generated documentation files and metadata
        """
        ...

    async def should_regenerate(
        self,
        node: NodeState,
        existing_doc: Path,
    ) -> bool:
        """Check if documentation needs regeneration.

        Compares source_hash to detect meaningful changes.
        """
        # Read existing doc metadata
        metadata = await self._read_doc_metadata(existing_doc)

        if metadata is None:
            return True  # No existing doc

        return metadata.source_hash != node.source_hash
```

#### API Documentation Agent

```python
# remora/swarm/agents/api_docs.py

class APIDocumentationAgent(DocumentationAgent):
    """Generates OpenAPI specs and endpoint documentation."""

    async def generate(
        self,
        context: HubContext,
        changed_files: list[Path] | None,
    ) -> GenerationResult:
        # Find all API endpoints
        endpoints = self._find_endpoints(context)

        # Filter to changed if incremental
        if changed_files:
            endpoints = [
                e for e in endpoints
                if Path(e.file_path) in changed_files
            ]

        # Generate OpenAPI for each
        specs = []
        for endpoint in endpoints:
            spec = await self._generate_endpoint_spec(endpoint, context)
            specs.append(spec)

        # Merge into single OpenAPI document
        openapi = self._merge_specs(specs)

        # Write output
        output_path = self.output_dir / "openapi.yaml"
        await self._write_yaml(output_path, openapi)

        return GenerationResult(
            files=[output_path],
            nodes_processed=len(endpoints),
        )

    async def _generate_endpoint_spec(
        self,
        endpoint: NodeState,
        context: HubContext,
    ) -> dict:
        """Use fine-tuned model to generate OpenAPI spec."""

        # Build prompt with Hub context
        prompt = self._build_prompt(
            signature=endpoint.signature,
            docstring=endpoint.docstring,
            decorators=endpoint.decorators,
            # Cross-file context from Hub
            dependencies=context.get_callees(endpoint.key),
            response_models=context.get_related_models(endpoint.key),
        )

        # Call fine-tuned FunctionGemma
        result = await self.model.generate(prompt)

        return result.parsed_output
```

#### Tutorial Agent

```python
# remora/swarm/agents/tutorial.py

class TutorialAgent(DocumentationAgent):
    """Generates how-to guides and tutorials."""

    async def generate(
        self,
        context: HubContext,
        changed_files: list[Path] | None,
    ) -> GenerationResult:
        # Analyze usage patterns from tests
        usage_patterns = await self._analyze_test_files(context)

        # Group by feature/domain
        features = self._group_by_feature(usage_patterns)

        # Generate tutorial for each feature
        tutorials = []
        for feature in features:
            if self._needs_update(feature, changed_files):
                tutorial = await self._generate_tutorial(feature, context)
                tutorials.append(tutorial)

        # Write tutorials
        for tutorial in tutorials:
            path = self.output_dir / f"{tutorial.slug}.md"
            await self._write_markdown(path, tutorial.content)

        return GenerationResult(
            files=[t.path for t in tutorials],
            nodes_processed=len(features),
        )

    async def _analyze_test_files(
        self,
        context: HubContext,
    ) -> list[UsagePattern]:
        """Extract usage patterns from test files.

        Tests often demonstrate canonical usage of APIs.
        """
        patterns = []

        for node in context.nodes:
            # Get related tests from Hub
            related_tests = node.related_tests or []

            for test_key in related_tests:
                test_node = context.get(test_key)
                if test_node:
                    pattern = self._extract_pattern(node, test_node)
                    patterns.append(pattern)

        return patterns
```

#### Architecture Agent

```python
# remora/swarm/agents/architecture.py

class ArchitectureAgent(DocumentationAgent):
    """Generates architecture diagrams and overviews."""

    async def generate(
        self,
        context: HubContext,
        changed_files: list[Path] | None,
    ) -> GenerationResult:
        # Build dependency graph from Hub data
        graph = self._build_dependency_graph(context)

        # Detect architectural layers
        layers = self._detect_layers(graph)

        # Generate Mermaid diagrams
        diagrams = await self._generate_diagrams(layers, graph)

        # Generate prose overview
        overview = await self._generate_overview(layers, context)

        # Write output
        output_path = self.output_dir / "ARCHITECTURE.md"
        content = self._format_architecture_doc(overview, diagrams)
        await self._write_markdown(output_path, content)

        return GenerationResult(
            files=[output_path],
            nodes_processed=len(context.nodes),
        )

    def _build_dependency_graph(
        self,
        context: HubContext,
    ) -> DependencyGraph:
        """Build graph from Hub caller/callee data."""
        graph = DependencyGraph()

        for node in context.nodes:
            graph.add_node(node.key, node)

            # Add edges from Hub's cross-file analysis
            for callee in (node.callees or []):
                graph.add_edge(node.key, callee)

        return graph
```

### Hub Integration

The swarm leverages Hub context for cross-file intelligence:

```python
# remora/swarm/context.py

class HubContext:
    """Rich context from Node State Hub."""

    def __init__(self, nodes: dict[str, NodeState]):
        self.nodes = nodes
        self._callers_index = self._build_callers_index()

    def get_callees(self, node_key: str) -> list[str]:
        """Get functions this node calls."""
        node = self.nodes.get(node_key)
        return node.callees if node else []

    def get_callers(self, node_key: str) -> list[str]:
        """Get functions that call this node."""
        return self._callers_index.get(node_key, [])

    def get_related_models(self, node_key: str) -> list[NodeState]:
        """Find Pydantic models used by this endpoint."""
        node = self.nodes.get(node_key)
        if not node:
            return []

        # Find model references in signature/imports
        models = []
        for callee in (node.callees or []):
            callee_node = self.nodes.get(callee)
            if callee_node and callee_node.node_type == "class":
                if "BaseModel" in (callee_node.signature or ""):
                    models.append(callee_node)

        return models
```

### Fine-Tuning Strategy

Each agent uses a specialized FunctionGemma model:

```python
# Training data structure

# API Docs: (code, openapi_spec) pairs
{
    "input": {
        "signature": "@app.get('/users/{id}')\nasync def get_user(id: UUID) -> User",
        "docstring": "Retrieve user by ID",
        "decorators": ["@app.get('/users/{id}')"],
        "response_model": "User(id, name, email)"
    },
    "output": {
        "path": "/users/{id}",
        "method": "get",
        "summary": "Retrieve user by ID",
        "parameters": [...],
        "responses": {...}
    }
}

# Tutorial: (code + tests, prose) pairs
{
    "input": {
        "function": "UserService.create()",
        "test_usage": "user = await service.create(email='...')",
        "related_functions": ["validate_email", "hash_password"]
    },
    "output": "## Creating Users\n\nTo create a new user, call..."
}

# Architecture: (import graph, diagram) pairs
{
    "input": {
        "modules": ["api.users", "services.user", "db.repository"],
        "dependencies": [
            ("api.users", "services.user"),
            ("services.user", "db.repository")
        ]
    },
    "output": "```mermaid\ngraph TD\n    A[API] --> B[Services]\n    B --> C[Repository]\n```"
}
```

### Copy-on-Write Isolation

Agents work on isolated views of the codebase:

```python
# remora/swarm/isolation.py

class CodebaseSnapshot:
    """Immutable snapshot of codebase state."""

    def __init__(
        self,
        root: Path,
        commit_hash: str | None = None,
    ):
        self.root = root
        self.commit_hash = commit_hash or self._get_head()
        self._cache: dict[Path, str] = {}

    async def read_file(self, path: Path) -> str:
        """Read file from snapshot (cached)."""
        if path not in self._cache:
            # Read from git at specific commit, or filesystem
            if self.commit_hash:
                content = await self._git_show(path)
            else:
                content = path.read_text()
            self._cache[path] = content

        return self._cache[path]
```

### Output Merging

When multiple agents finish, results are merged:

```python
# remora/swarm/merge.py

class SwarmResultMerger:
    """Merges outputs from multiple agents."""

    async def merge(
        self,
        results: list[GenerationResult],
    ) -> MergedResult:
        # Collect all generated files
        all_files = []
        for result in results:
            all_files.extend(result.files)

        # Check for conflicts (same file from multiple agents)
        conflicts = self._detect_conflicts(all_files)

        if conflicts:
            # Use conflict resolution strategy
            resolved = await self._resolve_conflicts(conflicts)
            all_files = self._apply_resolutions(all_files, resolved)

        return MergedResult(
            files=all_files,
            conflicts_resolved=len(conflicts),
        )
```

### Extension Points

Add custom documentation agents:

```python
# Custom agent for changelog generation
class ChangelogAgent(DocumentationAgent):
    """Generates CHANGELOG.md from git history."""

    async def generate(
        self,
        context: HubContext,
        changed_files: list[Path] | None,
    ) -> GenerationResult:
        # Analyze git commits
        commits = await self._get_recent_commits()

        # Group by type (feat, fix, docs, etc.)
        grouped = self._group_by_type(commits)

        # Generate changelog entries
        entries = await self._generate_entries(grouped, context)

        # Write CHANGELOG.md
        ...
```

Register in configuration:

```yaml
swarm:
  documentation:
    agents:
      # ... built-in agents ...

      - name: changelog
        type: custom
        module: myproject.agents.ChangelogAgent
        output: ./
```

---

## Related Concepts

- [Feature Assembly Line](./FEATURE_ASSEMBLY_LINE_CONCEPT.md) - Pipeline pattern for feature implementation
- [Continuous Health](./CONTINUOUS_HEALTH_CONCEPT.md) - Background monitoring agents
- [Domain Bootstrap](./DOMAIN_BOOTSTRAP_CONCEPT.md) - Framework-specific code generation
