"""Form control components."""

from __future__ import annotations

from dataclasses import dataclass, field

from remora.ui.components.base import Component, Element, RawHTML


@dataclass
class Button(Component):
    """A button element."""

    label: str
    id: str | None = None
    class_: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    data_attrs: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        return Element(
            tag="button",
            content=self.label,
            id=self.id,
            class_=self.class_,
            attrs=self.attrs,
            data_attrs=self.data_attrs,
        ).render()


@dataclass
class Input(Component):
    """An input element."""

    id: str | None = None
    class_: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    data_attrs: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        return Element(
            tag="input",
            content="",
            id=self.id,
            class_=self.class_,
            attrs=self.attrs,
            data_attrs=self.data_attrs,
            self_closing=True,
        ).render()


@dataclass
class Select(Component):
    """A select element."""

    options: list[str] = field(default_factory=list)
    id: str | None = None
    class_: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    data_attrs: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        options_html = "".join(
            Element(tag="option", content=option, attrs={"value": option}).render()
            for option in self.options
        )
        return Element(
            tag="select",
            content=RawHTML(options_html),
            id=self.id,
            class_=self.class_,
            attrs=self.attrs,
            data_attrs=self.data_attrs,
        ).render()


__all__ = ["Button", "Input", "Select"]
