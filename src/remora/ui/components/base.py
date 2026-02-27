"""Base component classes."""

from __future__ import annotations

import html
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class Component(ABC):
    """Abstract base class for UI components."""

    @abstractmethod
    def render(self) -> str:
        """Render the component to an HTML string."""
        ...

    def __str__(self) -> str:
        return self.render()

    def __add__(self, other: "Component | str") -> "ComponentGroup":
        return ComponentGroup([self, other])


@dataclass
class ComponentGroup(Component):
    """A group of components rendered sequentially."""

    children: list[Component | str] = field(default_factory=list)

    def render(self) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, Component):
                parts.append(child.render())
            else:
                parts.append(str(child))
        return "".join(parts)

    def __add__(self, other: "Component | str") -> "ComponentGroup":
        return ComponentGroup([*self.children, other])


@dataclass
class RawHTML(Component):
    """Render raw HTML without escaping."""

    content: str

    def render(self) -> str:
        return self.content


@dataclass
class Element(Component):
    """A generic HTML element."""

    tag: str
    content: Component | str = ""
    id: str | None = None
    class_: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    data_attrs: dict[str, str] = field(default_factory=dict)
    self_closing: bool = False

    def render(self) -> str:
        attr_parts: list[str] = []

        if self.id:
            attr_parts.append(f'id="{html.escape(self.id)}"')

        if self.class_:
            attr_parts.append(f'class="{html.escape(self.class_)}"')

        for key, value in self.attrs.items():
            if value is not None:
                safe_key = _normalize_attr_key(key)
                attr_parts.append(f'{safe_key}="{html.escape(str(value))}"')

        for key, value in self.data_attrs.items():
            safe_key = _normalize_attr_key(key)
            attr_parts.append(f'data-{safe_key}="{html.escape(str(value))}"')

        attr_str = " ".join(attr_parts)

        if self.self_closing:
            return f"<{self.tag} {attr_str}/>" if attr_str else f"<{self.tag}/>"

        content = self.content.render() if isinstance(self.content, Component) else html.escape(str(self.content))

        if attr_str:
            return f"<{self.tag} {attr_str}>{content}</{self.tag}>"
        return f"<{self.tag}>{content}</{self.tag}>"


def escape(text: str) -> str:
    """Escape HTML special characters."""
    return html.escape(text)


def _normalize_attr_key(key: str) -> str:
    placeholder = "\0"
    key = key.replace("__", placeholder)
    key = key.replace("_", "-")
    return key.replace(placeholder, "__")


__all__ = ["Component", "ComponentGroup", "Element", "RawHTML", "escape"]
