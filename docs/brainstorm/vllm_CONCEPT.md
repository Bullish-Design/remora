# Architectural Concept: High-Throughput Tiny Model Serving

## The Philosophy
Serving many "tiny" models (like the 270M FunctionGemma) requires a different approach than serving one massive 70B model. Instead of worrying about VRAM capacity, the bottleneck becomes **request scheduling** and **I/O overhead**.



## Key Components

### 1. vLLM & Continuous Batching
Standard inference servers (like Flask/FastAPI wrappers) process requests in a "Stop-and-Wait" fashion. vLLM uses **Continuous Batching**. It doesn't wait for a whole batch to finish; it schedules new requests at the token level. For 270M models, this allows you to saturate the GPU with hundreds of concurrent streams without meaningful latency degradation.

### 2. Multi-LoRA Strategy
Loading 10 separate 270M models would waste memory and compute. By using **LoRA (Low-Rank Adaptation)**:
* **Base Weights:** The "intelligence" of Gemma is loaded once.
* **Adapters:** Only the specialized "fine-tuned" delta layers are swapped. 
vLLM handles this "hot-swapping" in the CUDA kernel, meaning `Adapter A` and `Adapter B` can be processed in the same GPU batch.

### 3. Tailscale Networking (The Sidecar)


By using a Tailscale container as a "network sidecar," the vLLM server inherits a unique identity on your private mesh VPN. 
* **Zero Port Forwarding:** You don't have to open ports on your Windows firewall.
* **Internal DNS:** You can hit the server at `http://gemma-engine:8000` from your laptop, phone, or another server anywhere in the world.

### 4. WSL2 & Docker
WSL2 provides the Linux kernel features (like `virtio-net` and proper CUDA IPC) that vLLM requires, while Docker ensures that the complex Python dependency tree doesn't conflict with your Windows host environment.