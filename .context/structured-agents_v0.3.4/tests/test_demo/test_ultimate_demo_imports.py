from demo.ultimate_demo import coordinator, runner


def test_demo_imports() -> None:
    assert coordinator is not None
    assert runner is not None
