# Feature Implementation Assembly Line

> **Status**: Concept
> **Category**: Multi-Agent Pattern
> **Use Case**: Structured feature development through specialized agents

---

## User Guide

### What Is This?

The Feature Assembly Line is a **pipeline pattern** where multiple specialized agents collaborate to implement a feature. Each agent handles one phase of development:

1. **Spec Agent** - Breaks down requirements into structured specs
2. **Interface Agent** - Designs types, signatures, and contracts
3. **Implementation Agent** - Writes the actual code
4. **Test Agent** - Creates tests against the interface
5. **Docs Agent** - Documents the completed feature

The key insight: **Interface-first design enables parallelism**. Once the interface is defined, implementation and tests can proceed simultaneously.

### Why Should I Care?

| Traditional Development | Assembly Line |
|------------------------|---------------|
| One person context-switches between tasks | Specialized agents stay focused |
| Tests written after implementation | Tests and implementation written in parallel |
| Documentation is an afterthought | Docs generated as part of the pipeline |
| Interface evolves during implementation | Interface locked before coding starts |
| Inconsistent patterns across features | Agents trained on your patterns |

### Example: Adding Rate Limiting

```bash
$ remora feature "Add rate limiting to the API - 100 requests/minute per IP, return 429 with Retry-After header"

[spec-agent] Analyzing requirements...
[spec-agent] Generated: .remora/features/rate-limiting/spec.yaml

[interface-agent] Designing interface...
[interface-agent] Generated:
  - src/middleware/rate_limit.py (signatures only)
  - src/config/rate_limit.py (RateLimitConfig model)

[impl-agent] Implementing rate_limit.py...
[test-agent] Writing tests against interface... (parallel)

[impl-agent] Completed: src/middleware/rate_limit.py
[test-agent] Completed: tests/test_rate_limit.py

[validation] Running tests...
[validation] 5/5 tests passed

[docs-agent] Updating documentation...
[docs-agent] Updated: docs/middleware.md, CHANGELOG.md

Feature complete: rate-limiting
  Files created: 3
  Files modified: 2
  Tests: 5 passing
```

### The Pipeline Stages

#### Stage 1: Specification

The Spec Agent analyzes your request and produces structured requirements:

```yaml
# .remora/features/rate-limiting/spec.yaml
feature: rate_limiting
description: Limit API requests per IP address

requirements:
  - id: REQ-001
    description: Limit requests to 100 per minute per IP
    acceptance:
      - Given an IP that has made 100 requests in the last minute
      - When another request arrives
      - Then return 429 Too Many Requests

  - id: REQ-002
    description: Include Retry-After header in 429 responses
    acceptance:
      - Given a rate-limited request
      - When 429 is returned
      - Then Retry-After header contains seconds until reset

  - id: REQ-003
    description: Rate limits are configurable via environment
    acceptance:
      - Given RATE_LIMIT_PER_MINUTE=50 is set
      - When the app starts
      - Then the limit is 50, not default 100

affected_components:
  - src/middleware/  # New middleware
  - src/config/      # Configuration model
  - tests/           # New tests

dependencies:
  - redis  # For distributed rate limiting (optional)
```

#### Stage 2: Interface Design

The Interface Agent creates type definitions and function signatures—**no implementation**:

```python
# src/middleware/rate_limit.py (interface only)

from datetime import timedelta
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.config.rate_limit import RateLimitConfig


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using sliding window algorithm.

    Tracks requests per IP address and returns 429 when limit exceeded.
    """

    def __init__(
        self,
        app,
        config: RateLimitConfig,
        storage: RateLimitStorage | None = None,
    ) -> None:
        """Initialize rate limiter.

        Args:
            app: FastAPI application
            config: Rate limit configuration
            storage: Storage backend (defaults to in-memory)
        """
        ...

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        """Check rate limit and either proceed or return 429.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response from handler, or 429 if rate limited
        """
        ...

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request, handling proxies."""
        ...

    def _build_rate_limit_response(
        self,
        retry_after: timedelta,
    ) -> Response:
        """Build 429 response with Retry-After header."""
        ...
```

```python
# src/config/rate_limit.py

from pydantic_settings import BaseSettings


class RateLimitConfig(BaseSettings):
    """Rate limiting configuration.

    All values can be overridden via environment variables.
    """

    requests_per_minute: int = 100
    """Maximum requests per IP per minute."""

    burst_size: int = 10
    """Allow burst above limit before enforcing."""

    storage_backend: str = "memory"
    """Storage backend: 'memory' or 'redis'."""

    redis_url: str | None = None
    """Redis URL for distributed rate limiting."""

    model_config = {"env_prefix": "RATE_LIMIT_"}
```

#### Stage 3: Parallel Implementation + Testing

With the interface locked, two agents work simultaneously:

**Implementation Agent** fills in the method bodies:
```python
# src/middleware/rate_limit.py (now implemented)

async def dispatch(
    self,
    request: Request,
    call_next,
) -> Response:
    client_ip = self._get_client_ip(request)

    # Check current count
    current = await self._storage.get_count(client_ip)

    if current >= self._config.requests_per_minute:
        retry_after = await self._storage.get_reset_time(client_ip)
        return self._build_rate_limit_response(retry_after)

    # Increment count
    await self._storage.increment(client_ip)

    # Proceed with request
    return await call_next(request)
```

**Test Agent** writes tests against the interface (not implementation):
```python
# tests/test_rate_limit.py

import pytest
from fastapi.testclient import TestClient
from src.middleware.rate_limit import RateLimitMiddleware
from src.config.rate_limit import RateLimitConfig


class TestRateLimitMiddleware:
    """Tests for rate limiting middleware."""

    def test_allows_requests_under_limit(self, client: TestClient):
        """Requests under limit should succeed."""
        for _ in range(50):
            response = client.get("/api/test")
            assert response.status_code == 200

    def test_blocks_requests_over_limit(self, client: TestClient):
        """Requests over limit should return 429."""
        # Exhaust the limit
        for _ in range(100):
            client.get("/api/test")

        # Next request should be blocked
        response = client.get("/api/test")
        assert response.status_code == 429

    def test_includes_retry_after_header(self, client: TestClient):
        """429 responses should include Retry-After header."""
        # Exhaust the limit
        for _ in range(100):
            client.get("/api/test")

        response = client.get("/api/test")
        assert "Retry-After" in response.headers
        assert int(response.headers["Retry-After"]) > 0

    def test_respects_config_override(self):
        """Config should be overridable via environment."""
        config = RateLimitConfig(requests_per_minute=50)
        assert config.requests_per_minute == 50
```

#### Stage 4: Validation

Tests run automatically. If they fail, the Implementation Agent iterates:

```
[validation] Running tests...
[validation] FAILED: test_includes_retry_after_header
  - Expected header present but was missing

[impl-agent] Analyzing failure...
[impl-agent] Fix: _build_rate_limit_response was not setting header

[impl-agent] Patched: src/middleware/rate_limit.py

[validation] Re-running tests...
[validation] 5/5 tests passed
```

#### Stage 5: Documentation

The Docs Agent updates relevant documentation:

```markdown
# docs/middleware.md (updated section)

## Rate Limiting

The API includes built-in rate limiting to prevent abuse.

### Default Limits

- **100 requests per minute** per IP address
- Configurable via environment variables

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | 100 | Max requests per IP |
| `RATE_LIMIT_BURST_SIZE` | 10 | Burst allowance |
| `RATE_LIMIT_STORAGE_BACKEND` | memory | `memory` or `redis` |

### Response Headers

When rate limited, the API returns:

- Status: `429 Too Many Requests`
- Header: `Retry-After: <seconds>` (time until limit resets)
```

### Configuration

```yaml
# .remora/assembly_line.yaml
assembly_line:
  # Pipeline stages
  stages:
    - name: spec
      agent: spec-agent
      model: functiongemma-spec-v1
      output: .remora/features/{feature_slug}/spec.yaml

    - name: interface
      agent: interface-agent
      model: functiongemma-interface-v1
      depends_on: [spec]

    - name: implementation
      agent: impl-agent
      model: functiongemma-impl-v1
      depends_on: [interface]

    - name: test
      agent: test-agent
      model: functiongemma-test-v1
      depends_on: [interface]  # NOT impl - parallel!

    - name: validate
      type: builtin
      command: pytest
      depends_on: [implementation, test]

    - name: docs
      agent: docs-agent
      model: functiongemma-docs-v1
      depends_on: [validate]

  # Retry policy
  on_test_failure:
    max_retries: 3
    strategy: impl-agent-retry
```

---

## Developer Guide

### Architecture Overview

```
User Request
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Pipeline Controller                       │
│                    (remora/pipeline/controller.py)               │
└─────────────────────────────────────────────────────────────────┘
     │
     │  Stage 1: Spec
     ▼
┌─────────────────┐
│   Spec Agent    │──────► spec.yaml
└─────────────────┘
     │
     │  Stage 2: Interface
     ▼
┌─────────────────┐
│ Interface Agent │──────► *.py (signatures only)
└─────────────────┘
     │
     ├───────────────────┐
     │  Stage 3a         │  Stage 3b (PARALLEL)
     ▼                   ▼
┌─────────────────┐ ┌─────────────────┐
│   Impl Agent    │ │   Test Agent    │
│                 │ │                 │
│ Fills method    │ │ Writes tests    │
│ bodies          │ │ against iface   │
└────────┬────────┘ └────────┬────────┘
         │                   │
         └─────────┬─────────┘
                   │
                   │  Stage 4: Validate
                   ▼
         ┌─────────────────┐
         │   Test Runner   │
         │    (pytest)     │
         └────────┬────────┘
                  │
                  │  if failed: retry impl
                  │  if passed: continue
                  ▼
         ┌─────────────────┐
         │   Docs Agent    │──────► *.md updates
         └─────────────────┘
```

### Core Components

#### PipelineController

```python
# remora/pipeline/controller.py

class PipelineController:
    """Controls the feature implementation pipeline."""

    def __init__(
        self,
        project_root: Path,
        hub_client: HubClient,
        config: PipelineConfig,
    ):
        self.project_root = project_root
        self.hub_client = hub_client
        self.config = config
        self.stages = self._build_stages()

    async def run(
        self,
        request: str,
        feature_slug: str | None = None,
    ) -> PipelineResult:
        """Execute the full pipeline.

        Args:
            request: Natural language feature request
            feature_slug: Optional slug for feature directory

        Returns:
            Complete pipeline results
        """
        # Initialize context
        ctx = PipelineContext(
            request=request,
            feature_slug=feature_slug or self._generate_slug(request),
            project_root=self.project_root,
            hub_context=await self.hub_client.get_full_context(),
        )

        # Execute stages according to dependency graph
        results = {}
        for stage_group in self._topological_order():
            # Run stages in group in parallel
            group_tasks = [
                self._run_stage(stage, ctx, results)
                for stage in stage_group
            ]
            group_results = await asyncio.gather(*group_tasks)

            for stage, result in zip(stage_group, group_results):
                results[stage.name] = result

                # Handle failures
                if result.status == "failed":
                    if stage.name == "validate":
                        # Retry implementation
                        await self._retry_implementation(ctx, results)
                    else:
                        raise PipelineError(f"Stage {stage.name} failed")

        return PipelineResult(
            feature_slug=ctx.feature_slug,
            stages=results,
            files_created=self._collect_files(results),
        )
```

#### Stage Definitions

```python
# remora/pipeline/stages.py

@dataclass
class PipelineStage:
    """A stage in the pipeline."""
    name: str
    agent: Agent | None
    depends_on: list[str]
    config: dict


class SpecStage(PipelineStage):
    """Generates structured specification from request."""

    async def run(
        self,
        ctx: PipelineContext,
        previous_results: dict,
    ) -> StageResult:
        # Use Hub to understand existing architecture
        existing_patterns = ctx.hub_context.get_patterns(
            category="middleware"  # Or inferred from request
        )

        # Generate spec using fine-tuned model
        spec = await self.agent.generate_spec(
            request=ctx.request,
            existing_patterns=existing_patterns,
            project_structure=ctx.hub_context.get_structure(),
        )

        # Write spec file
        spec_path = ctx.feature_dir / "spec.yaml"
        spec_path.write_text(yaml.dump(spec))

        return StageResult(
            status="success",
            outputs={"spec": spec, "spec_path": spec_path},
        )


class InterfaceStage(PipelineStage):
    """Generates type definitions and signatures."""

    async def run(
        self,
        ctx: PipelineContext,
        previous_results: dict,
    ) -> StageResult:
        spec = previous_results["spec"].outputs["spec"]

        # Analyze existing interfaces in codebase
        existing_interfaces = ctx.hub_context.get_nodes(
            node_type="class",
            file_patterns=spec["affected_components"],
        )

        # Generate interfaces
        interfaces = await self.agent.generate_interfaces(
            spec=spec,
            existing_patterns=existing_interfaces,
            style_guide=ctx.hub_context.get_style_patterns(),
        )

        # Write interface files (stubs only)
        files_written = []
        for interface in interfaces:
            path = ctx.project_root / interface.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(interface.stub_code)
            files_written.append(path)

        return StageResult(
            status="success",
            outputs={
                "interfaces": interfaces,
                "files": files_written,
            },
        )


class ImplementationStage(PipelineStage):
    """Fills in implementation details."""

    async def run(
        self,
        ctx: PipelineContext,
        previous_results: dict,
    ) -> StageResult:
        interfaces = previous_results["interface"].outputs["interfaces"]

        implementations = []
        for interface in interfaces:
            # Generate implementation
            impl = await self.agent.implement(
                interface=interface,
                spec=previous_results["spec"].outputs["spec"],
                hub_context=ctx.hub_context,
            )
            implementations.append(impl)

            # Update file with implementation
            path = ctx.project_root / interface.path
            path.write_text(impl.full_code)

        return StageResult(
            status="success",
            outputs={"implementations": implementations},
        )


class TestStage(PipelineStage):
    """Generates tests against interfaces."""

    async def run(
        self,
        ctx: PipelineContext,
        previous_results: dict,
    ) -> StageResult:
        interfaces = previous_results["interface"].outputs["interfaces"]
        spec = previous_results["spec"].outputs["spec"]

        # Generate tests from spec acceptance criteria
        tests = await self.agent.generate_tests(
            interfaces=interfaces,
            acceptance_criteria=spec["requirements"],
            test_patterns=ctx.hub_context.get_test_patterns(),
        )

        # Write test files
        files_written = []
        for test in tests:
            path = ctx.project_root / test.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(test.code)
            files_written.append(path)

        return StageResult(
            status="success",
            outputs={"tests": tests, "files": files_written},
        )
```

#### Parallel Stage Execution

```python
# remora/pipeline/scheduler.py

class StageScheduler:
    """Schedules pipeline stages respecting dependencies."""

    def __init__(self, stages: list[PipelineStage]):
        self.stages = {s.name: s for s in stages}
        self.graph = self._build_dependency_graph()

    def topological_groups(self) -> list[list[PipelineStage]]:
        """Return stages grouped by execution order.

        Stages in the same group can run in parallel.
        """
        groups = []
        remaining = set(self.stages.keys())
        completed = set()

        while remaining:
            # Find stages whose dependencies are all completed
            ready = [
                name for name in remaining
                if all(dep in completed for dep in self.stages[name].depends_on)
            ]

            if not ready:
                raise CyclicDependencyError()

            groups.append([self.stages[name] for name in ready])
            completed.update(ready)
            remaining -= set(ready)

        return groups

    # Example output for our pipeline:
    # [
    #     [SpecStage],           # Group 0: no dependencies
    #     [InterfaceStage],      # Group 1: depends on spec
    #     [ImplStage, TestStage], # Group 2: both depend on interface (PARALLEL)
    #     [ValidateStage],       # Group 3: depends on impl and test
    #     [DocsStage],           # Group 4: depends on validate
    # ]
```

#### Test Failure Recovery

```python
# remora/pipeline/recovery.py

class ImplementationRetryStrategy:
    """Retries implementation when tests fail."""

    def __init__(
        self,
        impl_agent: ImplementationAgent,
        max_retries: int = 3,
    ):
        self.impl_agent = impl_agent
        self.max_retries = max_retries

    async def retry(
        self,
        ctx: PipelineContext,
        test_result: TestResult,
        previous_impl: Implementation,
    ) -> Implementation:
        """Retry implementation based on test failures.

        Args:
            ctx: Pipeline context
            test_result: Failed test results
            previous_impl: Implementation that failed

        Returns:
            New implementation attempt
        """
        for attempt in range(self.max_retries):
            # Analyze failures
            analysis = await self._analyze_failures(
                test_result.failures,
                previous_impl,
            )

            # Generate fix
            fixed_impl = await self.impl_agent.fix(
                implementation=previous_impl,
                failures=analysis,
                attempt=attempt + 1,
            )

            # Re-run tests
            new_result = await self._run_tests(fixed_impl)

            if new_result.all_passed:
                return fixed_impl

            previous_impl = fixed_impl
            test_result = new_result

        raise MaxRetriesExceededError(
            f"Implementation failed after {self.max_retries} attempts"
        )
```

### Interface-First Design Pattern

The key architectural insight: **interfaces are contracts**.

```python
# Why this enables parallelism:

# Interface Agent outputs:
class RateLimitMiddleware:
    async def dispatch(self, request: Request, call_next) -> Response:
        """Check rate limit."""
        ...  # No implementation yet

# Test Agent can write tests against the CONTRACT:
def test_returns_429_when_limited(middleware):
    # This test is valid regardless of HOW dispatch is implemented
    response = middleware.dispatch(request_over_limit, mock_call_next)
    assert response.status_code == 429

# Implementation Agent fills in the HOW:
async def dispatch(self, request: Request, call_next) -> Response:
    # Actual implementation - doesn't affect test validity
    if self._is_rate_limited(request):
        return Response(status_code=429)
    return await call_next(request)
```

### Hub Integration

The pipeline uses Hub context throughout:

```python
# remora/pipeline/context.py

class PipelineContext:
    """Context available to all pipeline stages."""

    def __init__(
        self,
        request: str,
        feature_slug: str,
        project_root: Path,
        hub_context: HubContext,
    ):
        self.request = request
        self.feature_slug = feature_slug
        self.project_root = project_root
        self.hub_context = hub_context

        # Feature working directory
        self.feature_dir = project_root / ".remora" / "features" / feature_slug
        self.feature_dir.mkdir(parents=True, exist_ok=True)


class HubContext:
    """Rich context from Node State Hub."""

    def get_patterns(self, category: str) -> list[Pattern]:
        """Find existing patterns in category."""
        # Uses Hub's cross-file analysis
        ...

    def get_style_patterns(self) -> StyleGuide:
        """Infer style guide from existing code."""
        # Analyzes naming, docstring style, etc.
        ...

    def get_test_patterns(self) -> TestPatterns:
        """Find testing conventions used in project."""
        # Looks at existing test files
        ...

    def get_structure(self) -> ProjectStructure:
        """Get project directory structure."""
        ...
```

### Fine-Tuning Data

Each agent is fine-tuned on different data:

```python
# Spec Agent: (request, structured_spec) pairs
{
    "input": "Add rate limiting to the API",
    "output": {
        "feature": "rate_limiting",
        "requirements": [...],
        "affected_components": [...],
    }
}

# Interface Agent: (spec, interface_code) pairs
{
    "input": {
        "spec": {...},
        "existing_patterns": ["BaseHTTPMiddleware pattern"],
    },
    "output": {
        "path": "src/middleware/rate_limit.py",
        "stub_code": "class RateLimitMiddleware:\n    async def dispatch(...):\n        ..."
    }
}

# Implementation Agent: (interface + spec, implementation) pairs
{
    "input": {
        "interface": "async def dispatch(self, request, call_next) -> Response: ...",
        "spec_requirement": "Return 429 when limit exceeded",
    },
    "output": "async def dispatch(self, request, call_next) -> Response:\n    if self._is_limited(request):\n        return Response(status_code=429)\n    ..."
}

# Test Agent: (interface + acceptance_criteria, test_code) pairs
{
    "input": {
        "interface": "async def dispatch(...) -> Response",
        "acceptance": "When limit exceeded, return 429",
    },
    "output": "def test_returns_429_when_limited():\n    response = middleware.dispatch(request_over_limit)\n    assert response.status_code == 429"
}
```

---

## Related Concepts

- [Swarm Documentation](./SWARM_DOCUMENTATION_CONCEPT.md) - Parallel documentation generation
- [Continuous Health](./CONTINUOUS_HEALTH_CONCEPT.md) - Background code quality monitoring
- [Domain Bootstrap](./DOMAIN_BOOTSTRAP_CONCEPT.md) - Framework-specific scaffolding
