"""Dashboard-specific components."""

from __future__ import annotations

import html
import json
import time
from dataclasses import dataclass, field
from typing import Any

from remora.ui.components.base import Component, Element, RawHTML
from remora.ui.components.data import List, ListItem, ProgressBar, StatusBadge
from remora.ui.components.layout import Card


@dataclass
class EventItem(Component):
    """A single event in the events list."""

    event: dict[str, Any]

    def render(self) -> str:
        timestamp = self.event.get("timestamp", 0)
        if timestamp:
            timestamp_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
        else:
            timestamp_str = "--:--:--"

        event_type = self.event.get("type", "")
        agent_id = self.event.get("agent_id", "")
        kind = self.event.get("kind", "")
        if hasattr(kind, "value"):
            kind = getattr(kind, "value")
        label = f"{kind}:{event_type}" if kind else event_type

        parts = [
            Element(tag="span", content=timestamp_str, class_="event-time").render(),
            Element(tag="span", content=label, class_="event-type").render(),
        ]

        if agent_id:
            parts.append(
                Element(tag="span", content=f"@{agent_id}", class_="event-agent").render()
            )

        return Element(
            tag="div",
            content=RawHTML("".join(parts)),
            class_="event",
        ).render()


@dataclass
class EventsList(Component):
    """List of recent events."""

    events: list[dict[str, Any]] = field(default_factory=list)
    max_display: int = 50

    def render(self) -> str:
        if not self.events:
            return List(
                id="events-list",
                class_="events-list",
                empty_message="No events yet",
            ).render()

        items = [EventItem(event) for event in reversed(self.events[-self.max_display :])]
        return List(
            items=items,
            id="events-list",
            class_="events-list",
        ).render()


@dataclass
class AgentStatusItem(Component):
    """A single agent status item."""

    agent_id: str
    state_info: dict[str, Any]

    def render(self) -> str:
        state = self.state_info.get("state", "pending")
        name = self.state_info.get("name", self.agent_id)

        badge = StatusBadge(status=state).render()
        name_el = Element(
            tag="span",
            content=name,
            class_="agent-name",
        ).render()

        return Element(
            tag="div",
            content=RawHTML(badge + name_el),
            class_="agent-item",
        ).render()


@dataclass
class AgentStatusList(Component):
    """List of agent statuses."""

    agent_states: dict[str, dict[str, Any]] = field(default_factory=dict)

    def render(self) -> str:
        if not self.agent_states:
            return List(
                id="agent-status",
                class_="agent-status",
                empty_message="No agents started yet",
            ).render()

        items = [
            AgentStatusItem(agent_id, info)
            for agent_id, info in self.agent_states.items()
        ]
        return List(
            items=items,
            id="agent-status",
            class_="agent-status",
        ).render()


@dataclass
class BlockedAgentCard(Component):
    """Card for a blocked agent awaiting input."""

    blocked: dict[str, Any]

    def render(self) -> str:
        agent_id = self.blocked.get("agent_id", "")
        question = self.blocked.get("question", "")
        options = self.blocked.get("options", [])
        request_id = self.blocked.get("request_id", "")

        key = f"{agent_id}:{question}".replace(":", "_").replace(" ", "_")

        if options:
            options_html = "".join(
                Element(tag="option", content=opt, attrs={"value": opt}).render()
                for opt in options
            )
            input_html = Element(
                tag="select",
                content=RawHTML(options_html),
                id=f"answer-{key}",
                data_attrs={"bind": f"responseDraft.{key}"},
            ).render()
        else:
            input_html = Element(
                tag="input",
                id=f"answer-{key}",
                attrs={"placeholder": "Your response", "type": "text"},
                data_attrs={"bind": f"responseDraft.{key}"},
                self_closing=True,
            ).render()

        escaped_request_id = request_id.replace("'", "\\'")
        button_html = Element(
            tag="button",
            content="Submit",
            attrs={"type": "button"},
            data_attrs={
                "on": "click",
                "on-click": f"""
                    const draft = $responseDraft?.{key}?.trim();
                    if (!draft) {{
                        alert('Response required.');
                        return;
                    }}
                    @post('/input', {{request_id: '{escaped_request_id}', response: draft}});
                """,
            },
        ).render()

        form = Element(
            tag="div",
            content=RawHTML(input_html + button_html),
            class_="response-form",
        ).render()

        agent_label = Element(
            tag="div",
            content=f"Agent: {html.escape(agent_id)}",
            class_="agent-id",
        ).render()

        question_el = Element(
            tag="div",
            content=question,
            class_="question",
        ).render()

        return Element(
            tag="div",
            content=RawHTML(agent_label + question_el + form),
            class_="blocked-agent",
        ).render()


@dataclass
class GraphLauncher(Component):
    """Graph launcher form."""

    recent_targets: list[str] = field(default_factory=list)
    bundle_default: str = ""

    def render(self) -> str:
        defaults = {
            "graphLauncher": {
                "target_path": "",
                "bundle": self.bundle_default or "",
            }
        }
        signals_attr = html.escape(json.dumps(defaults), quote=True)

        target_input = Element(
            tag="input",
            attrs={
                "placeholder": "Target path (file or directory)",
                "type": "text",
                "id": "target-path",
                "autocomplete": "off",
            },
            data_attrs={"bind": "graphLauncher.target_path"},
            self_closing=True,
        ).render()

        bundle_input = Element(
            tag="input",
            attrs={
                "placeholder": "Bundle name (e.g., lint, docstring)",
                "type": "text",
            },
            data_attrs={"bind": "graphLauncher.bundle"},
            self_closing=True,
        ).render()

        run_button = Element(
            tag="button",
            content="Run Graph",
            attrs={"type": "button"},
            data_attrs={
                "on": "click",
                "on-click": """
                    const target = $graphLauncher?.target_path?.trim();
                    const bundle = $graphLauncher?.bundle?.trim() || 'lint';
                    if (!target) {
                        alert('Target path is required.');
                        return;
                    }
                    @post('/run', {target_path: target, bundle: bundle});
                """,
            },
        ).render()

        root_button = Element(
            tag="button",
            content="Run Root Graph",
            attrs={"type": "button"},
            data_attrs={
                "on": "click",
                "on-click": """
                    const bundle = $graphLauncher?.bundle?.trim() || 'lint';
                    @post('/run', {target_path: '.', bundle: bundle});
                """,
            },
        ).render()

        form = Element(
            tag="div",
            content=RawHTML(target_input + bundle_input + run_button + root_button),
            class_="graph-launcher-form",
        ).render()

        signals_div = Element(
            tag="div",
            content="",
            attrs={"style": "display:none"},
            data_attrs={"signals__ifmissing": signals_attr},
        ).render()

        recent_panel = ""
        if self.recent_targets:
            recent_buttons = "".join(
                Element(
                    tag="button",
                    content=target,
                    attrs={"type": "button"},
                    class_="recent-target",
                    data_attrs={
                        "on": "click",
                        "on-click": f"$graphLauncher.target_path = '{self._escape_js(target)}';",
                    },
                ).render()
                for target in self.recent_targets
            )
            recent_panel = Element(
                tag="div",
                content=RawHTML(
                    Element(tag="div", content="Recent targets", class_="recent-label").render()
                    + recent_buttons
                ),
                class_="recent-targets",
            ).render()

        return Card(
            title="Run Agent Graph",
            content=RawHTML(form + recent_panel + signals_div),
            class_="card graph-launcher-card",
        ).render()

    @staticmethod
    def _escape_js(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


@dataclass
class ResultsList(Component):
    """List of agent results."""

    results: list[dict[str, Any]] = field(default_factory=list)
    max_display: int = 10

    def render(self) -> str:
        if not self.results:
            return List(
                id="results-list",
                class_="results",
                empty_message="No results yet",
            ).render()

        items: list[ListItem] = []
        for result in self.results[: self.max_display]:
            agent_el = Element(
                tag="div",
                content=result.get("agent_id", ""),
                class_="result-agent",
            ).render()
            content_el = Element(
                tag="div",
                content=result.get("content", ""),
                class_="result-content",
            ).render()
            items.append(
                ListItem(
                    content=RawHTML(agent_el + content_el),
                    class_="result-item",
                )
            )

        return List(
            items=items,
            id="results-list",
            class_="results",
        ).render()


__all__ = [
    "AgentStatusList",
    "BlockedAgentCard",
    "EventItem",
    "EventsList",
    "GraphLauncher",
    "ResultsList",
]
