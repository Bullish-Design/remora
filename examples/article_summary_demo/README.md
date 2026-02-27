# Article Summary Demo

This example runs the article summary graph on a directory of Markdown files.
It uses two agents:

- `article_section_agent` summarizes each Markdown section node.
- `article_summary_agent` combines section summaries and can request human input.

## Run via the demo UI

From the repo root:

```bash
python demo/component_demo/run_demo.py \
  --config examples/article_summary_demo/remora.article.yaml \
  --project-root examples/article_summary_demo
```

Open `http://127.0.0.1:8425/demo/dashboard` and run a graph against `docs/`.
If the summary agent asks for input, respond in the blocked prompt panel.

## Run via CLI (non-interactive)

If you skip human input, you can run the graph directly:

```bash
remora run examples/article_summary_demo/docs \
  --config examples/article_summary_demo/remora.article.yaml
```

Note: the article summary agent can request human input. For a full
interactive run, use the demo UI.
