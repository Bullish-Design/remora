# MVP Demo Concept: Recommendation and Implementation Guide

**Author:** Claude Opus 4.5
**Date:** 2026-02-22
**Status:** Strategic Recommendation

---

## Executive Summary

After a comprehensive review of Remora's codebase and all seven example concepts, this document recommends a focused MVP demo strategy that maximizes **"wow" factor** while remaining achievable with the current infrastructure.

### Recommendation: "Code Evolution Pipeline" Demo

A hybrid approach combining elements from **TREESITTER_AGENT_SWARM_CONCEPT** and **FEATURE_ASSEMBLY_LINE_CONCEPT**, demonstrating:

1. **Visual AST-driven agent coordination** (most impressive element)
2. **Real-time LoRA adapter hot-swapping** (unique vLLM capability)
3. **Sandboxed multi-agent collaboration** (Grail/Cairn showcase)
4. **Live streaming dashboard** (engaging presentation)

**Time to MVP:** 4-6 weeks with current infrastructure
**Impact Score:** 9/10 for technical audiences, 8/10 for business audiences

---

## 1. Analysis of Existing Concepts

### 1.1 Concept Scoring Matrix

| Concept | Wow Factor | Feasibility | Unique Differentiator | Business Appeal | Overall |
|---------|------------|-------------|----------------------|-----------------|---------|
| Tree-sitter Agent Swarm | 10 | 4 | 10 | 7 | **7.75** |
| Comprehensive Model Suite | 9 | 3 | 9 | 8 | 7.25 |
| Feature Assembly Line | 8 | 7 | 7 | 9 | **7.75** |
| Swarm Documentation | 7 | 8 | 6 | 8 | 7.25 |
| Continuous Health | 6 | 9 | 5 | 7 | 6.75 |
| Learning Assistant | 7 | 6 | 6 | 6 | 6.25 |
| Domain Bootstrap | 6 | 5 | 7 | 7 | 6.25 |

### 1.2 Key Insights

**TREESITTER_AGENT_SWARM_CONCEPT** (Your Favorite #1)
- *Strengths:* Visually stunning, demonstrates deep compiler mathematics, showcases vLLM batched inference
- *Challenges:* Requires training dozens of node-specific LoRA adapters, complex coordination infrastructure
- *MVP Potential:* **High if scoped down** to 3-4 node types instead of "every AST node"

**COMPREHENSIVE_EMBEDDINGS_MODEL_SUITE** (Your Favorite #2)
- *Strengths:* Complete "Language Pack" distribution story, impressive multi-model orchestration
- *Challenges:* Requires EmbeddingGemma, CodeGemma, T5Gemma, and FunctionGemma trained/fine-tuned
- *MVP Potential:* **Medium** - could demo with mock/base models, but loses impact

**FEATURE_ASSEMBLY_LINE_CONCEPT**
- *Strengths:* Clear business value, understandable workflow, parallel execution visible
- *Challenges:* Requires 5 specialized agents, test validation loop
- *MVP Potential:* **High** - aligns well with existing infrastructure

---

## 2. Recommended MVP: "Code Evolution Pipeline"

### 2.1 Concept Overview

The **Code Evolution Pipeline** demonstrates Remora orchestrating a multi-agent transformation of a codebase in real-time, with visible AST navigation and LoRA adapter swapping.

```
User Request: "Add rate limiting and caching to this API"
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   LIVE DASHBOARD VIEW                            │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  AST VISUALIZATION          ACTIVE AGENTS                   ││
│  │                                                              ││
│  │  📁 api/                    🤖 Architect (planning...)      ││
│  │   └── routes.py             🤖 Implement-1 (waiting)        ││
│  │       ├── 🎯 get_users()    🤖 Implement-2 (waiting)        ││
│  │       ├── ⚙️ create_user()  🤖 Test-Gen (waiting)           ││
│  │       └── 📦 UserRouter     🤖 Lint (waiting)               ││
│  │                                                              ││
│  │  ──────────────────────────────────────────────────────────  ││
│  │  EVENT STREAM                                                ││
│  │  [14:32:01] Architect: Identified 3 endpoints needing rate   ││
│  │  [14:32:02] Architect: LoRA swap → architect-v1              ││
│  │  [14:32:05] Architect: Delegating to Implement-1, Implement-2││
│  │  [14:32:06] Implement-1: LoRA swap → rate-limit-v1           ││
│  │  [14:32:06] Implement-2: LoRA swap → caching-v1              ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Core Demo Features

#### Feature 1: Visual AST Navigation (From Swarm Concept)
- Tree-sitter parses the target codebase
- Real-time visualization of nodes being analyzed
- Agents "claim" nodes and show their activity
- Color-coded status (analyzing, modified, complete)

#### Feature 2: LoRA Adapter Hot-Swapping (Unique Showcase)
- Dashboard shows current adapter for each agent
- Visible swap events: `architect-v1 → implement-v1 → test-gen-v1`
- Demonstrates vLLM's continuous batching capability
- **This is the "wow" moment** - multiple adapters serving simultaneously

#### Feature 3: Parallel Agent Execution (From Assembly Line)
- Architect agent plans the transformation
- Multiple implementation agents work in parallel
- Test generation runs alongside implementation
- Final lint/validation phase

#### Feature 4: Sandboxed Workspaces (Cairn Showcase)
- Each agent operates in isolated workspace
- Changes visible as diffs in real-time
- Final merge step shows transformation result
- Rollback capability demonstrated

### 2.3 Demo Script (5-minute version)

**Setup:** A simple FastAPI application with 3 endpoints, no rate limiting or caching.

**Scene 1: Discovery (30 seconds)**
```
"Remora first discovers the codebase structure using Tree-sitter..."
[Dashboard shows AST tree populating with nodes]
"It identifies 3 API endpoints and their dependencies."
```

**Scene 2: Architecture Planning (45 seconds)**
```
"The Architect agent, powered by our fine-tuned FunctionGemma adapter,
analyzes the request and creates an implementation plan..."
[Event stream shows planning decisions]
"Notice how it identifies which endpoints need rate limiting vs caching."
```

**Scene 3: Parallel Implementation (90 seconds)**
```
"Now watch as multiple agents work simultaneously..."
[Dashboard shows 3 agents activating]
"The vLLM server is hot-swapping LoRA adapters in real-time.
Agent 1 is using rate-limit-v1, Agent 2 is using caching-v1..."
[Code changes appear in diff view]
"Each agent operates in an isolated sandbox - no conflicts."
```

**Scene 4: Test Generation (45 seconds)**
```
"While implementation continues, the test agent generates tests..."
[Test file appearing in separate pane]
"It uses the interface definitions, not the implementation,
allowing true parallel development."
```

**Scene 5: Validation & Merge (30 seconds)**
```
"Finally, all changes are validated and merged..."
[Green checkmarks appear on all nodes]
"The codebase has been safely transformed with full isolation."
```

**Scene 6: Result (30 seconds)**
```
"Let's run the final application..."
[Terminal shows API with rate limiting working]
"Complete transformation in under 2 minutes, fully auditable."
```

---

## 3. Technical Implementation Plan

### 3.1 Required Components

#### Already Implemented (Leverage Existing)
| Component | Location | Readiness |
|-----------|----------|-----------|
| Tree-sitter Discovery | `src/remora/discovery/` | 95% |
| Grail Sandboxed Execution | `agents/*/tools/*.pym` | 80% |
| Cairn Workspace Isolation | Via `structured-agents` | 90% |
| Event Streaming | `src/remora/events.py` | 95% |
| vLLM Client | `src/remora/client.py` | 95% |
| Coordinator | `src/remora/orchestrator.py` | 90% |

#### Needs Implementation
| Component | Effort | Priority |
|-----------|--------|----------|
| Live Dashboard TUI | 2 weeks | Critical |
| Architect Agent Bundle | 1 week | Critical |
| LoRA Swap Visualization | 3 days | High |
| AST Visualization | 1 week | High |
| Rate-Limit Tool | 3 days | Medium |
| Caching Tool | 3 days | Medium |

### 3.2 Agent Bundle Definitions

#### Architect Agent (`agents/architect/`)

```yaml
# bundle.yaml
name: architect
description: Plans multi-step code transformations

model:
  plugin: function_gemma
  adapter: architect-v1  # Fine-tuned for planning

initial_context:
  system_prompt: |
    You are an expert software architect. Analyze the codebase structure
    and create an implementation plan for the requested transformation.

    You have access to the full AST of the project. Your job is to:
    1. Identify which nodes need modification
    2. Determine the order of operations
    3. Assign sub-tasks to specialized agents
    4. Define success criteria

    Output a structured plan using the plan_transformation tool.

tools:
  - name: analyze_ast
    registry: grail
    description: Get AST structure for a file or directory

  - name: plan_transformation
    registry: grail
    description: Submit transformation plan with node assignments

  - name: delegate_to_agent
    registry: grail
    description: Assign a specific task to a specialized agent
```

#### Implementation Agent (`agents/implement/`)

```yaml
# bundle.yaml
name: implement
description: Implements specific code transformations

model:
  plugin: function_gemma
  adapter: implement-v1

initial_context:
  system_prompt: |
    You are a senior Python developer. You receive specific transformation
    tasks from the Architect and implement them precisely.

    Work only on your assigned nodes. Use the workspace for all changes.
    When complete, call submit_implementation with your changes.

tools:
  - name: read_file
    registry: grail

  - name: apply_transformation
    registry: grail
    description: Apply code transformation to a specific AST node

  - name: submit_implementation
    registry: grail
    description: Submit completed implementation for review
```

### 3.3 Dashboard Implementation

The dashboard is critical for demo impact. Use `rich` + `textual` for TUI:

```python
# scripts/remora_demo_dashboard.py

from textual.app import App
from textual.widgets import Tree, DataTable, Log
from textual.containers import Horizontal, Vertical

class DemoDashboard(App):
    """Live demo dashboard showing agent coordination."""

    CSS = """
    #ast-view { width: 40%; }
    #agent-panel { width: 60%; }
    #event-log { height: 30%; }
    """

    def compose(self):
        yield Horizontal(
            Tree("AST", id="ast-view"),
            Vertical(
                DataTable(id="agent-table"),
                Log(id="event-log"),
                id="agent-panel",
            ),
        )

    async def on_remora_event(self, event: dict) -> None:
        """Handle Remora events and update UI."""
        if event["event"] == "LORA_SWAP":
            self.highlight_adapter_swap(event)
        elif event["event"] == "NODE_CLAIMED":
            self.highlight_node(event["node_id"])
        elif event["event"] == "TOOL_RESULT":
            self.append_log(event)
```

### 3.4 LoRA Adapter Requirements

For the MVP demo, you need these adapters:

| Adapter Name | Base Model | Training Data | Fine-tuning Focus |
|--------------|------------|---------------|-------------------|
| `architect-v1` | FunctionGemma 270M | Architecture planning examples | Task decomposition, dependency analysis |
| `implement-v1` | FunctionGemma 270M | Code transformation pairs | Python patterns, API modifications |
| `rate-limit-v1` | FunctionGemma 270M | Rate limiting implementations | FastAPI middleware, Redis patterns |
| `caching-v1` | FunctionGemma 270M | Caching implementations | In-memory, Redis caching patterns |
| `test-gen-v1` | FunctionGemma 270M | Test case pairs | pytest patterns, mocking |

**Shortcut:** For initial demos, these can be the same base model with different system prompts. True fine-tuning can come later.

---

## 4. Alternative MVP Options

### 4.1 Option B: "Documentation Swarm" (Lower Risk)

**Concept:** Simplified version of SWARM_DOCUMENTATION_CONCEPT

**Demo Flow:**
1. Point Remora at a codebase
2. Watch 3 agents generate docs in parallel:
   - API Documentation Agent
   - README Generator Agent
   - Architecture Diagram Agent
3. Show live progress in terminal
4. Output: Complete documentation suite

**Pros:** Uses existing infrastructure, clear business value
**Cons:** Less visually impressive, doesn't showcase LoRA swapping as well

**Effort:** 2-3 weeks

### 4.2 Option C: "Live Refactoring Assistant" (IDE Focus)

**Concept:** Simplified version of LEARNING_ASSISTANT_CONCEPT

**Demo Flow:**
1. Open VS Code/Neovim with Remora LSP
2. Hover over function - see rich context
3. Select code - request refactoring
4. Watch agents collaborate to refactor
5. Accept/reject changes inline

**Pros:** Very relatable for developers, IDE integration impressive
**Cons:** Requires LSP implementation, harder to present to non-technical audience

**Effort:** 5-7 weeks

### 4.3 Option D: "Mini Swarm" (Scope Reduction)

**Concept:** Drastically simplified TREESITTER_AGENT_SWARM

**Demo Flow:**
1. User selects a single function in codebase
2. Show 3 specialized agents analyzing it:
   - Structure Agent (AST analysis)
   - Style Agent (linting/formatting)
   - Doc Agent (docstring generation)
3. Agents communicate via shared workspace
4. Final merged result

**Pros:** Most faithful to your favorite concept, achievable scope
**Cons:** Less impressive than full swarm vision

**Effort:** 3-4 weeks

---

## 5. Detailed Comparison: Recommended vs Alternatives

### 5.1 Feature Comparison

| Feature | Code Evolution (Rec) | Doc Swarm (B) | Live Refactor (C) | Mini Swarm (D) |
|---------|---------------------|---------------|-------------------|----------------|
| AST Visualization | ✓ | ○ | ○ | ✓ |
| LoRA Hot-Swap Demo | ✓ | ○ | ○ | ✓ |
| Parallel Agents | ✓ | ✓ | ○ | ✓ |
| Live Dashboard | ✓ | ✓ | ○ | ✓ |
| Sandbox Demo | ✓ | ○ | ✓ | ✓ |
| Business Appeal | High | High | Medium | Medium |
| Technical Wow | High | Medium | High | Medium |

**Legend:** ✓ = Primary feature, ○ = Secondary/Limited

### 5.2 Risk Assessment

| Risk Category | Code Evolution | Doc Swarm | Live Refactor | Mini Swarm |
|---------------|----------------|-----------|---------------|------------|
| Technical Complexity | Medium | Low | High | Low |
| Integration Risk | Medium | Low | High | Low |
| Demo Failure Risk | Medium | Low | Medium | Low |
| Time Overrun Risk | Medium | Low | High | Low |

---

## 6. Implementation Roadmap

### 6.1 Phase 1: Foundation (Week 1-2)

**Deliverables:**
- [ ] Live Dashboard TUI skeleton
- [ ] Event stream → Dashboard bridge
- [ ] AST visualization component
- [ ] Agent status panel

**Technical Tasks:**
```bash
# Create dashboard module
mkdir -p src/remora/dashboard
touch src/remora/dashboard/__init__.py
touch src/remora/dashboard/app.py
touch src/remora/dashboard/widgets.py
touch src/remora/dashboard/event_handler.py
```

**Dependencies:**
```toml
# pyproject.toml additions
textual = ">=0.47.0"
rich = ">=13.0.0"
```

### 6.2 Phase 2: Agent Bundles (Week 2-3)

**Deliverables:**
- [ ] Architect agent bundle
- [ ] Implementation agent bundle
- [ ] Rate-limit tool script
- [ ] Caching tool script

**Bundle Structure:**
```
agents/
├── architect/
│   ├── bundle.yaml
│   └── tools/
│       ├── analyze_ast.pym
│       ├── plan_transformation.pym
│       └── delegate_to_agent.pym
├── implement/
│   ├── bundle.yaml
│   └── tools/
│       ├── read_file.pym
│       ├── apply_transformation.pym
│       └── submit_implementation.pym
```

### 6.3 Phase 3: LoRA Integration (Week 3-4)

**Deliverables:**
- [ ] LoRA swap event emission
- [ ] Dashboard adapter visualization
- [ ] Adapter preloading hints
- [ ] Fallback to base model

**Key Code:**
```python
# src/remora/events.py addition
class EventName(str, Enum):
    # ... existing events ...
    LORA_SWAP = "LORA_SWAP"

# Emit on adapter change
emitter.emit({
    "event": EventName.LORA_SWAP,
    "agent_id": agent_id,
    "from_adapter": previous,
    "to_adapter": new_adapter,
    "timestamp": datetime.now().isoformat(),
})
```

### 6.4 Phase 4: Demo Polish (Week 4-5)

**Deliverables:**
- [ ] Demo script automation
- [ ] Sample target codebase
- [ ] Recording capability
- [ ] Error recovery flows
- [ ] Presentation materials

### 6.5 Phase 5: Testing & Refinement (Week 5-6)

**Deliverables:**
- [ ] End-to-end demo tests
- [ ] Performance optimization
- [ ] Edge case handling
- [ ] Documentation

---

## 7. Demo Environment Setup

### 7.1 Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | RTX 3080 (10GB) | RTX 4090 (24GB) |
| RAM | 32GB | 64GB |
| vLLM | Single GPU | Multi-GPU |
| Storage | 100GB SSD | 500GB NVMe |

### 7.2 vLLM Configuration

```bash
# Launch vLLM with LoRA support
vllm serve google/functiongemma-270m-it \
    --enable-lora \
    --max-loras 8 \
    --max-cpu-loras 16 \
    --lora-modules architect-v1=./adapters/architect \
                   implement-v1=./adapters/implement \
                   rate-limit-v1=./adapters/rate-limit \
                   caching-v1=./adapters/caching \
                   test-gen-v1=./adapters/test-gen
```

### 7.3 Sample Target Codebase

Create a simple FastAPI app for transformation:

```python
# demo_target/api/routes.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/users")
async def get_users():
    """Fetch all users from database."""
    return await db.fetch_all_users()

@router.get("/users/{user_id}")
async def get_user(user_id: int):
    """Fetch a single user by ID."""
    return await db.fetch_user(user_id)

@router.post("/users")
async def create_user(user: UserCreate):
    """Create a new user."""
    return await db.create_user(user)
```

**Transformation Goal:** Add rate limiting (100 req/min) and caching (5 min TTL) to GET endpoints.

---

## 8. Success Metrics

### 8.1 Technical Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Demo completion time | < 3 minutes | End-to-end timing |
| Agent coordination | 3+ agents parallel | Dashboard observation |
| LoRA swaps visible | 5+ swaps | Event log count |
| Zero failures | 100% success | Demo run tests |

### 8.2 Audience Impact Metrics

| Audience | Goal | Indicator |
|----------|------|-----------|
| Developers | "I want to use this" | Follow-up questions about API |
| Investors | "This is differentiated" | Questions about competition |
| Enterprise | "This solves my problem" | Questions about integration |

---

## 9. Risk Mitigation

### 9.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| vLLM LoRA swap latency | Medium | High | Pre-warm adapters, use caching |
| Agent coordination failure | Medium | High | Implement retry logic, timeout handling |
| Grail script errors | High | Medium | Extensive testing, fallback responses |
| Dashboard performance | Low | Medium | Lazy loading, event throttling |

### 9.2 Demo Day Risks

| Risk | Mitigation |
|------|------------|
| Network issues | Run everything locally |
| GPU memory exhaustion | Monitor VRAM, limit concurrent agents |
| Unexpected errors | Pre-record backup video |
| Time overrun | Practice with timer, have short version |

---

## 10. Future Expansion

After successful MVP demo, expand to full visions:

### Phase 2: Full Tree-sitter Swarm
- Train node-specific LoRA adapters
- Implement graph algorithms (PageRank, A*)
- Add multi-file coordination

### Phase 3: Language Packs
- Create `.remorapack` distribution format
- Build public registry
- Add EmbeddingGemma for similarity search

### Phase 4: Enterprise Features
- CI/CD integration
- GitHub/GitLab plugins
- Team collaboration features

---

## 11. Conclusion

The **Code Evolution Pipeline** demo represents the optimal balance of:

1. **Visual Impact** - Live dashboard with AST navigation and agent coordination
2. **Technical Differentiation** - LoRA hot-swapping is unique and impressive
3. **Achievable Scope** - Builds on existing infrastructure
4. **Business Relevance** - Clear enterprise use case

**Recommended Next Steps:**
1. Approve this concept and begin Phase 1
2. Set up vLLM development environment with LoRA support
3. Create initial dashboard prototype
4. Define specific training data for adapter fine-tuning

The demo should be ready for internal presentation in 4 weeks, with another 2 weeks for polish before external audiences.

---

## Appendix A: Concept Rejection Rationale

### Why Not Pure TREESITTER_AGENT_SWARM?

The full swarm concept requires:
- Training 50+ node-specific LoRA adapters
- Implementing Louvain community detection
- Building Bayesian infection propagation
- Creating vector arithmetic tooling

This is 6-12 months of work. The MVP extracts the most impressive elements (AST visualization, multi-agent coordination) without requiring the full mathematical infrastructure.

### Why Not Pure COMPREHENSIVE_EMBEDDINGS_MODEL_SUITE?

The language pack concept requires:
- Fine-tuned EmbeddingGemma with MRL
- CodeGemma 2B with LoRA
- T5Gemma for transformations
- FunctionGemma for orchestration

Four different model architectures is too complex for MVP. We simplify to FunctionGemma-only with prompt engineering for different roles.

---

## Appendix B: Alternative Fine-Tuning Strategy

If training LoRA adapters is not feasible for MVP:

### Prompt-Based Role Differentiation

```python
# Instead of separate adapters, use role prompts
ARCHITECT_PROMPT = """You are a software architect specializing in API design..."""
IMPLEMENTER_PROMPT = """You are a senior Python developer implementing changes..."""
TESTER_PROMPT = """You are a QA engineer writing comprehensive tests..."""

# Same base model, different system prompts
# Dashboard still shows "adapter: architect-v1" for visual effect
# But actually uses prompt differentiation
```

This allows the demo to proceed without actual fine-tuning, while maintaining the narrative of specialized agents.

---

*End of MVP Demo Concept Document*
