"""Data display components."""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from remora.ui.components.base import Component, Element, RawHTML


@dataclass
class ListItem(Component):
    """A single list item."""

    content: Component | str
    class_: str | None = None

    def render(self) -> str:
        content = self.content.render() if isinstance(self.content, Component) else html.escape(str(self.content))
        return Element(
            tag="div",
            content=RawHTML(content),
            class_=self.class_,
        ).render()


@dataclass
class List(Component):
    """A list of items."""

    items: list[Component | str] = field(default_factory=list)
    id: str | None = None
    class_: str | None = None
    empty_message: str = "No items"

    def render(self) -> str:
        if not self.items:
            return Element(
                tag="div",
                content=Element(
                    tag="div",
                    content=self.empty_message,
                    class_="empty-state",
                ),
                id=self.id,
                class_=self.class_,
            ).render()

        items_html = "".join(
            item.render() if isinstance(item, Component) else html.escape(str(item))
            for item in self.items
        )

        return Element(
            tag="div",
            content=RawHTML(items_html),
            id=self.id,
            class_=self.class_,
        ).render()


@dataclass
class StatusBadge(Component):
    """A status indicator badge."""

    status: str
    label: str | None = None

    def render(self) -> str:
        indicator = Element(
            tag="span",
            content="",
            class_=f"state-indicator {self.status}",
        ).render()

        if self.label:
            label_el = Element(
                tag="span",
                content=self.label,
                class_="status-label",
            ).render()
            return indicator + label_el

        return indicator


@dataclass
class ProgressBar(Component):
    """A progress bar with text."""

    total: int
    completed: int
    failed: int = 0

    def render(self) -> str:
        if self.total <= 0:
            percent = 0
        else:
            percent = min(100, int((self.completed / self.total) * 100))

        fill = Element(
            tag="div",
            content="",
            id="progress-fill",
            class_="progress-fill",
            attrs={"style": f"width: {percent}%"},
        ).render()

        bar = Element(
            tag="div",
            content=RawHTML(fill),
            class_="progress-bar",
        ).render()

        suffix = f" ({self.failed} failed)" if self.failed else ""
        text = Element(
            tag="div",
            content=f"{self.completed}/{self.total} agents completed{suffix}",
            class_="progress-text",
        ).render()

        return Element(
            tag="div",
            content=RawHTML(bar + text),
            class_="progress-container",
        ).render()


__all__ = ["List", "ListItem", "ProgressBar", "StatusBadge"]
