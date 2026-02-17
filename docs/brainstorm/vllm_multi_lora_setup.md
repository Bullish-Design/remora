# Windows vLLM Multi-LoRA Setup Guide

This guide helps you deploy a cluster of individually fine-tuned FunctionGemma 270M models using vLLM in Docker on Windows, exposed securely to your local Tailscale network.

## 1. Prerequisites
* **WSL2:** Installed and set as default (`wsl --set-default-version 2`).
* **Docker Desktop:** Installed with "Use the WSL 2 based engine" enabled.
* **NVIDIA Container Toolkit:** Usually bundled with Docker Desktop for Windows, but ensures your GPU is visible to containers.
* **Tailscale Auth Key:** Generate one from your [Tailscale Admin Console](https://login.tailscale.com/admin/settings/keys).

## 2. Project Structure
Create a folder named `vllm-cluster` and organize it as follows:

```text
vllm-cluster/
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
└── models/
    ├── base/
    │   └── function-gemma-270m/   # Base model weights
    └── adapters/
        ├── tool-use-1/            # Fine-tune folder 1
        └── tool-use-2/            # Fine-tune folder 2