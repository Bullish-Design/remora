import pytest
from pathlib import Path
from remora.hub.test_discovery import extract_test_targets, is_test_file


def test_is_test_file() -> None:
    assert is_test_file(Path("test_foo.py"))
    assert is_test_file(Path("foo_test.py"))
    assert is_test_file(Path("tests/test_bar.py"))
    assert not is_test_file(Path("foo.py"))
    assert not is_test_file(Path("testing.py"))


def test_extract_test_targets(tmp_path: Path) -> None:
    source = '''
from mymodule import calculate, validate

def test_calculate():
    result = calculate(1, 2)
    assert result == 3

def test_validate_success():
    assert validate("good") is True

def test_complex():
    x = calculate(1, 2)
    y = validate(str(x))
    assert y
'''
    test_file = tmp_path / "test_mymodule.py"
    test_file.write_text(source, encoding="utf-8")

    targets = extract_test_targets(test_file)

    # test_calculate should target "calculate"
    test_calc_id = f"node:{test_file}:test_calculate"
    assert "calculate" in targets[test_calc_id]

    # test_validate_success should target "validate"
    test_val_id = f"node:{test_file}:test_validate_success"
    assert "validate" in targets[test_val_id]

    # test_complex should target both
    test_complex_id = f"node:{test_file}:test_complex"
    assert "calculate" in targets[test_complex_id]
    assert "validate" in targets[test_complex_id]
