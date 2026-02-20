# Learning / Onboarding Assistant

> **Status**: Concept
> **Category**: Reactive Agent Pattern
> **Use Case**: Real-time IDE assistance for understanding codebases

---

## User Guide

### What Is This?

The Learning Assistant is a set of **reactive agents** that help developers understand and navigate a codebase in real-time. Unlike documentation (which you have to find and read), these agents:

- Respond to your actions in the IDE (opening files, hovering, selecting code)
- Provide context-aware explanations using Hub cross-file data
- Surface "tribal knowledge" (gotchas, history, design decisions)
- Find similar code patterns elsewhere in the codebase

Think of it as having a senior developer looking over your shoulder, ready to explain anything.

### Why Should I Care?

| Traditional Onboarding | Learning Assistant |
|-----------------------|-------------------|
| Read docs, hope they're current | Explanations generated from live code |
| Ask teammates, interrupt their work | Instant answers, no interruption |
| Search codebase manually for examples | "Show similar code" is one click |
| Learn gotchas the hard way | Warnings from git history and PR comments |
| Context-switch to read external docs | Relevant docs surfaced inline |

### The Assistant Agents

#### Explain Agent
Answers "What does this code do?" in plain language:
- Function-level: "This function validates user input and hashes passwords"
- Block-level: "This loop retries the API call up to 3 times with exponential backoff"
- Architecture-level: "This service handles all payment processing for the checkout flow"

#### Context Agent
Answers "What calls this?" and "What does this depend on?":
- **Callers**: "Called by: CheckoutService.complete(), SubscriptionRenewal.process()"
- **Callees**: "Calls: validate_email(), hash_password(), db.save_user()"
- **Tests**: "Tested by: test_create_user_success(), test_create_user_duplicate_email()"

#### Example Agent
Shows similar patterns in the codebase:
- "5 other functions use this retry pattern"
- "See also: OrderService.create() which has similar validation logic"
- "This follows the Repository pattern used in 12 other places"

#### Gotcha Agent
Warns about known pitfalls:
- "Warning: Don't call this outside a transaction - see PR #234"
- "Note: This returns None on error, not an exception - 3 bugs fixed for this"
- "Historical: This was refactored in v2.0, old docs may reference old API"

### What You See

#### Hover Information

When you hover over a function:

```
┌─────────────────────────────────────────────────────────────────┐
│ process_payment(order: Order, method: PaymentMethod) -> Result │
├─────────────────────────────────────────────────────────────────┤
│ 📖 EXPLANATION                                                  │
│ Processes payment for an order using the specified method.     │
│ Handles retries, fraud detection, and receipt generation.      │
│                                                                 │
│ 🔗 CONTEXT                                                      │
│ Called by: CheckoutService.complete() (2 places)               │
│            SubscriptionRenewal.process()                        │
│ Calls: FraudDetector.check(), PaymentGateway.charge()          │
│ Tests: test_payment_success, test_payment_fraud_detected       │
│                                                                 │
│ 📝 SIMILAR CODE                                                 │
│ → RefundService.process() uses same retry pattern              │
│ → SubscriptionService.charge() has similar flow                 │
│                                                                 │
│ ⚠️  GOTCHAS                                                     │
│ • Must be called within transaction - commits on success       │
│ • PaymentGateway.charge() can take 10+ seconds                 │
│ • See PR #456 for why we don't cache fraud results             │
└─────────────────────────────────────────────────────────────────┘
```

#### CodeLens (Above Functions)

```python
# 🔗 3 callers | 📋 2 tests | 📝 Similar: refund_payment()
def process_payment(order: Order, method: PaymentMethod) -> Result:
    ...
```

#### Command Palette

```
> Remora: Explain Selection
> Remora: Show Callers
> Remora: Show Similar Code
> Remora: Why Was This Written This Way?
> Remora: Show Related Tests
```

#### Side Panel

```
┌─────────────────────────────────────────┐
│ 📚 Learning Assistant                   │
├─────────────────────────────────────────┤
│                                         │
│ Current File: payment_service.py        │
│                                         │
│ ▼ File Overview                         │
│   This module handles payment           │
│   processing for orders and             │
│   subscriptions.                        │
│                                         │
│ ▼ Key Functions                         │
│   • process_payment - Main entry        │
│   • validate_payment - Input checks     │
│   • generate_receipt - Post-process     │
│                                         │
│ ▼ Dependencies                          │
│   → fraud_detector.py                   │
│   → payment_gateway.py                  │
│   → receipt_generator.py                │
│                                         │
│ ▼ Recent Changes                        │
│   • 2024-02-15: Added retry logic       │
│   • 2024-01-20: Fixed currency bug      │
│                                         │
│ ▼ Known Issues                          │
│   ⚠️ TODO: Add idempotency key support  │
│                                         │
└─────────────────────────────────────────┘
```

### Configuration

```yaml
# .remora/assistant.yaml
assistant:
  enabled: true

  agents:
    explain:
      enabled: true
      verbosity: medium  # brief, medium, detailed
      include_examples: true

    context:
      enabled: true
      show_callers: true
      show_callees: true
      show_tests: true
      max_items: 5  # Limit displayed callers/callees

    example:
      enabled: true
      similarity_threshold: 0.7
      max_examples: 3

    gotcha:
      enabled: true
      sources:
        - git_history: true     # Learn from commits/PRs
        - code_comments: true   # # WARNING:, # NOTE:, # HACK:
        - issue_tracker: false  # Requires integration
      severity_filter: [warning, critical]

  # Display settings
  display:
    hover: true
    codelens: true
    side_panel: true
    inline_hints: false  # Experimental

  # Learning sources
  knowledge:
    # Project-specific knowledge file
    tribal_knowledge: .remora/tribal_knowledge.yaml
    # External documentation to index
    external_docs:
      - url: https://docs.pydantic.dev/
        prefix: "pydantic"
      - url: https://fastapi.tiangolo.com/
        prefix: "fastapi"
```

### Adding Tribal Knowledge

```yaml
# .remora/tribal_knowledge.yaml
knowledge:
  - pattern: "PaymentGateway.charge"
    severity: warning
    message: "Can take 10+ seconds, use async and show loading state"
    added_by: "alice@example.com"
    date: "2024-01-15"

  - pattern: "class.*Repository"
    severity: info
    message: "Follow the Repository pattern: all DB access goes through here"
    link: "docs/architecture.md#repository-pattern"

  - file: "src/legacy/**"
    severity: warning
    message: "Legacy code - prefer new implementations in src/v2/"
```

---

## Developer Guide

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        IDE / Editor                              │
│                                                                  │
│   Events: textDocument/didOpen, textDocument/hover, etc.        │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Remora LSP Server                            │
│                                                                  │
│   Receives events, routes to appropriate agent                  │
└─────────────────────────────────────────────────────────────────┘
                    │
    ┌───────────────┼───────────────┬───────────────┐
    ▼               ▼               ▼               ▼
┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
│Explain │    │Context │    │Example │    │ Gotcha │
│ Agent  │    │ Agent  │    │ Agent  │    │ Agent  │
│        │    │        │    │        │    │        │
│FuncGem │    │Hub API │    │Embed-  │    │Git +   │
│(tuned) │    │        │    │dings   │    │Tribal  │
└───┬────┘    └───┬────┘    └───┬────┘    └───┬────┘
    │             │             │             │
    └─────────────┴─────────────┴─────────────┘
                        │
                        ▼
         ┌─────────────────────────────┐
         │        Hub Client           │
         │   (NodeState, cross-refs)   │
         └─────────────────────────────┘
                        │
                        ▼
         ┌─────────────────────────────┐
         │      Embeddings Store       │
         │  (code + docs similarity)   │
         └─────────────────────────────┘
```

### Core Components

#### AssistantLSPServer

```python
# remora/assistant/lsp.py

class AssistantLSPServer:
    """LSP server providing learning assistant features."""

    def __init__(
        self,
        hub_client: HubClient,
        embeddings: EmbeddingsStore,
        config: AssistantConfig,
    ):
        self.hub_client = hub_client
        self.embeddings = embeddings
        self.config = config
        self.agents = self._initialize_agents()

    async def handle_hover(
        self,
        params: HoverParams,
    ) -> Hover | None:
        """Handle hover request - show rich context."""
        file_path = uri_to_path(params.text_document.uri)
        position = params.position

        # Get node at position from Hub
        node = await self._get_node_at_position(file_path, position)

        if not node:
            return None

        # Run all agents in parallel
        tasks = {
            "explain": self.agents["explain"].explain(node),
            "context": self.agents["context"].get_context(node),
            "example": self.agents["example"].find_similar(node),
            "gotcha": self.agents["gotcha"].get_warnings(node),
        }

        results = await asyncio.gather(*tasks.values())
        agent_results = dict(zip(tasks.keys(), results))

        # Format hover content
        content = self._format_hover(node, agent_results)

        return Hover(
            contents=MarkupContent(
                kind=MarkupKind.Markdown,
                value=content,
            ),
            range=self._node_to_range(node),
        )

    async def handle_codelens(
        self,
        params: CodeLensParams,
    ) -> list[CodeLens]:
        """Handle code lens request - show inline hints."""
        file_path = uri_to_path(params.text_document.uri)

        # Get all nodes in file from Hub
        nodes = await self.hub_client.get_nodes_in_file(file_path)

        lenses = []
        for node in nodes:
            if node.node_type in ("function", "class"):
                lens = await self._create_codelens(node)
                lenses.append(lens)

        return lenses

    async def _create_codelens(self, node: NodeState) -> CodeLens:
        """Create CodeLens for a node."""
        # Get quick stats from Hub
        callers = node.callers or []
        tests = node.related_tests or []

        # Find similar code
        similar = await self.agents["example"].find_similar(node, limit=1)

        parts = []
        if callers:
            parts.append(f"🔗 {len(callers)} callers")
        if tests:
            parts.append(f"📋 {len(tests)} tests")
        if similar:
            parts.append(f"📝 Similar: {similar[0].name}")

        return CodeLens(
            range=Range(
                start=Position(line=node.line_start - 1, character=0),
                end=Position(line=node.line_start - 1, character=0),
            ),
            command=Command(
                title=" | ".join(parts) if parts else "No context available",
                command="remora.showContext",
                arguments=[node.key],
            ),
        )
```

#### Explain Agent

```python
# remora/assistant/agents/explain.py

class ExplainAgent:
    """Generates plain-language explanations of code."""

    def __init__(
        self,
        model: FunctionGemmaModel,
        config: dict,
    ):
        self.model = model
        self.config = config

    async def explain(
        self,
        node: NodeState,
        verbosity: str = "medium",
    ) -> Explanation:
        """Generate explanation for a code node.

        Args:
            node: Node to explain
            verbosity: brief, medium, or detailed

        Returns:
            Explanation with summary and details
        """
        prompt = self._build_prompt(node, verbosity)
        result = await self.model.generate(prompt)

        return Explanation(
            summary=result.summary,
            details=result.details if verbosity != "brief" else None,
            examples=result.examples if self.config["include_examples"] else None,
        )

    def _build_prompt(
        self,
        node: NodeState,
        verbosity: str,
    ) -> str:
        """Build prompt for explanation generation."""
        return f"""Explain this Python code in plain language.

Function: {node.signature}
Docstring: {node.docstring or "None"}
Decorators: {', '.join(node.decorators) if node.decorators else "None"}

Verbosity: {verbosity}
- brief: One sentence
- medium: 2-3 sentences with key details
- detailed: Full explanation with edge cases

Generate a clear explanation for a developer unfamiliar with this codebase."""
```

#### Context Agent

```python
# remora/assistant/agents/context.py

class ContextAgent:
    """Provides cross-file context from Hub."""

    def __init__(self, hub_client: HubClient):
        self.hub_client = hub_client

    async def get_context(
        self,
        node: NodeState,
    ) -> NodeContext:
        """Get rich context for a node.

        Uses Hub's pre-computed cross-file analysis.
        """
        # These are already in NodeState from Hub
        callers = node.callers or []
        callees = node.callees or []
        tests = node.related_tests or []

        # Enrich with details
        caller_details = await self._get_node_details(callers)
        callee_details = await self._get_node_details(callees)
        test_details = await self._get_node_details(tests)

        return NodeContext(
            callers=caller_details,
            callees=callee_details,
            tests=test_details,
            # Compute depth metrics
            call_depth=await self._compute_call_depth(node),
            test_coverage=len(tests) > 0,
        )

    async def _get_node_details(
        self,
        keys: list[str],
    ) -> list[NodeSummary]:
        """Get summary details for node keys."""
        nodes = await self.hub_client.get_context(keys)

        return [
            NodeSummary(
                key=key,
                name=node.node_name,
                file=node.file_path,
                signature=node.signature,
                docstring=node.docstring,
            )
            for key, node in nodes.items()
            if node
        ]
```

#### Example Agent

```python
# remora/assistant/agents/example.py

class ExampleAgent:
    """Finds similar code patterns in the codebase."""

    def __init__(
        self,
        embeddings: EmbeddingsStore,
        hub_client: HubClient,
        config: dict,
    ):
        self.embeddings = embeddings
        self.hub_client = hub_client
        self.config = config

    async def find_similar(
        self,
        node: NodeState,
        limit: int = 3,
    ) -> list[SimilarCode]:
        """Find similar code patterns.

        Args:
            node: Node to find similar code for
            limit: Maximum results to return

        Returns:
            List of similar code with similarity scores
        """
        # Get embedding for this node's source
        embedding = await self.embeddings.embed_code(node.source)

        # Search for similar
        results = await self.embeddings.search(
            embedding,
            limit=limit + 1,  # +1 to exclude self
            threshold=self.config["similarity_threshold"],
        )

        # Filter out self and enrich with Hub data
        similar = []
        for result in results:
            if result.key == node.key:
                continue

            node_state = await self.hub_client.get(result.key)
            if node_state:
                similar.append(SimilarCode(
                    key=result.key,
                    name=node_state.node_name,
                    file=node_state.file_path,
                    similarity=result.score,
                    signature=node_state.signature,
                    why_similar=await self._explain_similarity(node, node_state),
                ))

            if len(similar) >= limit:
                break

        return similar

    async def _explain_similarity(
        self,
        source: NodeState,
        target: NodeState,
    ) -> str:
        """Generate explanation of why code is similar."""
        # Use model to explain the similarity
        prompt = f"""Explain why these two functions are similar in one sentence:

Function 1: {source.signature}
Function 2: {target.signature}

Focus on patterns, not implementation details."""

        result = await self.model.generate(prompt)
        return result.explanation
```

#### Gotcha Agent

```python
# remora/assistant/agents/gotcha.py

class GotchaAgent:
    """Surfaces warnings and tribal knowledge."""

    def __init__(
        self,
        git_analyzer: GitAnalyzer,
        knowledge_store: KnowledgeStore,
        config: dict,
    ):
        self.git = git_analyzer
        self.knowledge = knowledge_store
        self.config = config

    async def get_warnings(
        self,
        node: NodeState,
    ) -> list[Gotcha]:
        """Get warnings and gotchas for a node.

        Sources:
        - Tribal knowledge file
        - Git commit messages / PR descriptions
        - Code comments (TODO, FIXME, WARNING)
        - Bug fix history
        """
        gotchas = []

        # 1. Check tribal knowledge
        if self.config["sources"].get("tribal_knowledge"):
            tribal = await self._check_tribal_knowledge(node)
            gotchas.extend(tribal)

        # 2. Check git history
        if self.config["sources"].get("git_history"):
            git_gotchas = await self._check_git_history(node)
            gotchas.extend(git_gotchas)

        # 3. Check code comments
        if self.config["sources"].get("code_comments"):
            comment_gotchas = await self._check_code_comments(node)
            gotchas.extend(comment_gotchas)

        # Filter by severity
        severity_filter = self.config.get("severity_filter", ["warning", "critical"])
        gotchas = [g for g in gotchas if g.severity in severity_filter]

        return gotchas

    async def _check_tribal_knowledge(
        self,
        node: NodeState,
    ) -> list[Gotcha]:
        """Check against tribal knowledge file."""
        gotchas = []

        for entry in self.knowledge.entries:
            if self._matches(entry, node):
                gotchas.append(Gotcha(
                    severity=entry.severity,
                    message=entry.message,
                    source="tribal_knowledge",
                    link=entry.link,
                    added_by=entry.added_by,
                ))

        return gotchas

    async def _check_git_history(
        self,
        node: NodeState,
    ) -> list[Gotcha]:
        """Extract warnings from git history."""
        gotchas = []

        # Get commits that touched this function
        commits = await self.git.get_commits_for_function(
            node.file_path,
            node.node_name,
            limit=50,
        )

        for commit in commits:
            # Look for bug fix indicators
            if self._is_bug_fix(commit):
                gotchas.append(Gotcha(
                    severity="info",
                    message=f"Bug fixed: {commit.summary}",
                    source="git_history",
                    link=commit.url,
                    date=commit.date,
                ))

            # Look for warnings in commit messages
            warnings = self._extract_warnings(commit.message)
            for warning in warnings:
                gotchas.append(Gotcha(
                    severity="warning",
                    message=warning,
                    source="git_history",
                    link=commit.url,
                ))

        return gotchas

    async def _check_code_comments(
        self,
        node: NodeState,
    ) -> list[Gotcha]:
        """Extract warnings from code comments."""
        gotchas = []
        source = node.source or ""

        patterns = [
            (r"#\s*WARNING:?\s*(.+)", "warning"),
            (r"#\s*HACK:?\s*(.+)", "warning"),
            (r"#\s*FIXME:?\s*(.+)", "info"),
            (r"#\s*TODO:?\s*(.+)", "info"),
            (r"#\s*NOTE:?\s*(.+)", "info"),
        ]

        for pattern, severity in patterns:
            for match in re.finditer(pattern, source, re.IGNORECASE):
                gotchas.append(Gotcha(
                    severity=severity,
                    message=match.group(1).strip(),
                    source="code_comment",
                    line=self._get_line_number(source, match.start()),
                ))

        return gotchas
```

### Embeddings Store

```python
# remora/assistant/embeddings.py

class EmbeddingsStore:
    """Stores and searches code embeddings."""

    def __init__(
        self,
        project_root: Path,
        model: EmbeddingModel,
    ):
        self.project_root = project_root
        self.model = model
        self.db_path = project_root / ".remora" / "embeddings.db"
        self._db = self._open_db()

    async def embed_code(self, source: str) -> list[float]:
        """Generate embedding for code snippet."""
        return await self.model.embed(source)

    async def index_node(self, node: NodeState) -> None:
        """Index a node for similarity search."""
        embedding = await self.embed_code(node.source)

        await self._db.upsert(
            key=node.key,
            embedding=embedding,
            metadata={
                "file": node.file_path,
                "name": node.node_name,
                "type": node.node_type,
            },
        )

    async def search(
        self,
        embedding: list[float],
        limit: int = 10,
        threshold: float = 0.7,
    ) -> list[SearchResult]:
        """Search for similar code by embedding."""
        results = await self._db.search(
            embedding=embedding,
            limit=limit,
        )

        return [
            SearchResult(key=r.key, score=r.score, metadata=r.metadata)
            for r in results
            if r.score >= threshold
        ]

    async def index_external_docs(
        self,
        url: str,
        prefix: str,
    ) -> None:
        """Index external documentation for context."""
        # Fetch and parse documentation
        docs = await self._fetch_docs(url)

        for doc in docs:
            embedding = await self.model.embed(doc.content)

            await self._db.upsert(
                key=f"doc:{prefix}:{doc.path}",
                embedding=embedding,
                metadata={
                    "type": "external_doc",
                    "source": url,
                    "title": doc.title,
                    "content_preview": doc.content[:200],
                },
            )
```

### Knowledge Store

```python
# remora/assistant/knowledge.py

class KnowledgeStore:
    """Manages tribal knowledge."""

    def __init__(self, knowledge_file: Path):
        self.knowledge_file = knowledge_file
        self.entries = self._load_entries()

    def _load_entries(self) -> list[KnowledgeEntry]:
        """Load entries from YAML file."""
        if not self.knowledge_file.exists():
            return []

        data = yaml.safe_load(self.knowledge_file.read_text())
        return [KnowledgeEntry(**e) for e in data.get("knowledge", [])]

    def add_entry(
        self,
        pattern: str,
        message: str,
        severity: str = "info",
        added_by: str | None = None,
    ) -> None:
        """Add a new knowledge entry."""
        entry = KnowledgeEntry(
            pattern=pattern,
            message=message,
            severity=severity,
            added_by=added_by,
            date=datetime.now().isoformat(),
        )

        self.entries.append(entry)
        self._save_entries()

    def matches(
        self,
        entry: KnowledgeEntry,
        node: NodeState,
    ) -> bool:
        """Check if entry matches a node."""
        # Check file pattern
        if entry.file:
            if not fnmatch(node.file_path, entry.file):
                return False

        # Check code pattern
        if entry.pattern:
            if entry.pattern not in (node.signature or ""):
                if entry.pattern not in (node.source or ""):
                    return False

        return True


@dataclass
class KnowledgeEntry:
    """A piece of tribal knowledge."""
    message: str
    severity: str = "info"
    pattern: str | None = None
    file: str | None = None
    link: str | None = None
    added_by: str | None = None
    date: str | None = None
```

### Git Analyzer

```python
# remora/assistant/git.py

class GitAnalyzer:
    """Analyzes git history for context."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    async def get_commits_for_function(
        self,
        file_path: str,
        function_name: str,
        limit: int = 50,
    ) -> list[Commit]:
        """Get commits that modified a specific function."""
        # Use git log with function context
        cmd = [
            "git", "log",
            f"-L:^{function_name}:{file_path}",
            f"-{limit}",
            "--format=%H|%s|%an|%ad|%b|||",
        ]

        result = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.repo_path,
            stdout=asyncio.subprocess.PIPE,
        )
        output, _ = await result.communicate()

        return self._parse_commits(output.decode())

    def _is_bug_fix(self, commit: Commit) -> bool:
        """Check if commit is a bug fix."""
        indicators = ["fix", "bug", "issue", "resolve", "patch"]
        message_lower = commit.message.lower()
        return any(ind in message_lower for ind in indicators)

    def _extract_warnings(self, message: str) -> list[str]:
        """Extract warning patterns from commit message."""
        warnings = []

        patterns = [
            r"(?:warning|caution|note|important):?\s*(.+)",
            r"don'?t\s+(.+)",
            r"make sure (?:to\s+)?(.+)",
            r"be careful (?:to\s+)?(.+)",
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, message, re.IGNORECASE):
                warnings.append(match.group(1).strip())

        return warnings
```

---

## Related Concepts

- [Continuous Health](./CONTINUOUS_HEALTH_CONCEPT.md) - Background code quality monitoring
- [Domain Bootstrap](./DOMAIN_BOOTSTRAP_CONCEPT.md) - Framework-specific code generation
- [Swarm Documentation](./SWARM_DOCUMENTATION_CONCEPT.md) - Parallel documentation generation
