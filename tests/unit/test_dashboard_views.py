from remora.ui.projector import UiStateProjector
from remora.ui.view import render_dashboard, render_tag


def test_dashboard_view_renders_body_content() -> None:
    html = render_dashboard(UiStateProjector().snapshot())
    assert '<main id="remora-root"' in html
    assert "Remora Dashboard" in html


def test_render_tag_normalizes_reserved_attrs() -> None:
    html = render_tag(
        "label",
        content="Name",
        class_="card",
        for_="name-input",
        **{"data-on": "click"},
    )
    assert 'class="card"' in html
    assert 'for="name-input"' in html
    assert 'data-on="click"' in html
    assert "class_=" not in html
