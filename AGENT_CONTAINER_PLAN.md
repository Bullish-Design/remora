# Agent Container Plan

A Tailscale-connected Docker container running OpenCode's web interface on a Windows PC, with GitHub repo sync and a full Linux development environment.

**Tailscale hostname:** `agents`
**Web interface:** `http://agents:8000`

---

## Table of Contents

1. [Concept](#1-concept)
2. [Architecture](#2-architecture)
3. [How the Existing Server Works](#3-how-the-existing-server-works)
4. [Container Design](#4-container-design)
5. [GitHub Repo Sync](#5-github-repo-sync)
6. [OpenCode Configuration](#6-opencode-configuration)
7. [NixOS Test Runner](#7-nixos-test-runner)
8. [Directory Layout](#8-directory-layout)
9. [Implementation Steps](#9-implementation-steps)
10. [Open Questions](#10-open-questions)

---

## 1. Concept

The goal is a persistent, headless OpenCode instance running inside a Docker container on a Windows PC. It:

- Joins your Tailscale network as `agents`, making the web UI accessible at `http://agents:8000` from any device on your tailnet
- Runs a full Linux filesystem (Ubuntu/Debian-based) so opencode has native file access, git, and shell tools
- Clones your GitHub repos into the container and keeps them in sync
- Serves the OpenCode web interface (`opencode web`) so you can interact with it from any browser on your tailnet
- Persists state (opencode sessions, git repos, config) across container restarts via Docker volumes

This is analogous to a cloud development environment (like Codespaces or Gitpod) but self-hosted on your own hardware, accessible only over Tailscale.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────┐
│  Windows PC (Docker Desktop / WSL2 backend)         │
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │  docker compose (agent-container/)           │    │
│  │                                              │    │
│  │  ┌──────────────────┐  ┌──────────────────┐  │    │
│  │  │  tailscale        │  │  opencode        │  │    │
│  │  │  (sidecar)        │  │  (main container)│  │    │
│  │  │                   │  │                   │  │    │
│  │  │  hostname: agents │  │  opencode web     │  │    │
│  │  │  SSH enabled      │◄─┤  --hostname 0.0.0│  │    │
│  │  │  port 8000 ←───────┤  --port 8000       │  │    │
│  │  │                   │  │                   │  │    │
│  │  │  /dev/net/tun     │  │  git, gh CLI      │  │    │
│  │  │  docker.sock      │  │  repos in /work/  │  │    │
│  │  └──────────────────┘  │  opencode config   │  │    │
│  │                         │  LLM API keys     │  │    │
│  │                         └──────────────────┘  │    │
│  │                                              │    │
│  │  Volumes:                                    │    │
│  │   tailscale-data → /var/lib/tailscale        │    │
│  │   repos          → /work                     │    │
│  │   opencode-data  → /home/dev/.local/share/   │    │
│  │                     opencode                 │    │
│  │   opencode-config→ /home/dev/.config/opencode│    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
└─────────────────────────────────────────────────────┘

       ▲ Tailscale network
       │
  http://agents:8000  ← any device on your tailnet
  ssh dev@agents      ← direct shell access
```

The pattern follows the existing `server/` setup exactly:
- A **tailscale sidecar** container owns the network identity
- The **opencode container** uses `network_mode: service:tailscale` to share the sidecar's network namespace
- Ports exposed on the opencode container appear on the Tailscale node

---

## 3. How the Existing Server Works

The current `server/` directory uses a three-container compose stack:

| Container | Image | Purpose | Network |
|-----------|-------|---------|---------|
| `tailscale` | `tailscale/tailscale:latest` + git/docker-cli | Tailscale node (`remora-server`), SSH access, can restart other containers | Owns the network namespace |
| `vllm-server` | `vllm/vllm-openai:latest` | LLM inference on port 8000 | `network_mode: service:tailscale` |
| `agents-server` | `python:3.11-slim` + FastAPI | Serves agent bundles on port 8001 | `network_mode: service:tailscale` |

Key patterns we reuse:
- **Tailscale sidecar** with `TS_AUTHKEY`, `TS_STATE_DIR`, `TS_SSH=true`, `cap_add: [net_admin, sys_module]`, `/dev/net/tun` mount
- **Docker socket mount** on the sidecar so `ssh root@agents` can manage containers
- **Named volumes** for persistent state (`tailscale-data`)
- **`.env` file** for secrets (auth keys, tokens)
- **`update.sh`** script for one-command redeploy via SSH

---

## 4. Container Design

### 4.1 Tailscale Sidecar

Nearly identical to `server/Dockerfile.tailscale`, but with hostname `agents` instead of `remora-server`.

```dockerfile
FROM tailscale/tailscale:latest
RUN apk update && apk add --no-cache git docker-cli docker-cli-compose bash
WORKDIR /app
```

### 4.2 OpenCode Container

This is the main workload. It uses a **NixOS-based image** (`nixos/nix`) with **devenv.sh** for environment management — consistent with all other projects in the ecosystem.

- **Base image:** `nixos/nix:latest` — provides the Nix package manager
- **Environment manager:** devenv.sh — all tools declared in `devenv.nix`
- **devenv.nix provides:** Node.js, git, GitHub CLI (`gh`), openssh, python3, curl, bash
- **opencode binary:** Installed via `npm install -g opencode-ai` inside the devenv shell (not in nixpkgs)
- **Non-root user:** `dev` — opencode should not run as root
- **Nix store volume:** `/nix` is persisted as a Docker volume to avoid rebuilding the environment on every restart

**Dockerfile approach:**
1. Start from `nixos/nix:latest`, enable flakes
2. Install devenv via `nix profile install`
3. Copy `devenv.nix` and `devenv.yaml` into the image
4. Pre-build the devenv environment (`devenv shell -- echo "done"`) to cache in the image layer
5. Install opencode via `devenv shell -- npm install -g opencode-ai`
6. Create non-root user `dev`, set up directories

**Entrypoint flow:**
1. Source Nix environment, ensure devenv is on PATH
2. Activate the devenv shell for all subsequent commands
3. Set up GitHub authentication (`gh auth login --with-token`)
4. Clone/pull configured repos into `/work/`
5. Start `opencode web --hostname 0.0.0.0 --port 8000` inside the devenv shell

**Key considerations:**
- `opencode web` starts both the HTTP server and the backend — it's a single process
- The `--hostname 0.0.0.0` flag makes it listen on all interfaces (required since the tailscale sidecar forwards traffic)
- `OPENCODE_SERVER_PASSWORD` should be set for auth (even on tailscale, defense in depth)
- The working directory when opencode starts determines which project it operates on

### 4.3 Multi-Repo Workspace

The container acts as a persistent workspace — the equivalent of a `Documents/Projects/` directory. The `/work` volume holds 5-10 repos side by side, each in its own subdirectory:

```
/work/
├── remora/
├── agent-sidecar/
├── my-app/
└── ...
```

**Repos are managed at runtime**, not at boot:
- Add a repo: `gh repo clone owner/repo /work/repo` (from opencode's bash tool or SSH)
- Remove a repo: `rm -rf /work/repo`
- No container restart needed for any repo operation

The entrypoint only sets up GitHub authentication. It does not clone anything — the `/work` volume persists repos across restarts, and new repos are added on demand.

OpenCode starts in `/work` and can see all project directories. It operates on whichever project you navigate to via the web UI.

---

## 5. GitHub Repo Sync

### 5.1 Authentication

GitHub CLI (`gh`) supports several auth methods. For a headless container, the best option is a **Personal Access Token (PAT)** or a **GitHub App installation token**.

```bash
# In entrypoint, before any git operations:
echo "$GITHUB_TOKEN" | gh auth login --with-token
gh auth setup-git  # configures git credential helper
```

This gives both `git` and `gh` access to your repos without SSH keys.

### 5.2 Runtime Repo Management

Repos are **not cloned at startup**. The `/work` volume is a persistent workspace. Add repos at any time from opencode's bash tool or via SSH:

```bash
# From opencode's bash tool or SSH into the container:
gh repo clone anomalyco/remora /work/remora
gh repo clone anomalyco/my-app /work/my-app

# Or use git directly:
git clone https://github.com/anomalyco/remora.git /work/remora
```

All repos persist across container restarts via the `repos` Docker volume. No restart is needed to add or remove repos.

### 5.3 Periodic Sync (Optional)

A background cron or loop that does `git fetch && git pull --ff-only` every N minutes. This keeps the container's copy fresh if you push from another machine. This is optional — opencode can also do git operations via its bash tool.

### 5.4 Push Support

Since opencode makes changes (edits files, creates commits), pushing back to GitHub requires write access. The PAT should have `repo` scope. Opencode's bash tool can run `git push` directly.

---

## 6. OpenCode Configuration

### 6.1 Config File

OpenCode reads `opencode.json` from the project root or `~/.config/opencode/opencode.json` globally. For the container, we set up a global config:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "server": {
    "port": 8000,
    "hostname": "0.0.0.0"
  },
  "provider": {
    "anthropic": {
      "options": {
        "apiKey": "{env:ANTHROPIC_API_KEY}"
      }
    }
  },
  "model": "anthropic/claude-sonnet-4-5",
  "permission": {
    "edit": "allow",
    "write": "allow",
    "bash": "allow"
  }
}
```

### 6.2 Environment Variables

All secrets are injected via `.env` file (never baked into the image):

| Variable | Purpose |
|----------|---------|
| `TS_AUTHKEY` | Tailscale auth key (reusable, ephemeral recommended) |
| `TS_HOSTNAME` | Tailscale node name (default: `agents`) |
| `GITHUB_TOKEN` | GitHub PAT with `repo` scope (for runtime repo cloning and pushing) |
| `ANTHROPIC_API_KEY` | LLM provider API key |
| `OPENCODE_SERVER_PASSWORD` | Web UI password |
| `OPENCODE_SERVER_USERNAME` | Web UI username (default: `opencode`) |

Additional provider keys (OpenAI, etc.) can be added as needed.

### 6.3 Persistence

Named Docker volumes ensure state survives container restarts:

| Volume | Mount Point | Contents |
|--------|------------|----------|
| `tailscale-data` | `/var/lib/tailscale` | Tailscale node identity and keys |
| `repos` | `/work` | Cloned git repositories |
| `opencode-data` | `/home/dev/.local/share/opencode` | Sessions, conversation history, project state |
| `opencode-config` | `/home/dev/.config/opencode` | Global opencode configuration |
| `nix-store` | `/nix` | Nix store — built packages, devenv environment cache |

---

## 7. NixOS Test Runner

### 7.1 Why Standalone

The NixOS test runner is a **separate Docker image**, not baked into the opencode container. Because the tailscale sidecar mounts the Docker socket (`/var/run/docker.sock`), any process with access to that socket — SSH sessions, opencode's bash tool, scripts, cron jobs, or even GitHub Actions self-hosted runners — can launch arbitrary containers on the host.

This means the test runner doesn't need to be a feature of the agent container. It's an independent tool that happens to be *launchable from* the agent container. This keeps both images focused and small:

- The **opencode container** stays a dev environment (editor, git, shell tools)
- The **test runner** stays a hermetic build/test environment (Nix, nothing else)

### 7.2 Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Docker Host (Windows PC / WSL2)                         │
│                                                          │
│  ┌─────────────────────────┐                             │
│  │  tailscale sidecar      │                             │
│  │  (has docker.sock)      │──── SSH session triggers ──┐│
│  └─────────────────────────┘                            ││
│                                                          ││
│  ┌─────────────────────────┐                            ││
│  │  opencode container     │                            ││
│  │  (bash tool triggers)   │──── opencode triggers ────┐││
│  └─────────────────────────┘                           │││
│                                                         │││
│  ┌─────────────────────────────────────────────────┐   │││
│  │  nixos-test-runner (ephemeral, --rm)             │◄──┘││
│  │                                                  │◄───┘│
│  │  1. Clone repo at specified git tag              │     │
│  │  2. Run nix-build / nix flake check / tests      │     │
│  │  3. Report results to stdout                     │     │
│  │  4. Exit (container removed automatically)       │     │
│  └─────────────────────────────────────────────────┘     │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

Each test run is a fresh, ephemeral container. No state leaks between runs. The `--rm` flag ensures automatic cleanup.

### 7.3 Runner Concept

The test runner takes a **GitHub repo** and a **git ref** (tag, branch, or commit SHA), clones the repo at that exact ref, and runs the Nix build/test pipeline. The interface is intentionally simple:

```bash
# From the sidecar via SSH:
./run-test.sh anomalyco/remora v1.2.3

# From opencode's bash tool:
/app/run-test.sh anomalyco/remora main

# With options:
./run-test.sh anomalyco/remora v1.2.3 --flake-check --timeout 600
```

The helper script (`run-test.sh`) wraps `docker run` with the right arguments:

```bash
docker run --rm \
  -e GITHUB_TOKEN="$GITHUB_TOKEN" \
  nixos-test-runner \
  "$REPO" "$GIT_REF" "$@"
```

### 7.4 Image Design

The NixOS test runner image:

- **Base:** NixOS-based (e.g., `nixos/nix:latest` or a custom Nix-on-Alpine image)
- **Installed:** Nix package manager, git, curl, GitHub CLI (for private repo access)
- **Entrypoint:** A script that clones, builds, tests, and exits
- **No Tailscale:** The runner doesn't need network identity — it runs, reports, and dies
- **No Docker socket:** The runner should not be able to launch further containers (least privilege)

### 7.5 Result Reporting

Results are reported via **stdout/stderr** by default — the calling process captures them. Additional options for richer reporting:

| Method | How | When to use |
|--------|-----|-------------|
| **stdout** (default) | `docker run` output streams to caller | Simple, synchronous runs |
| **File mount** | `-v /work/test-results:/output` | When you need persistent artifacts (logs, coverage) |
| **Tailscale network** (optional) | Runner joins tailnet for live streaming | Long-running builds where you want real-time progress |

For the initial implementation, stdout is sufficient. File mount for test artifacts can be added as a `--output-dir` flag to `run-test.sh`.

### 7.6 Scope Note

The NixOS test runner will get its own dedicated planning document later. This section provides context for how it fits into the agent container architecture — specifically, *why* the sidecar mounts docker.sock and how the helper script bridges the two. The actual runner image, its Nix configuration, and test pipeline design are out of scope for this plan.

---

## 8. Directory Layout

```
agent-container/
├── docker-compose.yml          # Two-service stack (tailscale + opencode)
├── Dockerfile.tailscale        # Tailscale sidecar (same pattern as server/)
├── Dockerfile.opencode         # Main opencode container
├── entrypoint.sh               # GitHub auth, repo sync, start opencode web
├── opencode.json               # Default opencode config (copied into image)
├── update.sh                   # One-command redeploy via SSH
├── run-test.sh                 # Helper to launch ephemeral NixOS test runner containers
├── .env.example                # Template for secrets
└── README.md                   # Setup and usage instructions
```

---

## 9. Implementation Steps

### Step 1: Scaffold the directory
Create `agent-container/` with the files listed above.

### Step 2: Dockerfile.tailscale
Copy from `server/Dockerfile.tailscale` — it's identical. The hostname is set via env var, not baked in.

### Step 3: devenv.nix
Write the devenv configuration declaring all tools: Node.js, git, gh, openssh, python3, curl, bash. opencode-ai is installed via npm in the enterShell hook (it's not in nixpkgs).

### Step 4: Dockerfile.opencode
Build the main container image:
- Base: `nixos/nix:latest`
- Enable flakes in nix.conf
- Install devenv via `nix profile install`
- Copy `devenv.nix` and `devenv.yaml`, pre-build the environment
- Install opencode: `devenv shell -- npm install -g opencode-ai`
- Create non-root user `dev` with home at `/home/dev`
- Copy `entrypoint.sh` and `opencode.json`
- Set `WORKDIR /work`

### Step 5: entrypoint.sh
Write the startup script:
1. Source Nix environment, ensure devenv is on PATH
2. Authenticate `gh` with `$GITHUB_TOKEN` (inside devenv shell)
3. List existing projects in `/work` (repos persist across restarts)
4. Start `opencode web --hostname 0.0.0.0 --port 8000` in `/work` inside devenv shell
5. Repos are added at runtime via `gh repo clone` — no clone at boot

### Step 6: docker-compose.yml
Two services:
- `tailscale` — sidecar with hostname `agents`, SSH enabled, docker socket, tun device
- `opencode` — main container, `network_mode: service:tailscale`, depends_on tailscale, env_file, volumes for repos/data/config/nix-store

### Step 6: .env.example and README
Document all required variables, setup steps, and verification commands.

### Step 7: update.sh
Script for SSH-in redeploy: `git pull && docker compose up -d --build --no-deps opencode`

### Step 8: run-test.sh
Helper script that wraps `docker run --rm` to launch ephemeral NixOS test runner containers. Takes a repo and git ref as arguments, passes through `$GITHUB_TOKEN` for private repo access. See [Section 7](#7-nixos-test-runner) for details.

### Step 9: Test
- `docker compose up -d --build`
- Verify tailscale joins: `docker exec tailscale-agents tailscale status`
- Verify opencode starts: `curl http://agents:8000/global/health`
- Open `http://agents:8000` in browser on tailnet

---

## 10. Open Questions

### Q1: ~~Single repo or multi-repo?~~ RESOLVED
Multi-repo workspace. The container is a persistent `Documents/Projects/` equivalent. Repos are managed at runtime via `gh repo clone` — no `GITHUB_REPO` env var, no clone at boot. The `/work` volume persists everything across restarts.

### Q2: Which LLM providers?
The config supports any provider opencode supports. The `.env` file can include keys for Anthropic, OpenAI, Google, or any other provider. We only need to decide which to configure by default. **Recommendation: Anthropic (Claude) as primary, with env vars for others.**

### Q3: Auto-update opencode?
OpenCode has an `autoupdate` config option. In a container, this is a tradeoff:
- **Auto-update ON:** Always latest opencode, but container state may change unexpectedly
- **Auto-update OFF:** Pin the version in the Dockerfile, update explicitly via rebuild

**Recommendation: OFF in the container. Pin version. Update via `update.sh` rebuild.**

### Q4: SSH access to the opencode container?
The tailscale sidecar provides SSH (`ssh root@agents`), but that lands in the Alpine sidecar, not the NixOS opencode container. Options:
- Install `openssh-server` in the opencode container and forward port 22 through tailscale
- Use `docker exec` from the sidecar (docker socket is mounted) to get a shell in the opencode container
- Use Tailscale SSH directly on the opencode container (requires running tailscaled there too — defeats the sidecar pattern)

**Recommendation: Use docker exec from the sidecar.** Add a helper alias: `ssh root@agents` → then `docker exec -it opencode-agent bash` to get a shell. The `update.sh` script can include this.

### Q5: Resource limits?
OpenCode itself is lightweight (Node.js process), but the bash tool can run arbitrary commands. Consider setting memory and CPU limits in docker-compose to prevent runaway processes from taking down the host.

### Q6: Git branch management?
When opencode makes changes, it can create branches and commits. The sync script should handle diverged branches gracefully. The simple `git pull --ff-only || true` approach avoids force-overwriting local changes but may leave the repo in a state where manual intervention is needed.

**Recommendation: Let opencode manage git entirely via its tools. The entrypoint just does the initial clone. Periodic sync is opt-in.**
