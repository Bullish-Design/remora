# Remora Model Suite: Technical Architecture

> **Status**: Concept / Design Draft
> **Related**: DOMAIN_BOOTSTRAP_CONCEPT.md

## 1. Overview

The Remora Model Suite (RMS) architecture defines a "Language Pack": a distributable unit containing fine-tuned model adapters, embeddings, and templates specialized for a specific domain (e.g., a library like `FastAPI` or an internal company codebase).

The system uses a multi-model approach where specialized models handle distinct aspects of the code generation pipeline, orchestrated by a central agent.

## 2. Component Architecture

A Language Pack consists of five synchronized components:

### A. The Orchestrator: FunctionGemma
*   **Model**: FunctionGemma (270M) - *Ultra-Low Latency*
*   **Role**: Decision Engine & Tool Caller.
*   **Responsibility**:
    *   Parses user intent from natural language or code context.
    *   Decides which sub-components to activate (e.g., "Scan docs" vs "Generate code").
    *   Calls the `search_embeddings` tool to retrieve context.
    *   Calls the `render_template` tool to generate scaffolding.
    *   Delegates complex generation tasks to the LoRA-equipped CodeGemma model.

### B. The Semantic Layer: EmbeddingGemma
*   **Model**: Fine-tuned EmbeddingGemma (270M)
*   **Feature**: **Matrioshka Representation Learning (MRL)**
*   **Training Data**: Library documentation, source code, and "Gold Standard" usage examples.
*   **Responsibility**:
    *   **Adaptive Retrieval**: Thanks to MRL, the model produces "nesting doll" vectors.
        *   *Fast Pass*: Use the first 64 dimensions for ultra-low-memory pre-filtering of millions of chunks.
        *   *Precise Pass*: Use the full 768 dimensions to re-rank the top 100 candidates.
    *   **Value**: Allows the vector index to fit entirely in CPU L3 cache or edge-device RAM while maintaining high precision for the final selection.
    *   **Contextual Type Inference**: Matches variable usage patterns to vector clusters.

### C. The Generative Layer: CodeGemma LoRA
*   **Model**: CodeGemma (2B) with Low-Rank Adapters (LoRA)
*   **Training Data**: Library source code and high-quality dependent repositories.
*   **Responsibility**:
    *   **Context-Aware Completion**: Generates method bodies and complex logic.
    *   **Idiomatic Usage**: The LoRA ensures generation adheres to specific library versions/patterns.
    *   **Dynamic Serving (vLLM)**: Leverages vLLM's continuous batching to serve hundreds of different fine-tuned adapters from a single base model.

### D. The Transformational Layer: T5Gemma 2
*   **Model**: T5Gemma 2 (270M or 1B) - Encoder-Decoder
*   **Capabilities**: 128k context window, Multimodal (SigLIP encoder).
*   **Responsibility**:
    *   **Deterministic Transformation**: Code refactoring, style enforcement, and docstring generation.
    *   **Content Generation**: Specialized fine-tunes for non-code artifacts.
        *   **README Writer**: Ingests code structure -> Outputs comprehensive `README.md`.
        *   **Marketing Blurb**: Ingests feature code -> Outputs release notes/marketing copy.
    *   **Summarization**: Ingesting large documentation sections (up to 128k tokens) to provide concise context to the Orchestrator.
    *   **Multimodal Analysis**: Analyzing UI screenshots to generate structural code.

### E. The Deterministic Layer: `.pym` Templates
*   **Format**: Python scripts generating Jinja2 templates.
*   **Responsibility**:
    *   **Scaffolding**: Generating file structures, imports, and boilerplate.
    *   **Standardization**: Enforcing project-specific patterns (e.g., specific error handling blocks, security decorators) that probabilistic models might miss.

## 3. Interaction Workflows

### 3.1. Context-Aware Type Inference
1.  **Trigger**: User hovers over untyped variable `s` or invokes completion.
2.  **EmbeddingGemma**: Embeds the usage window (surrounding lines). Searches vector index for nearest neighbors in the target library's codebase.
3.  **FunctionGemma**: Analyzes search results. If confidence > threshold, inserts type hint.

### 3.2. Feature Scaffolding
1.  **Trigger**: User command "Add user profile endpoint".
2.  **FunctionGemma**:
    *   Calls `search_embeddings` to find existing `User` model.
    *   Selects `fastapi/router.pym` template.
3.  **Template Engine**: Renders the router file structure with correct imports.
4.  **CodeGemma LoRA**: Fills in the specific business logic within the generated function bodies, using the context of the `User` model.

### 3.3. Multimodal Component Generation
1.  **Trigger**: User provides a screenshot of a dashboard widget.
2.  **T5Gemma 2**: specific visual encoder analyzes image, decoder generates raw HTML/Tailwind structure.
3.  **EmbeddingGemma**: Identifies internal components that match the visual elements (e.g., `PrimaryButton`).
4.  **FunctionGemma**: Refines the T5 output, replacing raw HTML with calls to the identified internal components.

### 3.4. Dynamic Activation (The "Just-in-Time" Brain)
Static models are always on; Remora Models are "JIT".
*   **TreeSitter Triggers**:
    *   *Trigger*: Parser detects `import pandas as pd`.
    *   *Action**: vLLM instantly hot-swaps the `adapter-pandas-v2` LoRA into the active slot.
    *   *Result*: The model now "thinks" in dataframes without increasing VRAM usage.
*   **Script Triggers**:
    *   *Trigger*: CI/CD pipeline runs `remora generate-release-notes`.
    *   *Action**: Activates `t5gemma-marketing-v1` adapter.
    *   *Result*: Generates a punchy, non-technical summary of the git diff for the `CHANGELOG.md`.

## 4. Packaging and Distribution

A `.remorapack` file is a compressed archive containing:
1.  `manifest.yaml`: Metadata, version dependencies, and entry points.
2.  `adapters/`: LoRA weight files (`.safetensors`).
3.  `embeddings/`: Vector store dump (e.g., ChromaDB or HNSW index).
4.  `templates/`: Directory of `.pym` scripts.

### Distribution Channels
*   **Public Registry**: Community-maintained packs for open-source libraries.
*   **Private Registry**: Authenticated S3/Artifact registry for internal enterprise packs (trained on private monorepos).

## 5. Implementation Roadmap (Phased Rollout)

### Phase 1: Foundation (The Serving Layer)
**Goal**: Enable dynamic, multi-LoRA serving via vLLM.

1.  **Refactor `LlmClient`**:
    *   Deprecate direct model loading in favor of a centralized `RemoraInferenceServer` (wrapping vLLM).
    *   Implement `MultiLoRAAdapter` pattern: The base model (CodeGemma 7B) stays loaded. Requests specify `adapter_id="fastapi-v3"`.
2.  **Benchmark Context Switching**:
    *   Verify vLLM's `enable_lora` performance impact.
    *   Establish memory budget for caching ~100 active adapters.

### Phase 2: The Training Pipeline (`remora-train`)
**Goal**: A CLI tool that turns a repo + docs into a `.remorapack`.

1.  **Data Ingestion**:
    *   `DocScraper`: recursively fetches documentation URLs and chunks them by semantic section.
    *   `RepoWalker`: uses TreeSitter to extract "Golden Snippets" (high quality functions with >90% test coverage).
2.  **Embedding Fine-tuning**:
    *   Script to fine-tune `embedding-gemma` using pair-mining (Code Snippet <-> Docstring).
    *   Output: `adapter-embedding-fastapi.safetensors`.
3.  **LoRA Fine-tuning**:
    *   Script to fine-tune `codegemma-7b` on the "Golden Snippets".
    *   Focus on *style* and *idiom* preservation (using low-rank r=16 for efficiency).
    *   Output: `adapter-generation-fastapi.safetensors`.
4.  **T5 Summarization Training**:
    *   Fine-tune `t5-gemma-270m` on Docstring <-> Function pairs.
    *   Output: `adapter-transform-fastapi.safetensors`.

### Phase 3: Runtime Integration (The "JIT" Brain)
**Goal**: Remora automatically loads/unloads packs based on user context.

1.  **TreeSitter Triggers**:
    *   Implement `ImportGenie`: A background watcher that parses `import` statements.
    *   Map `import fastapi` -> `load_adapter("fastapi-v3")`.
2.  **Context Injection**:
    *   Modify `FunctionGemma` system prompt to include available tool definitions from active packs.
    *   "You have the 'FastAPI' pack active. You can search its docs using `tool:fastapi_search`."
3.  **IDE UI**:
    *   Add a "Pack Status" indicator (e.g., "Active Packs: FastAPI, Pydantic, Internal-Utils").

### Phase 4: The Registry & Distribution
**Goal**: `pip install` for AI brains.

1.  **Pack Format**: Define the `.remorapack` zip specification (Manifest, 3x Adapters, VectorDB dump, Templates).
2.  **Registry API**: Simple S3-backed REST API for hosting community packs.
3.  **`remora install` CLI**:
    *   `remora install pack:fastapi` -> Downloads to `~/.remora/packs/`.
    *   `remora update` -> Pulls latest fine-tunes.
