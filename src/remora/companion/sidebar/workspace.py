"""Workspace panels for companion sidebar rendering."""

from __future__ import annotations

from dataclasses import dataclass

from remora.core.agents.workspace import AgentWorkspace


@dataclass
class WorkspacePanel:
    key: str
    title: str
    content: str
    is_empty: bool


async def _read_panel_text(workspace: AgentWorkspace, path: str) -> tuple[str, bool]:
    try:
        content = await workspace.read(path)
    except Exception:
        return "", True
    text = content or ""
    return text, not bool(text.strip())


async def build_workspace_panels(workspace: AgentWorkspace) -> list[WorkspacePanel]:
    """Build workspace panels sourced from bootstrap identity files."""
    panels: list[WorkspacePanel] = []

    role, role_empty = await _read_panel_text(workspace, "role.md")
    panels.append(WorkspacePanel(key="role", title="Role", content=role, is_empty=role_empty))

    schema, schema_empty = await _read_panel_text(workspace, "schema.yaml")
    panels.append(WorkspacePanel(key="schema", title="Schema", content=schema, is_empty=schema_empty))

    notes, notes_empty = await _read_panel_text(workspace, "notes.md")
    panels.append(WorkspacePanel(key="notes", title="Notes", content=notes, is_empty=notes_empty))

    summary, summary_empty = await _read_panel_text(workspace, "summary.md")
    panels.append(WorkspacePanel(key="summary", title="Summary", content=summary, is_empty=summary_empty))

    todo, todo_empty = await _read_panel_text(workspace, "todo.md")
    panels.append(WorkspacePanel(key="todo", title="Todo", content=todo, is_empty=todo_empty))

    log_text, log_empty = await _read_panel_text(workspace, "log.jsonl")
    if not log_empty:
        lines = [line for line in log_text.splitlines() if line.strip()]
        log_text = "\n".join(lines[-20:])
    panels.append(WorkspacePanel(key="log", title="Log", content=log_text, is_empty=log_empty))

    tools_content = ""
    tools_empty = True
    try:
        files = await workspace.list_dir("tools")
        pym_files = sorted(name for name in files if name.endswith(".pym"))
        if pym_files:
            tools_content = "\n".join(f"- `{name}`" for name in pym_files)
            tools_empty = False
    except Exception:
        pass
    panels.append(WorkspacePanel(key="tools", title="Tools", content=tools_content, is_empty=tools_empty))

    return panels


__all__ = ["WorkspacePanel", "build_workspace_panels"]
