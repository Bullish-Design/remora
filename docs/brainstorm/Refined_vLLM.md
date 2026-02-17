# Refined vLLM Concept

This `CONCEPT_SUMMARY` consolidates the technical decisions and architectural plan for serving multiple fine-tuned **FunctionGemma 270M** models with high throughput on local hardware.

---

## CONCEPT_SUMMARY: High-Throughput Multi-LoRA Inference System

### 1. Core Objective

The goal is to serve dozens of specialized, fine-tuned versions of the **FunctionGemma 270M** model simultaneously. The system must handle a constant stream of asynchronous requests with minimal latency and maximum GPU saturation, leveraging local hardware with high VRAM capacity.

### 2. The Primary Engine: vLLM

**vLLM** was selected as the inference framework over Ollama due to its superior handling of high-concurrency workloads and specialized memory management.

| Feature | Implementation | Benefit |
| --- | --- | --- |
| **PagedAttention** | Partitions KV Cache into non-contiguous "pages." | Eliminates memory fragmentation; allows hundreds of concurrent sequences. |
| **Continuous Batching** | Iteration-level scheduling. | New requests are injected into the GPU cycle immediately when a slot opens, preventing idle time. |
| **Multi-LoRA** | One base model + multiple tiny adapters. | Minimizes VRAM usage; allows "brain-swapping" without reloading full model weights. |
| **Chunked Prefill** | Breaks large prompts into smaller chunks. | Prevents large inputs from "stalling" the generation of other active requests. |
| **Prefix Caching** | Caches redundant system prompts. | Drastically speeds up "Time to First Token" for repeated instructions. |

---

### 3. Deployment & Networking Architecture

To ensure stability on Windows and accessibility across a local network, the system uses a containerized approach.

* **Environment:** **WSL2** (Windows Subsystem for Linux) provides the Linux kernel and NVIDIA GPU pass-through required for vLLM.
* **Containerization:** **Docker Desktop** manages the lifecycle of the inference server.
* **Networking (Tailscale Sidecar):** * A Tailscale container acts as a "network gateway" for the vLLM container.
* The vLLM container uses `network_mode: service:tailscale`, appearing as a unique node (e.g., `function-gemma-server`) on the Tailscale mesh VPN.
* This bypasses Windows host-firewall issues and provides secure, encrypted access from any device on the network.



---

### 4. Storage & Memory Management

The configuration is optimized for a multi-SSD setup to ensure data bottlenecks don't throttle the GPU.

* **Model Storage:** Base models are stored on the fastest NVMe drive (mapped via `/mnt/d/` in WSL) to speed up initial VRAM loading.
* **Adapter Storage:** LoRA adapters are stored on secondary SSDs.
* **Cache Redirection:** Both `VLLM_CACHE_ROOT` and `HF_HOME` environment variables are pointed to a dedicated SSD folder to prevent the Windows system (C:) drive from filling up with metadata and temporary files.

---

### 5. Final Agreed Configuration Parameters

The vLLM server will be launched with the following optimized flags for the FunctionGemma 270M:

* **`--model`**: Path to the base FunctionGemma 270M weights.
* **`--enable-lora`**: Activates the Multi-LoRA kernel.
* **`--max-loras`**: Set to ~20 (adjustable based on the number of active tasks).
* **`--max-lora-rank`**: 32 (to support complex fine-tunes).
* **`--max-num-seqs`**: 256 (leveraging the tiny 270M footprint for massive concurrency).
* **`--enable-prefix-caching`**: Enabled to handle repetitive async prompts efficiently.

---

### 6. Workflow Summary

1. **Fine-Tuning:** Users create LoRA adapters locally using libraries like `peft`.
2. **Request:** An async client sends a request to `http://function-gemma-server:8000/v1/chat/completions`.
3. **Routing:** The `model` parameter in the API call specifies which adapter (e.g., `sql-adapter`) to use.
4. **Inference:** vLLM dynamically applies the adapter weights to the base model in the current batch and returns the result.



---


## Files

Here are the complete, ready-to-run files to verify your local infrastructure.

To ensure this works "off the bat" without crashing, the `entrypoint.sh` is configured to serve **only the base model** by pulling it directly from Hugging Face and caching it to your SSD. The Multi-LoRA arguments are included but commented out so you can easily toggle them on once your adapters are trained.

### 1. The Docker Configuration

Create a new directory (e.g., `vllm-test-env`) and save the following three files inside it.

**`docker-compose.yml`**
This file handles the Tailscale sidecar network and maps your physical Windows SSD paths into the container.

```yaml
version: '3.8'

services:
  tailscale:
    image: tailscale/tailscale:latest
    container_name: tailscale-vllm
    hostname: function-gemma-server
    environment:
      # TODO: Replace with your actual Tailscale Auth Key
      - TS_AUTHKEY=tskey-auth-YOUR_KEY_HERE 
      - TS_STATE_DIR=/var/lib/tailscale
    volumes:
      - tailscale-data:/var/lib/tailscale
      - /dev/net/tun:/dev/net/tun
    cap_add:
      - net_admin
      - sys_module
    restart: unless-stopped

  vllm-server:
    build: .
    container_name: vllm-gemma
    network_mode: service:tailscale
    depends_on:
      - tailscale
    environment:
      # TODO: Add your Hugging Face token if the model requires authentication
      - HUGGING_FACE_HUB_TOKEN=hf_YOUR_TOKEN_HERE
      # Redirect downloads to the high-speed SSD cache
      - VLLM_CACHE_ROOT=/models/cache
      - HF_HOME=/models/cache
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      # TODO: Adjust these paths to match your actual Windows SSD drive letters (e.g., /mnt/d/)
      - /mnt/d/AI_Models/base:/models/base
      - /mnt/e/AI_Models/adapters:/models/adapters
      - /mnt/d/AI_Models/cache:/models/cache
    # Added ipc: host to prevent shared memory limits from crashing vLLM
    ipc: host 
    restart: unless-stopped

volumes:
  tailscale-data:

```

**`Dockerfile`**
A minimal wrapper around the official image to inject our startup script.

```dockerfile
FROM vllm/vllm-openai:latest

WORKDIR /app
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]

```

**`entrypoint.sh`**
The launch script. Notice the LoRA flags are safely disabled for this verification run.

```bash
#!/bin/bash

# We use the Hugging Face repo ID so it downloads automatically for this test.
# It will be saved permanently to your /models/cache folder on your SSD.

python3 -m vllm.entrypoints.openai.api_server \
    --model google/function-gemma-3-270m \
    --max-num-seqs 256 \
    --enable-prefix-caching
    
    # ---------------------------------------------------------
    # MULTI-LORA CONFIGURATION (Uncomment when adapters are ready)
    # ---------------------------------------------------------
    # --enable-lora \
    # --max-loras 20 \
    # --max-lora-rank 32 \
    # --lora-modules \
    #     sql-adapter=/models/adapters/sql-adapter \
    #     email-adapter=/models/adapters/email-adapter

```

> **To Start the Server:** > Open your terminal in the directory containing these files and run: `docker compose up -d --build`. You can watch the model download and load into VRAM by checking the logs: `docker logs -f vllm-gemma`.

---

### 2. The Verification Script (`test_connection.py`)

This Python script uses PEP 723 inline metadata. Because you are using `uv`, you do not need to set up a virtual environment or run `pip install`. `uv` will read the header, create an ephemeral, isolated environment, install the `openai` package, run the script, and clean up after itself in a fraction of a second.

Save this file anywhere on a machine connected to your Tailscale network:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "openai",
# ]
# ///

import asyncio
from openai import AsyncOpenAI

# Pointing to the Tailscale hostname we defined in the compose file
SERVER_URL = "http://function-gemma-server:8000/v1"
MODEL_NAME = "google/function-gemma-3-270m"

async def test_base_model():
    print(f"🔄 Attempting to connect to vLLM at {SERVER_URL} over Tailscale...")
    
    # Initialize the async client
    client = AsyncOpenAI(
        base_url=SERVER_URL,
        api_key="EMPTY" # vLLM does not require an API key by default
    )

    try:
        # Fire off a single request to verify the base model is functioning
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a highly efficient assistant."},
                {"role": "user", "content": "Please reply with the exact phrase: 'Connection successful. The base model is active.'"}
            ],
            max_tokens=20,
            temperature=0.1
        )
        
        reply = response.choices[0].message.content.strip()
        print("\n✅ SUCCESS! Received response from the container:")
        print(f"🤖 Model Says: {reply}")

    except Exception as e:
        print(f"\n❌ FAILED TO CONNECT OR GENERATE: {e}")
        print("Check if the container is fully booted and your Tailscale connection is active.")

if __name__ == "__main__":
    asyncio.run(test_base_model())

```

> **To Run the Script:**
> Simply execute it using the `uv` runner:
> `uv run test_connection.py`

---

## Linux Development <-> Windows Running System


User: 
The development will take place on a linux system. Whats a good way to minimize the amount of "development on windows" that the user will have to deal with? Ideally they'll just edit any code locally on linux, push to github, then ssh to the tailscale sidecar and run a single command to update and restart everything. What else am I missing in order to be able to have this development workflow for setting up this system?

Again - the OS must remain windows, but all development and code will ideally be linux based, so living within docker containers. But the user doesn't want to have to actually interact with the windows environment if at all possible (aside from making sure docker is running, of course)

---

Agent:
This is a fantastic approach. You essentially want to treat the Windows machine as a headless, dumb appliance and do all your actual "living" inside a seamless Linux environment over the network.

To achieve this "SSH in, pull, and restart" workflow purely through Docker without ever touching the Windows desktop, you are currently missing four key infrastructural bridges.

Here is exactly what you need to add to your setup to make this workflow a reality.

---

### The 4 Missing Links

1. **Tailscale SSH (`TS_SSH=true`):** You need an SSH server. Tailscale has a brilliant built-in feature that allows keyless SSH directly into a node using your Tailscale identity. We need to enable this on the sidecar.
2. **Docker Socket Passthrough:** If you SSH into a container, that container is trapped. To let it restart the *other* containers (like vLLM), you must mount the host's Docker socket (`/var/run/docker.sock`) inside the Tailscale container. This gives the container permission to act as a remote control for the host's Docker daemon.
3. **The Deployment Tools:** The official Tailscale Docker image is extremely minimal (based on Alpine Linux). It doesn't have `git` or the `docker` CLI installed. We need to build a slightly upgraded sidecar.
4. **Project Directory Mapping:** The sidecar needs to be able to see your `docker-compose.yml` and project files so it can run `git pull`.

---

### The "Ops-Ready" Implementation

Here is how we adapt your existing architecture to support this exact developer workflow.

#### 1. Create a `Dockerfile.tailscale`

Instead of using the raw Tailscale image, we will wrap it to install Git and the Docker CLI. Create this file in your project root:

```dockerfile
FROM tailscale/tailscale:latest

# Install Git, Docker CLI, and Docker Compose plugin into the Alpine container
RUN apk update && \
    apk add --no-cache git docker-cli docker-cli-compose bash

# Create an app directory
WORKDIR /app

```

#### 2. Update your `docker-compose.yml`

We will update the `tailscale` service to build from our new Dockerfile, enable SSH, and mount the necessary files.

```yaml
version: '3.8'

services:
  tailscale:
    build: 
      context: .
      dockerfile: Dockerfile.tailscale # Use our new custom image
    container_name: tailscale-vllm
    hostname: function-gemma-server
    environment:
      - TS_AUTHKEY=tskey-auth-YOUR_KEY_HERE
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_SSH=true # 1. ENABLE TAILSCALE SSH
    volumes:
      - tailscale-data:/var/lib/tailscale
      - /dev/net/tun:/dev/net/tun
      # 2. MOUNT THE DOCKER SOCKET (Allows controlling Docker from inside)
      - /var/run/docker.sock:/var/run/docker.sock 
      # 3. MOUNT THE PROJECT DIRECTORY
      - .:/app 
    cap_add:
      - net_admin
      - sys_module
    restart: unless-stopped

  vllm-server:
    # ... (Keep your vllm-server configuration exactly as it was) ...

```

#### 3. Create the `update.sh` Deployment Script

Create this simple bash script in your project root. This is the "single command" you will run via SSH.

```bash
#!/bin/bash
# update.sh

echo "⬇️ Pulling latest changes from Git..."
git pull origin main

echo "🔄 Rebuilding and restarting containers..."
# Because we mapped the docker.sock, this command will affect the host system
docker compose up -d --build vllm-server

echo "✅ Update complete. Tailing logs for vLLM..."
docker logs -f vllm-gemma

```

*Note: Make sure to run `chmod +x update.sh` so it is executable.*

---

### Your New Workflow in Action

Once you boot this up via Windows Docker Desktop that *one final time*, you never have to look at Windows again. Your workflow becomes:

1. **Develop locally** on your Linux machine.
2. **Commit and push** your changes to GitHub (e.g., tweaked a prompt, changed the `entrypoint.sh`, added a new LoRA adapter to the download list).
3. **Deploy via Terminal:**
```bash
# SSH directly into the Tailscale container (Tailscale handles the keys!)
ssh root@function-gemma-server

# Run your update script
./update.sh

```


