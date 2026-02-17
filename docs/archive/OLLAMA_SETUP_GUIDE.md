# [ARCHIVED] Ollama Setup Guide
This guide applied to the pre-vLLM version of remora. See docs/SERVER_SETUP.md for the current setup procedure.

Remora uses the stock FunctionGemma model (`functiongemma:270m`, 270M parameters) via Ollama, accessed through the Python `llm` library. This guide covers two deployment scenarios:

- **Local** — Ollama runs on the same NixOS machine as Remora
- **Remote** — Ollama runs in a Windows Docker container, reachable over your Tailscale network

---

## Model: `functiongemma:270m`

FunctionGemma is Google's 270M-parameter model purpose-built for structured tool calling. Built on the Gemma 3 270M architecture, it uses a different chat format optimized for function calling. At 301MB (Q8_0 quantized), it runs on a single CPU core with no GPU requirement. Remora uses it as the backend for all subagents (lint, test, docstring, sample_data).

FunctionGemma is not intended for use as a direct dialogue model — it is designed for function calling tasks and performs best after fine-tuning on domain-specific data.

Ollama model name: `functiongemma:270m`
Remora model ID: `ollama/functiongemma:270m`

> **Requires Ollama v0.13.5 or later.**

---

## Option A: Local NixOS

### 1. Install Ollama

Add Ollama to your NixOS configuration:

```nix
# /etc/nixos/configuration.nix  (or your flake equivalent)
services.ollama = {
  enable = true;
  # host = "0.0.0.0";  # uncomment if you want to expose on the network
};
```

Apply the configuration:

```bash
sudo nixos-rebuild switch
```

Alternatively, install Ollama imperatively for the current user session:

```bash
nix-shell -p ollama
# or, with flakes:
nix run nixpkgs#ollama -- serve
```

Verify the service is running:

```bash
systemctl status ollama        # if using NixOS services
# or
curl http://localhost:11434/api/tags
```

### 2. Pull the FunctionGemma model

```bash
ollama pull functiongemma:270m
```

Verify it was pulled:

```bash
ollama list
# functiongemma:270m should appear in the output
```

### 3. Quick smoke test

```bash
ollama run functiongemma:270m "Call the greet tool with name=world"
```

### 4. Install the `llm` Ollama plugin

After installing and activating your Remora Python environment:

```bash
llm install llm-ollama
```

Verify the model is reachable through `llm`:

```bash
llm -m ollama/functiongemma:270m "Say hello"
```

### 5. Remora config

No changes needed — `ollama/functiongemma:270m` is the default. Your `remora.yaml` can omit `model_id` entirely, or be explicit:

```yaml
model_id: "ollama/functiongemma:270m"
```

Ollama is expected at `http://localhost:11434` (the default). No additional configuration is required for local mode.

---

## Option B: Remote Windows Docker Container (Tailscale)

This setup runs the Ollama Docker container on a Windows machine and accesses it from your NixOS dev machine over Tailscale.

### On the Windows machine

#### 1. Install Docker Desktop

Download and install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).

#### 2. Create the Dockerfile

Copy the quick start Dockerfile from this repo (`Dockerfile.ollama.quickstart`) to your Windows machine, or create a new file with the same contents in a working directory.

#### 3. Build the Ollama image

Open PowerShell in the directory with the Dockerfile and run:

```powershell
docker build -t remora-ollama -f Dockerfile.ollama.quickstart .
```

#### 4. Run the Ollama container

```powershell
docker run -d `
  --name ollama `
  -p 11434:11434 `
  -v ollama-data:/root/.ollama `
  remora-ollama
```

This starts Ollama listening on port 11434, with model data persisted in a Docker volume. The image already includes `functiongemma:270m`.

#### 5. Verify the model inside the container

```powershell
docker exec ollama ollama list
```

#### 6. Configure Windows Firewall

Allow inbound TCP on port 11434 so Tailscale peers can reach the container:

```powershell
New-NetFirewallRule `
  -DisplayName "Ollama Tailscale" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 11434 `
  -Action Allow
```

#### 7. Find the Windows machine's Tailscale IP

In PowerShell:

```powershell
tailscale ip -4
# Example output: 100.x.y.z
```

Note this IP — you will use it in the next section.

#### 8. Verify from the Windows machine

```powershell
curl http://localhost:11434/api/tags
```

### On the NixOS dev machine

#### 9. Verify Tailscale connectivity

```bash
curl http://<TAILSCALE_IP>:11434/api/tags
# Should return a JSON list of available models
```

#### 10. Configure the `llm` Ollama plugin to use the remote host

The `llm-ollama` plugin reads the `OLLAMA_HOST` environment variable:

```bash
export OLLAMA_HOST=http://<TAILSCALE_IP>:11434
```

Add this to your shell profile (`~/.bashrc`, `~/.zshrc`, or your devenv shell config) so it persists:

```bash
# ~/.bashrc or ~/.zshrc
export OLLAMA_HOST=http://<TAILSCALE_IP>:11434
```

#### 11. Verify the model is reachable through `llm`

```bash
llm -m ollama/functiongemma:270m "Say hello"
```

#### 12. Remora config for remote Ollama

Add the `OLLAMA_HOST` environment variable to your shell before running `remora`, or set it in your `devenv.nix`:

```nix
# devenv.nix
env.OLLAMA_HOST = "http://<TAILSCALE_IP>:11434";
```

Your `remora.yaml` stays the same — `ollama/functiongemma:270m` works regardless of where Ollama is running, as long as `OLLAMA_HOST` points at the right machine.

```yaml
model_id: "ollama/functiongemma:270m"
```

---

## Verifying the full Remora integration

Once Ollama is running (locally or remotely) and `llm-ollama` is installed, verify everything is wired correctly:

```bash
# Check that Remora can see the model
remora list-agents

# Expected output (table format):
# Agent       | YAML            | YAML     | Model                       | Available
# ----------- | --------------- | -------- | --------------------------- | ----------
# lint        | agents/lint/... | ✓ found  | ollama/functiongemma:270m   | ✓ ready
# test        | agents/test/... | ✓ found  | ollama/functiongemma:270m   | ✓ ready
# docstring   | agents/doc../.. | ✓ found  | ollama/functiongemma:270m   | ✓ ready
```

If any agent shows `✗ unavailable`, check:

1. Ollama is running (`curl $OLLAMA_HOST/api/tags` or `curl http://localhost:11434/api/tags`)
2. The model was pulled (`ollama list` on the machine running Ollama)
3. `OLLAMA_HOST` is set correctly for the remote case
4. `llm-ollama` is installed (`llm plugins` should list `llm-ollama`)

---

## Quick reference

| Scenario | Ollama URL | Set env var? |
|---|---|---|
| Local NixOS | `http://localhost:11434` | No (default) |
| Remote Windows/Docker via Tailscale | `http://<TAILSCALE_IP>:11434` | `OLLAMA_HOST=http://<TAILSCALE_IP>:11434` |

| Command | Purpose |
|---|---|
| `ollama pull functiongemma:270m` | Download the model |
| `ollama list` | List available models |
| `llm install llm-ollama` | Install the llm Ollama plugin |
| `llm -m ollama/functiongemma:270m "hello"` | Verify model is reachable via llm |
| `remora list-agents` | Verify Remora can reach the model |
| `curl $OLLAMA_HOST/api/tags` | Check Ollama API is responding |
