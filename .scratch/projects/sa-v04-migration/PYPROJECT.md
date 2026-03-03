# pyproject.toml Changes

## Diff

```diff
 [project]
 dependencies = [
     ...
-    "structured-agents>=0.3.4",
+    "structured-agents>=0.4.0",
     ...
 ]

 [tool.uv.sources]
-structured-agents = { git = "https://github.com/Bullish-Design/structured-agents.git", rev = "main" }
+structured-agents = { git = "https://github.com/Bullish-Design/structured-agents.git", tag = "v0.4.0" }
```

## Notes

- The `tag = "v0.4.0"` ensures you get exactly the v0.4.0 release
- Alternatively use `rev = "v0.4.0"` (same effect)
- For development against latest: `rev = "main"` (but may break)

## After Update

Run:
```bash
uv lock --upgrade-package structured-agents
uv sync
```

Then verify:
```bash
uv run python -c "import structured_agents; print(structured_agents.__version__)"
# Should print: 0.4.0
```
