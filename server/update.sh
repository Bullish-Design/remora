#!/bin/bash
set -e

# One-command redeploy script.
#
# Run this after SSH-ing into the Tailscale sidecar:
#   ssh root@function-gemma-server
#   ./update.sh
#
# It pulls the latest server/ changes from Git, rebuilds the vLLM container,
# and tails the logs so you can confirm the model loads successfully.
# The base model is NOT re-downloaded (it lives in your /models/cache SSD volume).

echo "Pulling latest changes from Git..."
git pull origin main

echo "Rebuilding and restarting vLLM container..."
# --no-deps: only restart vllm-server, leave tailscale untouched
# (restarting tailscale would drop this SSH connection)
docker compose up -d --build --no-deps vllm-server

echo "Tailing vLLM logs — Ctrl+C to stop watching..."
docker logs -f vllm-gemma
