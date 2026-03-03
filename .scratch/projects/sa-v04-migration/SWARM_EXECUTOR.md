# swarm_executor.py Migration

This file documents the import changes needed for `src/remora/core/swarm_executor.py`.

## Import Changes

### Before (v0.3 - Broken)

```python
from structured_agents.agent import load_manifest    # BROKEN - module deleted
from structured_agents.client import build_client
from structured_agents.types import Message
```

### After (v0.4 - Fixed)

```python
from structured_agents import build_client, Message
from remora.core.manifest import load_manifest       # Local implementation
```

## Full Context

The swarm_executor.py file uses these from structured-agents:

| Import | v0.3 Location | v0.4 Location | Action |
|--------|---------------|---------------|--------|
| `load_manifest` | `structured_agents.agent` | **DELETED** | Use `remora.core.manifest` |
| `build_client` | `structured_agents.client` | `structured_agents` | Update import |
| `Message` | `structured_agents.types` | `structured_agents` | Update import |

## Diff

```diff
-from structured_agents.agent import load_manifest
-from structured_agents.client import build_client
-from structured_agents.types import Message
+from structured_agents import build_client, Message
+from remora.core.manifest import load_manifest
```

## Manifest Usage in swarm_executor.py

The file accesses these manifest attributes (all supported by our `BundleManifest`):

```python
# Line 108
manifest.name

# Lines 225, 227, 231
manifest.agents_dir

# Lines 310, 327
manifest.grammar_config
manifest.grammar_config.send_tools_to_api

# Line 317
manifest.system_prompt

# Line 215
manifest.requires_context

# Line 329 (via getattr with default)
getattr(manifest, "max_turns", None)
```

All of these are supported by our `BundleManifest` dataclass.
