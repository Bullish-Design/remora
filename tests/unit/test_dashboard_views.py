from remora.dashboard.state import DashboardState
from remora.dashboard.views import dashboard_view, render_tag


def test_dashboard_view_renders_body_content() -> None:
    html = dashboard_view(DashboardState().get_view_data())
    body_index = html.find("<body")
    assert body_index != -1
    body_start = html.find(">", body_index)
    assert body_start != -1
    assert "Remora Dashboard" in html[body_start:]


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
