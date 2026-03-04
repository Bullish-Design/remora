# server/ Documentation Analysis

## Files

### server/README.md (53 lines) — **KEEP, REVISE**
- Quick reference for the vLLM server stack.
- Docker compose setup, verification, agents server, adapter hot-loading.
- References Docker Desktop WSL2, Tailscale, Hugging Face.
- This is infrastructure documentation for the vLLM deployment.
- Useful but specific to the deployment setup. Should stay in server/.
- Minor revision: verify commands still work.

### server/SERVER_DEV_GUIDE.md (~200+ lines) — **KEEP, REVISE**
- Step-by-step dev guide for building the server/ directory.
- References VLLM_REFACTOR.md (now in .hidden/), Windows/Linux dual machine setup.
- Detailed with verification steps for each phase.
- May be partially stale — references old docs and possibly old architecture.
- Should stay in server/ as the deployment guide.

## Recommendation
Both files belong in server/. Minor revisions needed to update references and verify accuracy.
