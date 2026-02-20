"""Tests for Hub rules engine."""

from pathlib import Path

from remora.hub.rules import DeleteFileNodes, ExtractSignatures, RulesEngine


def test_get_actions_for_deleted_file() -> None:
    rules = RulesEngine()
    actions = rules.get_actions("deleted", Path("/project/foo.py"))

    assert len(actions) == 1
    assert isinstance(actions[0], DeleteFileNodes)


def test_get_actions_for_modified_file() -> None:
    rules = RulesEngine()
    actions = rules.get_actions("modified", Path("/project/foo.py"))

    assert len(actions) == 1
    assert isinstance(actions[0], ExtractSignatures)


def test_should_process_file_filters() -> None:
    rules = RulesEngine()
    ignore = ["node_modules", "build"]

    assert rules.should_process_file(Path("/project/src/app.py"), ignore) is True
    assert rules.should_process_file(Path("/project/src/app.txt"), ignore) is False
    assert rules.should_process_file(Path("/project/.hidden.py"), ignore) is False
    assert rules.should_process_file(Path("/project/node_modules/app.py"), ignore) is False
