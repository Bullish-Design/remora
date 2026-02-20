# Continuous Codebase Health

> **Status**: Concept
> **Category**: Background Agent Pattern
> **Use Case**: Always-on code quality monitoring and alerting

---

## User Guide

### What Is This?

Continuous Codebase Health runs **background agents** that monitor your codebase in real-time. Unlike traditional linters that run on-demand, these agents:

- React to file changes as they happen
- Provide context-aware analysis using Hub data
- Track trends over time (not just point-in-time checks)
- Surface issues through IDE integration (LSP diagnostics)

Think of it as having a team of specialized reviewers watching your code 24/7.

### Why Should I Care?

| Traditional Approach | Continuous Health |
|---------------------|-------------------|
| Run linter manually or in CI | Issues surface as you type |
| No historical context | Tracks trends ("complexity increased 20% this month") |
| Generic rules for all code | Context-aware (knows about callers, tests, patterns) |
| Find issues after commit | Find issues before commit |
| One-size-fits-all analysis | Multiple specialized agents |

### The Health Agents

#### Staleness Agent
Detects outdated dependencies and patterns:
- **Dependencies**: "requests 2.25.0 is 2 years old, 2.31.0 available"
- **Deprecated APIs**: "Using `datetime.utcnow()` which is deprecated in 3.12"
- **Abandoned patterns**: "This uses the old auth middleware, 47 files have migrated"

#### Drift Agent
Catches deviation from coding standards:
- **Style drift**: "This file uses snake_case but 95% of codebase uses camelCase"
- **Pattern drift**: "This endpoint doesn't use the standard response format"
- **Architecture drift**: "Service layer importing from API layer (should be reversed)"

#### Complexity Agent
Monitors code complexity:
- **Function complexity**: "process_order() has cyclomatic complexity 25 (threshold: 15)"
- **Class size**: "UserService has 45 methods (threshold: 20)"
- **Coupling**: "This module imports from 23 other modules"

#### Coverage Agent
Tracks test coverage:
- **Missing tests**: "validate_email() has no test coverage"
- **Coverage drops**: "Coverage for auth/ dropped from 85% to 72%"
- **Flaky tests**: "test_payment_flow has failed 3 times this week"

### What You See

#### IDE Diagnostics (Squiggly Lines)

```python
def process_order(order: dict) -> dict:  # ⚠️ Complexity: 18 (threshold: 15)
    """Process an order."""
    if order["type"] == "retail":      # ℹ️ Consider extracting to _process_retail()
        ...
```

#### Status Dashboard

```bash
$ remora health status

Codebase Health Report
======================

Overall Score: 78/100 (Good)

┌────────────────┬────────┬────────────────────────────────┐
│ Agent          │ Status │ Summary                        │
├────────────────┼────────┼────────────────────────────────┤
│ Staleness      │ ⚠️  Warn │ 3 outdated dependencies       │
│ Drift          │ ✅ OK   │ No style violations           │
│ Complexity     │ ⚠️  Warn │ 2 functions above threshold   │
│ Coverage       │ ✅ OK   │ 84% coverage (target: 80%)    │
└────────────────┴────────┴────────────────────────────────┘

Recent Trends:
- Complexity: ↑ 5% this week (watch)
- Coverage: ↓ 2% this week (ok, new untested code)

Top Issues:
1. [COMPLEXITY] src/services/order.py:process_order (18)
2. [STALENESS] requests==2.25.0 (2 years old)
3. [COMPLEXITY] src/api/users.py:create_user (16)
```

#### Notifications

```
[remora-health] ⚠️ Complexity threshold exceeded

File: src/services/payment.py
Function: charge_customer()
Complexity: 22 (threshold: 15)

This function was fine until commit abc123.
Suggested: Extract retry logic to separate function.

[View in IDE] [Dismiss] [Snooze 1 day]
```

### Configuration

```yaml
# .remora/health.yaml
health:
  # Global settings
  enabled: true
  check_interval: 5s  # How often to check changed files

  # Agent configurations
  agents:
    staleness:
      enabled: true
      dependency_age_warning: 365d  # Warn if dep is 1+ year old
      check_deprecated_apis: true
      deprecated_api_sources:
        - python-deprecations  # Built-in database

    drift:
      enabled: true
      style_guide: auto  # Infer from codebase majority
      # Or specify explicit rules:
      # style_guide: .remora/style_guide.yaml
      architecture_rules:
        - name: no-api-in-service
          pattern: "src/services/**/*.py"
          forbidden_imports: ["src.api.*"]
          message: "Services should not import from API layer"

    complexity:
      enabled: true
      thresholds:
        cyclomatic: 15
        cognitive: 20
        class_methods: 20
        module_lines: 500
      ignore_patterns:
        - "**/migrations/**"
        - "**/generated/**"

    coverage:
      enabled: true
      target: 80
      fail_on_decrease: true
      track_flaky: true

  # Output settings
  output:
    lsp: true           # Send to IDE as diagnostics
    dashboard: true     # Enable remora health status
    notifications:
      enabled: true
      channels:
        - type: terminal
        - type: desktop  # System notifications
```

### Silencing Issues

```python
# Silence specific check
def complex_but_necessary():  # noqa: remora-complexity
    ...

# Silence with expiration
def temporary_hack():  # noqa: remora-complexity[expires=2024-06-01]
    ...
```

```yaml
# .remora/health.yaml - global ignores
health:
  ignore:
    - path: "src/legacy/**"
      agents: [complexity, drift]
      reason: "Legacy code, will be removed in Q3"

    - path: "src/generated/**"
      agents: all
      reason: "Auto-generated code"
```

---

## Developer Guide

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Hub Daemon (watchfiles)                      │
│                                                                  │
│   File change detected: src/services/order.py                   │
└─────────────────────────────────────────────────────────────────┘
                    │
                    │ Event broadcast to subscribers
                    │
    ┌───────────────┼───────────────┬───────────────┐
    ▼               ▼               ▼               ▼
┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
│Staleness│   │ Drift  │   │Complex-│   │Coverage│
│ Agent  │    │ Agent  │    │ ity    │    │ Agent  │
│        │    │        │    │ Agent  │    │        │
│FuncGem │    │FuncGem │    │FuncGem │    │FuncGem │
│(tuned) │    │(tuned) │    │(tuned) │    │(tuned) │
└───┬────┘    └───┬────┘    └───┬────┘    └───┬────┘
    │             │             │             │
    ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Findings Store                             │
│                  (FSdantic / VersionedKVRecord)                  │
│                                                                  │
│  key: "finding:{file}:{agent}:{hash}"                           │
│  value: { severity, message, line, suggested_fix, ... }         │
└─────────────────────────────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
┌───────────────┐      ┌───────────────┐
│   LSP Server  │      │   Dashboard   │
│  (diagnostics)│      │   (CLI/Web)   │
└───────────────┘      └───────────────┘
```

### Core Components

#### HealthDaemon

```python
# remora/health/daemon.py

class HealthDaemon:
    """Background daemon running health agents."""

    def __init__(
        self,
        project_root: Path,
        hub_client: HubClient,
        config: HealthConfig,
    ):
        self.project_root = project_root
        self.hub_client = hub_client
        self.config = config
        self.agents = self._initialize_agents()
        self.findings_store = FindingsStore(project_root)

    async def run(self) -> None:
        """Main daemon loop."""
        # Subscribe to Hub file change events
        async for event in self.hub_client.subscribe_changes():
            await self._handle_change(event)

    async def _handle_change(self, event: FileChangeEvent) -> None:
        """Process a file change through all agents."""
        file_path = event.file_path

        # Skip ignored paths
        if self._is_ignored(file_path):
            return

        # Get Hub context for this file
        context = await self.hub_client.get_context_for_file(file_path)

        # Run all agents in parallel
        tasks = [
            agent.analyze(file_path, context)
            for agent in self.agents
            if agent.applies_to(file_path)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Store findings
        for agent, result in zip(self.agents, results):
            if isinstance(result, Exception):
                logger.error(f"Agent {agent.name} failed: {result}")
                continue

            await self._store_findings(agent, file_path, result)

        # Notify subscribers (LSP, dashboard)
        await self._notify_findings(file_path)
```

#### HealthAgent Base Class

```python
# remora/health/agents/base.py

class HealthAgent(ABC):
    """Base class for health monitoring agents."""

    name: str
    severity_default: Severity = Severity.WARNING

    def __init__(
        self,
        model: FunctionGemmaModel,
        config: dict,
    ):
        self.model = model
        self.config = config

    @abstractmethod
    async def analyze(
        self,
        file_path: Path,
        context: HubContext,
    ) -> list[Finding]:
        """Analyze a file and return findings.

        Args:
            file_path: Path to file that changed
            context: Hub context with metadata

        Returns:
            List of findings (issues, warnings, info)
        """
        ...

    def applies_to(self, file_path: Path) -> bool:
        """Check if this agent should analyze this file."""
        # Default: analyze all Python files
        return file_path.suffix == ".py"


@dataclass
class Finding:
    """A health issue found by an agent."""

    agent: str
    file_path: str
    line: int
    column: int
    severity: Severity  # error, warning, info, hint
    code: str           # e.g., "complexity-exceeded"
    message: str
    suggested_fix: str | None = None
    context: dict | None = None  # Additional data
```

#### Complexity Agent

```python
# remora/health/agents/complexity.py

class ComplexityAgent(HealthAgent):
    """Monitors code complexity metrics."""

    name = "complexity"

    async def analyze(
        self,
        file_path: Path,
        context: HubContext,
    ) -> list[Finding]:
        findings = []

        # Get nodes in this file from Hub
        nodes = context.get_nodes_in_file(file_path)

        for node in nodes:
            # Check cyclomatic complexity
            if node.complexity and node.complexity > self.config["thresholds"]["cyclomatic"]:
                findings.append(Finding(
                    agent=self.name,
                    file_path=str(file_path),
                    line=node.line_start,
                    column=0,
                    severity=Severity.WARNING,
                    code="complexity-exceeded",
                    message=f"{node.node_name}() has complexity {node.complexity} (threshold: {self.config['thresholds']['cyclomatic']})",
                    suggested_fix=await self._suggest_refactoring(node, context),
                ))

            # Check method count for classes
            if node.node_type == "class":
                method_count = len(context.get_methods(node.key))
                threshold = self.config["thresholds"]["class_methods"]

                if method_count > threshold:
                    findings.append(Finding(
                        agent=self.name,
                        file_path=str(file_path),
                        line=node.line_start,
                        column=0,
                        severity=Severity.WARNING,
                        code="class-too-large",
                        message=f"{node.node_name} has {method_count} methods (threshold: {threshold})",
                        suggested_fix="Consider splitting into smaller classes",
                    ))

        return findings

    async def _suggest_refactoring(
        self,
        node: NodeState,
        context: HubContext,
    ) -> str | None:
        """Use model to suggest refactoring."""
        # Fine-tuned model generates refactoring suggestions
        prompt = self._build_refactoring_prompt(node, context)
        result = await self.model.generate(prompt)
        return result.suggested_fix
```

#### Drift Agent

```python
# remora/health/agents/drift.py

class DriftAgent(HealthAgent):
    """Detects deviation from codebase patterns."""

    name = "drift"

    async def analyze(
        self,
        file_path: Path,
        context: HubContext,
    ) -> list[Finding]:
        findings = []

        # Get codebase-wide patterns from Hub
        patterns = context.get_codebase_patterns()

        # Check style drift
        style_findings = await self._check_style_drift(file_path, patterns)
        findings.extend(style_findings)

        # Check architecture drift
        arch_findings = await self._check_architecture_drift(file_path, context)
        findings.extend(arch_findings)

        # Check pattern drift (e.g., not using standard patterns)
        pattern_findings = await self._check_pattern_drift(file_path, context)
        findings.extend(pattern_findings)

        return findings

    async def _check_architecture_drift(
        self,
        file_path: Path,
        context: HubContext,
    ) -> list[Finding]:
        """Check for architectural violations."""
        findings = []

        for rule in self.config.get("architecture_rules", []):
            if not fnmatch(str(file_path), rule["pattern"]):
                continue

            # Get imports in this file
            node = context.get_file_node(file_path)
            imports = node.imports or []

            for forbidden in rule["forbidden_imports"]:
                for imp in imports:
                    if fnmatch(imp, forbidden):
                        findings.append(Finding(
                            agent=self.name,
                            file_path=str(file_path),
                            line=1,  # Could track import line
                            column=0,
                            severity=Severity.ERROR,
                            code="architecture-violation",
                            message=rule["message"],
                            context={"import": imp, "rule": rule["name"]},
                        ))

        return findings

    async def _check_pattern_drift(
        self,
        file_path: Path,
        context: HubContext,
    ) -> list[Finding]:
        """Check if file uses non-standard patterns."""
        findings = []

        # Example: Check if API endpoints follow standard response format
        nodes = context.get_nodes_in_file(file_path)

        for node in nodes:
            if self._is_api_endpoint(node):
                # Use model to check pattern compliance
                compliance = await self.model.check_pattern_compliance(
                    node_source=node.source,
                    standard_patterns=context.get_patterns("api_response"),
                )

                if not compliance.is_compliant:
                    findings.append(Finding(
                        agent=self.name,
                        file_path=str(file_path),
                        line=node.line_start,
                        column=0,
                        severity=Severity.INFO,
                        code="pattern-drift",
                        message=f"This endpoint doesn't follow standard response format",
                        suggested_fix=compliance.suggested_fix,
                    ))

        return findings
```

#### Staleness Agent

```python
# remora/health/agents/staleness.py

class StalenessAgent(HealthAgent):
    """Detects outdated dependencies and deprecated APIs."""

    name = "staleness"

    async def analyze(
        self,
        file_path: Path,
        context: HubContext,
    ) -> list[Finding]:
        findings = []

        # Check deprecated API usage
        deprecated_findings = await self._check_deprecated_apis(file_path, context)
        findings.extend(deprecated_findings)

        # Check abandoned patterns (code that hasn't migrated)
        abandoned_findings = await self._check_abandoned_patterns(file_path, context)
        findings.extend(abandoned_findings)

        return findings

    async def check_dependencies(self) -> list[Finding]:
        """Check project dependencies for staleness.

        Called separately (not per-file) on schedule.
        """
        findings = []

        # Read requirements/pyproject.toml
        deps = await self._parse_dependencies()

        for dep in deps:
            age = await self._get_dependency_age(dep)
            latest = await self._get_latest_version(dep)

            if age.days > self.config["dependency_age_warning"]:
                findings.append(Finding(
                    agent=self.name,
                    file_path="pyproject.toml",  # or requirements.txt
                    line=dep.line,
                    column=0,
                    severity=Severity.WARNING,
                    code="outdated-dependency",
                    message=f"{dep.name}=={dep.version} is {age.days} days old. Latest: {latest}",
                    suggested_fix=f"Upgrade to {dep.name}=={latest}",
                ))

        return findings

    async def _check_deprecated_apis(
        self,
        file_path: Path,
        context: HubContext,
    ) -> list[Finding]:
        """Check for deprecated API usage."""
        findings = []

        # Load deprecation database
        deprecations = await self._load_deprecation_db()

        # Get AST/source for file
        source = file_path.read_text()

        for deprecation in deprecations:
            matches = deprecation.find_in_source(source)

            for match in matches:
                findings.append(Finding(
                    agent=self.name,
                    file_path=str(file_path),
                    line=match.line,
                    column=match.column,
                    severity=Severity.WARNING,
                    code="deprecated-api",
                    message=f"`{deprecation.old_api}` is deprecated since Python {deprecation.since}",
                    suggested_fix=f"Use `{deprecation.replacement}` instead",
                ))

        return findings
```

#### Coverage Agent

```python
# remora/health/agents/coverage.py

class CoverageAgent(HealthAgent):
    """Monitors test coverage."""

    name = "coverage"

    async def analyze(
        self,
        file_path: Path,
        context: HubContext,
    ) -> list[Finding]:
        findings = []

        nodes = context.get_nodes_in_file(file_path)

        for node in nodes:
            if node.node_type == "function":
                # Check if this function has tests (from Hub)
                related_tests = node.related_tests or []

                if not related_tests:
                    findings.append(Finding(
                        agent=self.name,
                        file_path=str(file_path),
                        line=node.line_start,
                        column=0,
                        severity=Severity.INFO,
                        code="no-test-coverage",
                        message=f"{node.node_name}() has no test coverage",
                        context={"callers": node.callers},
                    ))

        return findings

    async def check_coverage_trend(self) -> list[Finding]:
        """Check coverage trends over time.

        Called separately on schedule.
        """
        findings = []

        # Get historical coverage data
        history = await self._load_coverage_history()

        if len(history) < 2:
            return findings

        current = history[-1]
        previous = history[-2]

        change = current.percentage - previous.percentage

        if change < -self.config.get("fail_on_decrease_threshold", 5):
            findings.append(Finding(
                agent=self.name,
                file_path="<project>",
                line=0,
                column=0,
                severity=Severity.WARNING,
                code="coverage-decreased",
                message=f"Coverage dropped from {previous.percentage}% to {current.percentage}%",
                context={
                    "previous": previous.percentage,
                    "current": current.percentage,
                    "changed_files": current.changed_files,
                },
            ))

        return findings
```

### Findings Store

```python
# remora/health/store.py

class FindingsStore:
    """Stores health findings with history."""

    def __init__(self, project_root: Path):
        self.workspace = Fsdantic.open(
            path=str(project_root / ".remora" / "health.db")
        )
        self.repo = self.workspace.kv.repository(
            prefix="finding:",
            model_type=StoredFinding,
        )

    async def store(
        self,
        findings: list[Finding],
        file_path: Path,
    ) -> None:
        """Store findings for a file, replacing old ones."""
        # Clear old findings for this file
        await self._clear_file_findings(file_path)

        # Store new findings
        for finding in findings:
            key = self._make_key(finding)
            record = StoredFinding(
                key=key,
                **finding.__dict__,
                timestamp=datetime.now(timezone.utc),
            )
            await self.repo.save(key, record)

    async def get_all_findings(self) -> list[StoredFinding]:
        """Get all current findings."""
        return await self.repo.list_all()

    async def get_findings_for_file(
        self,
        file_path: Path,
    ) -> list[StoredFinding]:
        """Get findings for a specific file."""
        all_findings = await self.get_all_findings()
        return [f for f in all_findings if f.file_path == str(file_path)]

    async def get_trend(
        self,
        days: int = 30,
    ) -> list[TrendPoint]:
        """Get findings trend over time."""
        # Query historical data
        ...
```

### LSP Integration

```python
# remora/health/lsp.py

class HealthLSPProvider:
    """Provides LSP diagnostics from health findings."""

    def __init__(self, findings_store: FindingsStore):
        self.findings_store = findings_store

    async def get_diagnostics(
        self,
        file_uri: str,
    ) -> list[Diagnostic]:
        """Get LSP diagnostics for a file."""
        file_path = Path(uri_to_path(file_uri))
        findings = await self.findings_store.get_findings_for_file(file_path)

        return [
            Diagnostic(
                range=Range(
                    start=Position(line=f.line - 1, character=f.column),
                    end=Position(line=f.line - 1, character=f.column + 1),
                ),
                severity=self._map_severity(f.severity),
                code=f.code,
                source=f"remora-health/{f.agent}",
                message=f.message,
                data={
                    "suggested_fix": f.suggested_fix,
                    "context": f.context,
                },
            )
            for f in findings
        ]

    def _map_severity(self, severity: Severity) -> DiagnosticSeverity:
        return {
            Severity.ERROR: DiagnosticSeverity.Error,
            Severity.WARNING: DiagnosticSeverity.Warning,
            Severity.INFO: DiagnosticSeverity.Information,
            Severity.HINT: DiagnosticSeverity.Hint,
        }[severity]
```

### Trend Tracking

```python
# remora/health/trends.py

class TrendTracker:
    """Tracks health metrics over time."""

    def __init__(self, store: FindingsStore):
        self.store = store

    async def record_snapshot(self) -> None:
        """Record current state for trend analysis."""
        findings = await self.store.get_all_findings()

        snapshot = HealthSnapshot(
            timestamp=datetime.now(timezone.utc),
            total_findings=len(findings),
            by_agent={
                agent: len([f for f in findings if f.agent == agent])
                for agent in set(f.agent for f in findings)
            },
            by_severity={
                sev.value: len([f for f in findings if f.severity == sev])
                for sev in Severity
            },
        )

        await self.store.save_snapshot(snapshot)

    async def get_trend_data(
        self,
        days: int = 30,
    ) -> TrendData:
        """Get trend data for dashboard."""
        snapshots = await self.store.get_snapshots(days=days)

        return TrendData(
            snapshots=snapshots,
            complexity_trend=self._calculate_trend(snapshots, "complexity"),
            coverage_trend=self._calculate_trend(snapshots, "coverage"),
            overall_health=self._calculate_health_score(snapshots[-1]),
        )
```

---

## Related Concepts

- [Learning Assistant](./LEARNING_ASSISTANT_CONCEPT.md) - Real-time IDE help
- [Swarm Documentation](./SWARM_DOCUMENTATION_CONCEPT.md) - Parallel documentation generation
- [Domain Bootstrap](./DOMAIN_BOOTSTRAP_CONCEPT.md) - Framework-specific code generation
