<!-- c:\Users\Andrew\Documents\Projects\remora\RECURSIVE_LANGUAGE_MODELS_RESEARCH.md -->

# Recursive Language Models (RLMs): Research Report & Implementation Strategy

**Status:** Research Aggregation
**Source Material:** "Recursive Language Models" by Alex L. Zhang (MIT OASYS lab, 2025)

---

## 1. Executive Summary

The paper *Recursive Language Models* addresses a fundamental limitation in modern Large Language Models: **Context Rot**. As the length of a prompt increases, an LLM's ability to recall and reason over that information degrades, even if the information technically fits within its maximum context window.

Rather than trying to force more tokens into the Transformer architecture (which is computationally expensive and still suffers from degradation on complex tasks), the paper proposes a simple, task-agnostic framework: **Recursive Language Models (RLMs)**.

The core thesis of an RLM is to stop feeding the massive context directly into the LLM's prompt. Instead, the context is offloaded into an external execution environment (a Python REPL) as a queryable variable. The LLM is then placed into this environment and tasked with writing code to programmatically explore, chunk, and recursively spawn sub-LLM calls over specific pieces of that context to build up a final answer.

The results show that RLMs can handle inputs containing tens of millions of tokens (far beyond any current model's context window), drastically outperform base models on complex long-context reasoning tasks, and operate at a comparable or cheaper API cost due to processing fewer tokens overall.

---

## 2. Core Concepts & Vocabulary Definitions

The paper relies on several key concepts and acronyms to define its architecture and evaluation methodologies.

### Architectural Terms
*   **RLM (Recursive Language Model):** An inference strategy where an LLM is placed in a sandbox and given tools to write code that interacts with its input context. It can recursively call sub-LLMs over parsed chunks of that context.
*   **REPL (Read-Eval-Print Loop):** An interactive programming environment (like a Jupyter notebook or a Python console) where the LLM writes code, executes it, and observes the printed output to make its next decision.
*   **Root LM / Depth=0 LM:** The primary LLM process that receives the initial user query and the REPL environment. It manages the high-level planning and orchestrates the sub-calls.
*   **Recursive LM / Sub-LM / Depth=1 LM:** A secondary LLM process called programmatically by the Root LM using a function like `llm_query(prompt, context_chunk)`. In the paper's experiments, this is restricted to a depth of 1 (the sub-LM cannot call another sub-LM).
*   **Context Rot / Context Degradation:** The observed phenomenon where an LLM's reasoning and recall abilities decrease as the number of tokens in its context window increases.
*   **Information Density:** A categorization of how difficult a task is based on how much of the context must be processed to find the answer. The paper argues that LLMs experience Context Rot much faster on information-dense tasks.

### Evaluation & Baseline Terms
*   **S-NIAH (Single Needle-in-a-Haystack):** A benchmark task where the model must find one specific fact hidden in a massive document. Characterized as having a *constant* scaling of information density (only one thing matters, regardless of size).
*   **BrowseComp-Plus:** A multi-hop question-answering benchmark where the model must synthesize facts across multiple documents.
*   **OOLONG:** A benchmark requiring semantic transformation and aggregation across nearly every line of the context. Characterized as *linear* complexity.
*   **OOLONG-Pairs:** A synthetic benchmark requiring the aggregation of pairs of chunks. Characterized as *quadratic* complexity (the hardest task).
*   **Context Compaction / Summary Agent:** A competing baseline method where a massive context is iteratively summarized down to fit into a model's context window. (The RLM outperforms this by a wide margin).
*   **CodeAct:** A competing baseline agent architecture that can execute Python code (acting), but unlike an RLM, it still loads the massive context string directly into its LLM prompt rather than keeping it isolated in the environment.

---

## 3. The RLM Implementation Mechanism

The paper's implementation of an RLM is surprisingly simple. It does not require retraining the base model; it relies entirely on clever scaffolding and system prompts.

### Step-by-Step Execution Loop
1.  **Environment Initialization:** The massive input context (e.g., 1000 documents, or a 1M token codebase) is loaded into the memory of a Python REPL sandbox as a variable (e.g., `context`).
2.  **Root LM Prompting:** The Root LM is prompted with the user's query and the *metadata* of the context (e.g., "Your context is a list of strings with 8.3M characters"). It does *not* receive the text of the context.
3.  **Code as Navigation:** The Root LM writes a Python code block (tagged with ```repl) to interact with the environment.
    *   *Example (Grepping):* It might write `[line for line in context if "error" in line]` to filter the context based on its priors.
    *   *Example (Peeking):* It might write `print(context[:1000])` to understand the data structure.
4.  **Recursive Sub-Calling (The Core Engine):** The REPL environment exposes a function `llm_query(prompt)`. The Root LM uses Python loops or list comprehensions to chunk the massive context and fire off sub-LLM calls for each chunk.
    *   *Example (Map-Reduce):*
        ```python
        answers = []
        for doc in context:
            if "target_word" in doc:
                res = llm_query(f"Extract the specific date from this doc: {doc}")
                answers.append(res)
        ```
5.  **State Accumulation (Buffer Variables):** The outputs of the sub-LMs are stored in Python variables (e.g., `buffers = []`) within the REPL.
6.  **Termination:** Once the Root LM has programmatically synthesized the data in its buffers, it outputs a final answer wrapped in a specific tag (e.g., `FINAL(answer)` or `FINAL_VAR(variable_name)`).

### Crucial Implementation Decisions Noted in the Paper
*   **Asymmetric Model Pairing is Cost-Effective:** To manage API costs, the paper strongly recommends using a highly capable model for the Root LM (e.g., GPT-5) to write the REPL code and manage the reasoning, but a much cheaper/smaller model for the Recursive Sub-LMs (e.g., GPT-5-mini) to handle the map-reduce extraction tasks.
*   **Blocking vs. Asynchronous Calls:** The paper admits their implementation used blocking (sequential) sub-LM calls, making tasks very slow. They explicitly call out asynchrony (running the 100 `llm_query` map operations in parallel) as a major required optimization for real-world systems.
*   **Prompt Specificity per Model:** The paper found that Qwen-Coder models tended to abuse the `llm_query` function, firing off thousands of sub-calls when simple regex would do. They had to modify the system prompt specifically for Qwen to warn against excessive sub-calling and encourage batching.

---

## 4. Emergent Behaviors Observed

Because the LLM dictates its own programmatic traversal of the context, several un-programmed "emergent behaviors" were observed during evaluation:

1.  **Grepping / Filtering via Priors:** Without being told to, models frequently used standard Python string manipulation or Regex to filter the 10M token context down to just a few hundred relevant lines before ever calling a sub-LM, drastically saving cost and avoiding context rot.
2.  **Peeking:** Models would frequently `print()` the first 2000 characters of a context to learn its formatting (e.g., realizing it's a CSV or Markdown) before deciding how to chunk it.
3.  **Partition + Map (Map-Reduce):** When semantic understanding was required across the whole document (e.g., the OOLONG tasks), models naturally chunked the data and wrote loops to execute sub-LLMs over each chunk, aggregating the results back into a Python list.
4.  **Long-Output Synthesis:** For tasks requiring massive text generation (e.g., generating pairs of users), standard LLMs run out of output tokens. RLMs solved this by storing the partial outputs of sub-LLMs in a massive REPL variable and returning `FINAL_VAR(my_huge_list)` to bypass the token generation limit entirely.
5.  **Programmatic Verification:** Models would occasionally use `llm_query` to verify the accuracy of a previous `llm_query` output, or write a dedicated Python script to run an assertion check on the extracted data.

---

## 5. Bridging the Paper to Remora

The research presented in this paper perfectly validates the architecture of Remora. The paper proves that placing an LLM in a REPL sandbox with programmatic access to a context object is vastly superior to prompt-stuffing.

In Remora's implementation of this concept (as explored in `RECURSIVE_ENVIRONMENT_MODELS.md`):
*   Remora's **Grail `.pym` execution engine** serves as the robust Python REPL.
*   Instead of just string blobs, Remora injects the **Tree-sitter AST Graph** into the REPL, giving the Root LM far more powerful query tooling than basic Regex.
*   Remora's **vLLM Continuous Batching** natively solves the paper's primary limitation (slow, blocking inference), allowing the Root LM to spawn asynchronous, parallel sub-Agent workspaces instantly.
*   Remora's **Cairn KV Memory Bus** handles the passing of variables and intent between the Root LM and the sub-LMs, replacing the brittle string manipulation of the paper's basic `llm_query` function.

---

## 6. Prompt Engineering & System Design Observations

The authors provided deep insights into their system prompting strategy and shared several "negative results" detailing what failed during their experiments (documented in Appendix A and D of the paper). 

### The Core RLM System Prompt Structure
The system prompt for an RLM does not contain the context. Instead, it defines the rules of the sandbox. The prompt provided to GPT-5 included:
1.  **Environment Definition:** Explaining that a `context` variable exists in memory and contains the data.
2.  **Tool Definitions:** Defining the `llm_query(prompt)` function to allow recursive calls.
3.  **Syntactic Rules:** Instructing the model to write code in ````repl```` blocks.
4.  **Workflow Examples (Few-Shot):** The prompt heavily relies on in-context examples showing the model *how* to chunk, *how* to write map-reduce loops over the `context` list, and *how* to use regex to search headers.
5.  **Termination Clause:** Explicitly defining how to exit the loop by invoking `FINAL(answer)` or `FINAL_VAR(var_name)`.

### What Failed (Negative Results)
*   **One-Size-Fits-All Prompts:** Using the exact same system prompt for GPT-5 and Qwen3-Coder failed. Qwen was too liberal with the `llm_query` tool, spawning thousands of sub-calls when simple regex would suffice. They had to append a specific warning to Qwen's prompt: *"IMPORTANT: Be very careful about using `llm_query` as it incurs high runtime costs. Always batch as much information as reasonably possible..."*
*   **Small Models:** Models lacking strong built-in coding capabilities (e.g., Qwen3-8B) failed entirely as Root RLMs because they could not write valid Python loops to navigate the environment.
*   **Token Starvation in "Thinking" Models:** Using reasoning models (like "think" models) as the Root LM often led to failures because the model's internal "thinking" tokens consumed the entire output context window before it could finish writing the `llm_query` loop.
*   **Synchronous Execution:** The authors naïvely implemented `llm_query` as a blocking, sequential call. This resulted in extremely slow execution times. They explicitly cite asynchronous parallel mapping as a necessary system feature.
*   **Brittle Termination:** Distinguishing between the AI just "thinking" inside the REPL and providing the final answer was error-prone. Even with the `FINAL()` tag structural enforcement, models occasionally tried to output their "plan" as the final answer.

---

## 7. Fine-Tuning & Training for RLMs

**Crucial Clarification:** The authors of the paper **did not perform any fine-tuning** or custom training for their RLMs. The phenomenal results achieved in the paper (handling 10M+ tokens) were done purely via Zero-Shot and Few-Shot prompting of off-the-shelf frontier models (GPT-5 and Qwen3-Coder-480B).

However, the authors explicitly state in their "Limitations and Future Work" section that utilizing standard base models as RLMs is inefficient (e.g., they make too many unnecessary sub-calls or repeat assertions). They hypothesize that the next major axis of scale is explicitly training RLMs to navigate contexts natively. 

### Recommended QLoRA Fine-Tuning Strategy for Remora

Since base models struggle with the specific nuances of an RLM environment (knowing *when* to code vs. *when* to query, formatting the `FINAL` tags, and preventing context starvation), we can emulate the paper's "Future Work" using low-cost QLoRA adapters. 

Here is a recommended approach to training "Root Architect" and "Sub-Node" RLMs for Remora on a budget:

#### 1. Dataset Generation via Bootstrapping (STaR Method)
The paper cites the STaR (Self-Taught Reasoner) method. We shouldn't pay humans to write RLM trajectories. Instead:
1.  Take a powerful, expensive model (like Claude 3.5 Sonnet or GPT-4o) and give it the heavy RLM system prompt.
2.  Feed it 1,000 algorithmic codebase queries (e.g., "Find all functions returning a dict and modify them").
3.  Let it organically operate in the Grail sandbox, generating REPL scripts and spawning sub-calls. 
4.  Throw away the failed trajectories. Keep only the trajectories that successfully resulted in a correct codebase modification or correct answer. 
5.  This yields a golden dataset of perfect code-based reasoning chains.

#### 2. QLoRA Adapter Configuration 
To train on consumer hardware or low-cost cloud GPUs (like a single A100 or 4x RTX 4090s), use **QLoRA (Quantized Low-Rank Adaptation)**.

*   **Base Model:** Choose a strong, open-source coding model. **Qwen2.5-Coder-32B** or **Llama-3-70B-Instruct** are ideal candidates.
*   **Quantization:** Load the base model in 4-bit NormalFloat (NF4) bitsandbytes quantization to drastically reduce VRAM requirements.
*   **Target Modules:** Apply the LoRA adapters to all linear layers (e.g., `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`). RLM navigation requires complex logical reasoning, so targeting only attention heads is insufficient.
*   **Rank (r) and Alpha:** Use a moderate rank, `r=16` or `r=32`, with `lora_alpha=2*r`. This provides enough parameter capacity to learn the specific REPL syntax rules and tool-calling cadence without overfitting.

#### 3. Training Objectives (What the LoRA is learning)
The QLoRA fine-tuning process shouldn't teach the model *how to code*; the base model already knows that. It should teach the model **environment management discipline**:
*   **Tool Cadence:** Learning to write one clean Python script, stop generation, wait for the Grail standard output, and then write the next step.
*   **Sub-Calling Restraint:** Learning *not* to use `llm_query` iteratively on 10,000 individual nodes, but to use native Python (like Tree-sitter AST filters) to narrow the context first, then batch sending via a localized sub-environment.
*   **Graceful Degradation:** Teaching the model to capture `try/except` errors in its own REPL scripts rather than crashing the loop.
*   **Termination Formatting:** Perfectly conforming to the `FINAL_VAR()` output constraints so the parsing engine never fails.

By training these specific behaviors into a lightweight LoRA, Remora can achieve the power of the paper's hypothetical "Trained RLM" using significantly cheaper open-weights models and dynamic LoRA swapping via vLLM.
