"""Layout components."""

from __future__ import annotations

from dataclasses import dataclass, field

from remora.ui.components.base import Component, Element, RawHTML


@dataclass
class Container(Component):
    """A generic container div."""

    children: list[Component | str] = field(default_factory=list)
    id: str | None = None
    class_: str | None = None

    def render(self) -> str:
        content = "".join(
            child.render() if isinstance(child, Component) else str(child)
            for child in self.children
        )
        return Element(
            tag="div",
            content=RawHTML(content),
            id=self.id,
            class_=self.class_,
        ).render()


@dataclass
class Card(Component):
    """A card with optional title and content."""

    title: str | None = None
    content: Component | str = ""
    class_: str = "card"

    def render(self) -> str:
        parts: list[str] = []

        if self.title:
            parts.append(
                Element(
                    tag="div",
                    content=self.title,
                    class_="card-title",
                ).render()
            )

        if isinstance(self.content, Component):
            parts.append(self.content.render())
        else:
            parts.append(str(self.content))

        return Element(
            tag="div",
            content=RawHTML("".join(parts)),
            class_=self.class_,
        ).render()


@dataclass
class Panel(Component):
    """A panel section with header."""

    header: str
    content: Component | str
    id: str | None = None

    def render(self) -> str:
        header_html = Element(
            tag="div",
            content=self.header,
            id=f"{self.id}-header" if self.id else None,
        ).render()

        content_html = self.content.render() if isinstance(self.content, Component) else str(self.content)

        return Element(
            tag="div",
            content=RawHTML(header_html + content_html),
            id=self.id,
        ).render()


@dataclass
class FlexRow(Component):
    """Horizontal flex container."""

    children: list[Component | str] = field(default_factory=list)
    gap: str = "1rem"
    justify: str = "flex-start"
    align: str = "center"

    def render(self) -> str:
        content = "".join(
            child.render() if isinstance(child, Component) else str(child)
            for child in self.children
        )
        return Element(
            tag="div",
            content=RawHTML(content),
            attrs={
                "style": f"display:flex;gap:{self.gap};justify-content:{self.justify};align-items:{self.align}",
            },
        ).render()


@dataclass
class Grid(Component):
    """CSS Grid container."""

    children: list[Component | str] = field(default_factory=list)
    columns: str = "repeat(auto-fit, minmax(300px, 1fr))"
    gap: str = "1rem"

    def render(self) -> str:
        content = "".join(
            child.render() if isinstance(child, Component) else str(child)
            for child in self.children
        )
        return Element(
            tag="div",
            content=RawHTML(content),
            attrs={
                "style": f"display:grid;grid-template-columns:{self.columns};gap:{self.gap}",
            },
        ).render()


__all__ = ["Card", "Container", "FlexRow", "Grid", "Panel"]
