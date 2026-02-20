# SHELLper - multi-turn bash function calling model

<p align="center">
  <img src="shellper.png" alt="SHELLper" width="200">
</p>

*Turn natural language into bash commands with a small, local model.*

We trained a small model for a multi-turn tool calling task - bash command execution. Our model converts plain text requests
into executable bash commands. 

Multi-turn tool calling is notoriously difficult for small models - before tuning, QWEN3 0.6B had a single tool call prediction accuracy of 84% which means **accuracy of 42% for 5-turn** user-model conversations! After our tuning, the model achieves 100% on our test set, offering reliable multi-turn capabilities.

| Model | Parameters | Tool call accuracy (test set) | => average 5-turn tool call accuracy |
| --- | --- | --- | --- |
| Qwen3 235B Instruct (teacher) | 235B | 99% | 95% |
| **Qwen3 0.6B (tuned)** | **0.6B** | **100%** | 100% |
| Qwen3 0.6B (base) | 0.6 | 84.16% | 42.22% |


The model is available on [huggingface](https://huggingface.co/distil-labs/distil-qwen3-0.6b-SHELLper), and you can run it locally on your PC. We provide here a simple demo for bash command execution - it asks before executing commands (for safety) and also limits some of the dangerous commands (like `rm -r /`), so don't be afraid to check it out!

## Quick Start

### 1. Install Ollama

Install [Ollama](https://ollama.com/) following the instructions on their website.

### 2. Set up the environment

```bash
python -m venv .venv
. .venv/bin/activate
pip install openai
pip install --upgrade huggingface_hub
```

### 3. Download and build the model
```bash
# Download the model
hf download distil-labs/distil-qwen3-0.6b-SHELLper model_fp16.gguf Modelfile --local-dir distil_model

cd distil_model
ollama create distil_model -f Modelfile
cd ..
```

Alternatively, to download all files including the `model.safetensors` (for usage in transformers):
```bash
# Download the model
hf download distil-labs/distil-qwen3-0.6b-SHELLper --local-dir distil_model
```

### 4. Run the assistant

```bash
python filesystem_demo.py
```


## Usage Examples

The assistant takes natural language requests, converts them to bash commands, and optionally executes them (asking y/N).

### Basic usage (print commands only)

```bash
> python filesystem_demo.py

USER: List all files in the current directory
COMMAND: ls

USER: Create a new directory called test_folder
COMMAND: mkdir test_folder

USER: Navigate to test_folder
COMMAND: cd test_folder
```

Command line options:

| Option | Default | Description |
|--------|---------|-------------|
| `--execute_commands` | off | Execute commands without asking for confirmation (on your own responsibility) |
| `--allow_recursive` | off | Allow recursive directory removal (`rm -r`) |
| `--verbose` | off | Also print the tool calling output (before parsing to bash commands) |
| `--model` | `distil_model` | Model name |


## How We Trained the Model

### The Problem

n multi-turn tool calling, the data is a conversation history of user requests and model tool call responses.
The data looks like this:
```
# Input (conversation history)
[
  {"role": "user", "content": "List all files in the current directory"},
  {
    "role": "assistant",
    "tool_calls": [{"type": "function", "function": {"name": "ls", "arguments": {"folder": "."}}}]
  },
  {"role": "user", "content": "Now go to the src folder"}
]

# Target (next tool call to predict)
{"name": "cd", "arguments": {"folder": "src"}}
```

Multi-turn tool calling is notoriously difficult for small models - the performance deteriorates when tool calls are chained - a model with a single tool call accuracy of 80 % has only a 33% chance it won't make a mistake over 5 turns.

| Single tool call accuracy | 5-turn tool call accuracy |
| --- | --- |
| 80% | 33% |
| 90% | 59% |
| 95% | 77% |
| 99% | 95% |

Every percentage point in accuracy has a tremendous impact on the performance on the deployed model so it is very important to use every available tool (like model fine tuning).

For this demo, we chose an existing task from the [Berkeley function calling leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html) - the [gorilla file system tool calling task](https://github.com/ShishirPatil/gorilla/blob/main/berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v4_multi_turn_base.json). We modify it for our case:
- this task allows multiple tool calls per assistant turn -> we allow only one
- we map the commands to existing bash commands in this demo (instead of calling gorilla filesystem functions)

In other words, we keep the same tool set, but create new, simpler, train/test data. Nevertheless, in future works on multi-turn tool calling, we plan to expand to the more complex multi-turn tasks.

See [functions.md](functions.md) for the complete list of supported Gorilla tools and their bash translations.

### Training Pipeline

**1. Seed Data:** 
We created 20 simplified training conversation (only 1 tool call rather than multiple per response).

These examples should cover the available tools while still being somewhat realistic.

**2. Synthetic Expansion:** Using our [data synthesis pipeline](https://www.distillabs.ai/blog/small-expert-agents-from-10-examples/?utm_source=github&utm_medium=referral&utm_campaign=shellper), we expanded to thousands of training examples.

Compared to our other tasks, we need to handle conversations of various length - to help this, we expanded each conversation
into intermediate conversations. For example, this conversation:
```
[Input] User: List all files => Model: ls -al => User: go to directory models
[Output] Model: cd models
```

... is expanded into 2 data points:
```
[Input] User: List all files
[Output] Model: ls -al

[Input] User: List all files => Model: ls -al => User: go to directory models
[Output] Model: cd models
```

**3. Fine-tuning:** We chose Qwen3-0.6B as the smallest available model in our platform that we tested with tool calling.



## Train Your Own Model

The workflow we used is generic across text generation tasks. Here's we provide instructions for how you can train a model
for your multi-turn tool calling task.

Check out also our [Claude CLI skill](https://github.com/distil-labs/distil-cli-skill) that can help you call the right training commands!

### 1. Define your task format and seed examples

Look at `data/job_description.json` and `data/train.jsonl` - think about which functions you have available,
and create example conversations. Be sure to follow the correct function calling format.

Note: Multi-turn tool calling is in active development - the format may change, and we work on providing a better experience and documentation.

### 2. Train the model
Install distil CLI...
```bash
curl -fsSL https://cli-assets.distillabs.ai/install.sh | sh
```

...and train!
```
# Log in (if you dont have an account, use `distil register`)
distil login

# create a model for your specific task
distil model create my-first-model
# Output: Model created with ID: <model-id>

# Upload your data (see Data preparation for details)
distil model upload-data <model-id> --data ./data

# Train a Small Model to solve your task as well as an LLM can
distil model run-training <model-id>

# Download the trained model
distil model download <model-id>
```

That's it! Your trained model is ready for [local deployment](https://docs.distillabs.ai/deployment/local-deployment). You can also use our [Claude Skill](https://github.com/distil-labs/distil-cli-skill) to train models directly from Claude Code or Claude.ai.


## FAQ

**Q: Why not just use GPT-4 / Claude for this?**

You can - but small models are a cheaper alternative that runs locally, offering better data privacy.
If you want general-purpose tool calling models, proprietary LLMs will most likely have a better performance.
However, if you have a specific task in mind, fine-tuned SLMs might work well for you!

**Q: Why not use a small tool-calling-focused model?**

As per here, even these models are not perfect on multi-turn tasks (note that these are more complex than our case)
https://gorilla.cs.berkeley.edu/leaderboard.html

This means that there is still a potential in gaining performance via fine-tuning on a specific tool-calling task. Our aim
are not general-purpose tool calling models, but rather task-specific models with a good practical performance.

**Q: The model can't do XXX in bash or made an error?!**

Right now, we support only a limited tool set for bash:
- no pipes, combined commands, or multiple tool calls per assistant turn
- no invalid command/parameter detection
- max 5 turns of user-model exchanges

We wanted to focus first on making the simplest case good and then move to more complex setups!

There are also some other limitations, for example, less robustness for paraphrases.
While our other tasks target this (via synthetic data coverage), here we focused mostly on improving tool call accuracy in general.

If you want to use this for your bash workflows, you can track which commands fail, add them to `data/train.jsonl`, and then train a new model based on the updated data (you can also try using a larger student model!). Check out our documentation on [multi-turn tool calling](https://docs.distillabs.ai/how-to/data-preparation/multi-turn-tool-calling) for more details.


**Q: Why do you use ollama? :(**

This demo uses ollama for convenience of setup, but we have model.safetensors and model.gguf files - just be sure to use the correct chat template (for example, we have not tested tool calling formatting in llama.cpp yet).

**Q: Can you train a model for my company's specific workflows?**

Yes! Visit [distillabs.ai](https://www.distillabs.ai/?utm_source=github&utm_medium=referral&utm_campaign=shellper) to discuss custom solutions trained on your specific command patterns.


## Links

<p align="center">
  <a href="https://www.distillabs.ai/?utm_source=github&utm_medium=referral&utm_campaign=shellper">
    <img src="https://github.com/distil-labs/badges/blob/main/badge-distillabs-home.svg?raw=true" alt="Distil Labs Homepage" />
  </a>
  <a href="https://github.com/distil-labs">
    <img src="https://github.com/distil-labs/badges/blob/main/badge-github.svg?raw=true" alt="GitHub" />
  </a>
  <a href="https://huggingface.co/distil-labs">
    <img src="https://github.com/distil-labs/badges/blob/main/badge-huggingface.svg?raw=true" alt="Hugging Face" />
  </a>
  <a href="https://www.linkedin.com/company/distil-labs/">
    <img src="https://github.com/distil-labs/badges/blob/main/badge-linkedin.svg?raw=true" alt="LinkedIn" />
  </a>
  <a href="https://distil-labs-community.slack.com/join/shared_invite/zt-36zqj87le-i3quWUn2bjErRq22xoE58g">
    <img src="https://github.com/distil-labs/badges/blob/main/badge-slack.svg?raw=true" alt="Slack" />
  </a>
  <a href="https://x.com/distil_labs">
    <img src="https://github.com/distil-labs/badges/blob/main/badge-twitter.svg?raw=true" alt="Twitter" />
  </a>
</p>
