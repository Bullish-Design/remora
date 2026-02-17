#!/bin/bash
set -e

# Start the vLLM OpenAI-compatible inference server.
#
# On first boot the model is pulled from Hugging Face and cached to
# /models/cache (mapped to your SSD via docker-compose.yml volumes).
# Subsequent boots load directly from the cache — no re-download.
#
# The server exposes the OpenAI-compatible API on port 8000.
# Reach it from any Tailscale-connected machine via:
#   http://function-gemma-server:8000/v1
#
# --max-num-seqs 256   : allow up to 256 concurrent sequences (safe for 270M)
# --enable-prefix-caching : cache shared system-prompt prefixes across requests
#                           (major throughput win for remora's repeated tool schemas)

python3 -m vllm.entrypoints.openai.api_server \
    --model google/function-gemma-3-270m \
    --max-num-seqs 256 \
    --enable-prefix-caching

    # -------------------------------------------------------------------------
    # MULTI-LORA CONFIGURATION
    # Uncomment this block once your fine-tuned LoRA adapters are trained and
    # placed in /models/adapters/ (mapped from your SSD in docker-compose.yml).
    #
    # Adapter names here must match the `model_id` values in remora.yaml.
    # -------------------------------------------------------------------------
    # --enable-lora \
    # --max-loras 20 \
    # --max-lora-rank 32 \
    # --lora-modules \
    #     lint=/models/adapters/lint \
    #     test=/models/adapters/test \
    #     docstring=/models/adapters/docstring \
    #     sample_data=/models/adapters/sample_data
