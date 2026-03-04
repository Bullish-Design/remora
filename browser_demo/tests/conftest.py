"""Shared test fixtures for browser_demo tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add src to path so browser_demo is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from browser_demo.models import ClipMetadata, ClipRecord, FetchResult
from browser_demo.store import ClipStore


@pytest.fixture
def tmp_clips_dir(tmp_path: Path) -> Path:
    """Temporary directory for clip storage."""
    clips = tmp_path / "clips"
    clips.mkdir()
    return clips


@pytest.fixture
def store(tmp_clips_dir: Path) -> ClipStore:
    """A ClipStore backed by a temporary directory."""
    s = ClipStore(tmp_clips_dir)
    yield s
    s.close()


@pytest.fixture
def sample_html() -> str:
    """A realistic HTML page for testing conversion."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>Test Page Title</title>
    <meta property="og:title" content="OG Title" />
    <style>body { color: red; }</style>
</head>
<body>
    <nav><a href="/">Home</a><a href="/about">About</a></nav>
    <article class="main-content">
        <h1>Welcome to the Test Page</h1>
        <p>This is the <strong>first paragraph</strong> with some <em>emphasis</em>.</p>
        <h2>Section Two</h2>
        <p>A list of items:</p>
        <ul>
            <li>Item one</li>
            <li>Item two</li>
            <li>Item three</li>
        </ul>
        <h2>Code Example</h2>
        <pre><code>def hello():
    print("world")</code></pre>
        <p>A link to <a href="https://example.com">Example</a>.</p>
        <img src="cat.jpg" alt="A cat" />
    </article>
    <footer>Copyright 2026</footer>
    <script>console.log("hello");</script>
</body>
</html>"""


@pytest.fixture
def sample_fetch_result(sample_html: str) -> FetchResult:
    """A FetchResult wrapping sample HTML."""
    return FetchResult(
        url="https://example.com/test",
        final_url="https://example.com/test",
        title="Test Page Title",
        html=sample_html,
        status_code=200,
    )


@pytest.fixture
def sample_record() -> ClipRecord:
    """A pre-built ClipRecord for testing."""
    meta = ClipMetadata(
        clip_id="abc123",
        url="https://example.com/test",
        title="Test Page",
        tags=["python", "testing"],
    )
    record = ClipRecord(metadata=meta, content="# Test Page\n\nSome content here.\n")
    record.metadata.compute_hash(record.content)
    return record
