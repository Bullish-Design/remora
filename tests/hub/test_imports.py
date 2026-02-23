import pytest
from pathlib import Path
from remora.hub.imports import extract_imports, extract_node_imports


def test_extract_imports(tmp_path: Path) -> None:
    source = '''
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

def foo():
    pass
'''
    file = tmp_path / "test.py"
    file.write_text(source, encoding="utf-8")

    imports = extract_imports(file)
    assert "os" in imports
    assert "sys" in imports
    assert "pathlib.Path" in imports
    assert "typing.TYPE_CHECKING" in imports
    assert "typing.Optional" in imports


def test_extract_node_imports(tmp_path: Path) -> None:
    source = '''
import os
from pathlib import Path
from typing import Optional

def uses_path():
    return Path.cwd()

def uses_os():
    return os.getcwd()

def uses_nothing():
    return 42
'''
    file = tmp_path / "test.py"
    file.write_text(source, encoding="utf-8")

    path_imports = extract_node_imports(file, "uses_path")
    assert "pathlib.Path" in path_imports
    assert "os" not in path_imports

    os_imports = extract_node_imports(file, "uses_os")
    assert "os" in os_imports
    assert "pathlib.Path" not in os_imports

    nothing_imports = extract_node_imports(file, "uses_nothing")
    assert len(nothing_imports) == 0
