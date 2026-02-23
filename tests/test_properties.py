"""Property-based tests using Hypothesis."""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import assume, given, settings, strategies as st

from remora.config import _deep_update
from remora.discovery import compute_node_id


safe_path_chars = st.characters(whitelist_categories=("L", "N"), whitelist_characters="/._-")

NODE_TYPES = ["file", "class", "function", "method"]


@given(
    name=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"), min_size=1, max_size=50
    ),
    file_path=st.text(alphabet=safe_path_chars, min_size=1, max_size=60),
    node_type=st.sampled_from(NODE_TYPES),
)
def test_node_id_deterministic(name: str, file_path: str, node_type: str) -> None:
    """Node ID generation is deterministic for same inputs."""
    assume("\x00" not in file_path)
    path = Path(file_path)

    first = compute_node_id(path, node_type, name)
    second = compute_node_id(path, node_type, name)

    assert first == second


@given(
    data=st.dictionaries(
        st.text(min_size=1, max_size=20),
        st.one_of(
            st.text(max_size=50),
            st.integers(),
            st.booleans(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.none(),
        ),
        max_size=20,
    )
)
def test_json_roundtrip(data: dict) -> None:
    """Any JSON-serializable dict should survive encode/decode."""
    encoded = json.dumps(data)
    decoded = json.loads(encoded)
    assert decoded == data


@given(
    base=st.dictionaries(
        st.text(min_size=1, max_size=20),
        st.one_of(
            st.text(max_size=50),
            st.integers(),
            st.booleans(),
            st.none(),
        ),
        max_size=20,
    )
)
def test_config_merge_empty_identity(base: dict) -> None:
    """Merging with empty dict returns equivalent config."""
    result = _deep_update(base, {})
    assert result == base


@given(path=st.text(alphabet=safe_path_chars, min_size=1, max_size=80))
@settings(max_examples=200)
def test_path_normalization_idempotent(path: str) -> None:
    """Normalizing a path twice should give the same result."""
    assume("\x00" not in path)

    try:
        normalized_once = Path(path).resolve()
        normalized_twice = normalized_once.resolve()
    except (OSError, ValueError):
        assume(False)
    else:
        assert normalized_once == normalized_twice
