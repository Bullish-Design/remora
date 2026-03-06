from pathlib import Path


def test_query_files_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "queries" / "python" / "tags.scm").exists()
    assert (root / "queries" / "markdown" / "sections.scm").exists()
