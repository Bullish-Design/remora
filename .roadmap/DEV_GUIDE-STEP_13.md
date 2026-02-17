# DEV GUIDE STEP 13: Fine-Tuning Pipeline + GGUF Export

## Goal
Fine-tune the FunctionGemma base model for each domain using the training data from Step 12, then export each fine-tuned checkpoint to a Q8 GGUF file for use by the FunctionGemmaRunner.

## Why This Matters
This step produces the actual brain of each subagent. Without trained GGUF models, all runner infrastructure from Steps 4–11 runs in a degraded state (using the untrained base model). With trained models, the runner's multi-turn loop has a model that reliably produces correct tool calls for its domain.

## Implementation Checklist
- Implement `training/shared/base_model.py` — downloads and caches the FunctionGemma base model from HuggingFace Hub.
- For each domain, implement `training/{domain}/fine_tune.py` — LoRA fine-tuning using Unsloth (preferred) or HuggingFace PEFT.
- Implement `training/shared/gguf_export.py` — converts a fine-tuned HuggingFace checkpoint to Q8 GGUF using llama.cpp's `convert_hf_to_gguf.py`.
- Create `training/Makefile` with targets:
  - `generate-{domain}` — run the example generator for a domain
  - `generate-all` — generate all domains
  - `train-{domain}` — fine-tune and export for a domain
  - `train-all` — fine-tune and export all domains
  - `eval-{domain}` — run evaluation on eval split
- GGUF outputs go to `agents/{domain}/models/{domain}_functiongemma_q8.gguf`.

## Suggested File Targets
- `training/shared/base_model.py`
- `training/shared/gguf_export.py`
- `training/lint/fine_tune.py`
- `training/test/fine_tune.py`
- `training/docstring/fine_tune.py`
- `training/sample_data/fine_tune.py`
- `training/Makefile`

## Fine-Tuning Configuration

```python
# training/lint/fine_tune.py (representative)
from training.shared.base_model import load_base_model

model, tokenizer = load_base_model()

# LoRA config
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
)

# Training arguments
training_args = TrainingArguments(
    output_dir="training/lint/checkpoints",
    num_train_epochs=3,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    fp16=True,
    save_strategy="epoch",
    logging_steps=10,
)

# Train on JSONL examples
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=load_jsonl("training/lint/examples/train.jsonl"),
    eval_dataset=load_jsonl("training/lint/examples/eval.jsonl"),
    args=training_args,
    peft_config=lora_config,
)
trainer.train()
trainer.save_model("training/lint/checkpoints/final")
```

## GGUF Export

```python
# training/shared/gguf_export.py
import subprocess

def export_to_gguf(
    checkpoint_dir: str,
    output_path: str,
    quantization: str = "q8_0",
) -> None:
    subprocess.run([
        "python", "llama.cpp/convert_hf_to_gguf.py",
        checkpoint_dir,
        "--outfile", output_path,
        "--outtype", quantization,
    ], check=True)
```

## Hardware Requirements
- Fine-tuning requires a GPU with at least 16GB VRAM for the 270M parameter FunctionGemma model with LoRA (Unsloth reduces this significantly — can run on 8GB with Unsloth).
- If no GPU is available, use a cloud instance (A10G or T4 is sufficient).
- GGUF conversion can run on CPU and is fast (~1 minute per model).

## base_model.py Notes

```python
MODEL_ID = "google/functiongemma-4b"  # HuggingFace model ID
# Note: verify actual model ID from HuggingFace Hub — use the correct FunctionGemma variant

def load_base_model() -> tuple[PreTrainedModel, PreTrainedTokenizer]:
    # Cache to ~/.cache/huggingface by default
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype="auto")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    return model, tokenizer
```

## Makefile

```makefile
DOMAINS := lint test docstring sample_data

generate-%:
	python training/$*/generate_examples.py --count 200

generate-all: $(addprefix generate-,$(DOMAINS))

train-%:
	python training/$*/fine_tune.py
	python -c "from training.shared.gguf_export import export_to_gguf; \
	    export_to_gguf('training/$*/checkpoints/final', 'agents/$*/models/$*_functiongemma_q8.gguf')"

train-all: $(addprefix train-,$(DOMAINS))

eval-%:
	python training/$*/evaluate.py
```

## Implementation Notes
- Use Unsloth if available — it reduces VRAM requirements and speeds up training significantly on consumer hardware.
- The FunctionGemma model is already pre-trained for tool calling. Fine-tuning on domain-specific examples primarily teaches it the right tool sequencing for each domain, not how to call tools in general. This means fewer epochs and smaller datasets are needed than for general-purpose fine-tuning.
- Merge LoRA weights before GGUF export: `model = model.merge_and_unload()`.
- Run the GGUF through a quick smoke test after export (load it and call the model once) before considering the step complete.

## Testing Overview
- **Verification:** `make train-lint` completes without error and produces `agents/lint/models/lint_functiongemma_q8.gguf`.
- **Verification:** GGUF file is loadable: `python -c "from llama_cpp import Llama; Llama('agents/lint/models/lint_functiongemma_q8.gguf'); print('ok')"`.
- **Verification:** Loaded model responds to a sample lint tool call prompt with valid JSON tool call (not garbage).
- **Verification:** GGUF file size is in the expected range (~250–320MB for Q8 of 270M params).
- **Verification:** `make train-all` produces all four GGUF files.
