#!/bin/bash

python3 -m vllm.entrypoints.openai.api_server \
    --model /models/base/function-gemma-270m \
    --enable-lora \
    --max-loras 10 \
    --max-num-seqs 128 \
    --lora-modules \
        task-alpha=/models/adapters/tool-use-1 \
        task-beta=/models/adapters/tool-use-2