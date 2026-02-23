"""
src/remora/hub/test_discovery.py

Discover which tests exercise which code nodes.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.hub.store import NodeStateStore


def is_test_file(path: Path) -> bool:
    """Check if a file is a test file."""
    name = path.name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "/tests/" in str(path)
        or "/test/" in str(path)
    )


def extract_test_targets(file_path: Path) -> dict[str, list[str]]:
    """
    Extract which functions/classes each test function targets.

    Returns:
        Dict mapping test_node_id -> list of target names
    """
    if not is_test_file(file_path):
        return {}

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return {}

    results: dict[str, list[str]] = {}

    # Find all test functions
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                test_node_id = f"node:{file_path}:{node.name}"
                targets = _extract_targets_from_test(node, source)
                results[test_node_id] = targets

    return results


def _extract_targets_from_test(test_func: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> list[str]:
    """Extract target function/class names from a test function."""
    targets: set[str] = set()

    # Strategy 1: Parse function name (test_foo tests foo)
    if test_func.name.startswith("test_"):
        potential_target = test_func.name[5:]  # Remove "test_" prefix
        if potential_target:
            targets.add(potential_target)

    # Strategy 2: Look for function calls in the test body
    for node in ast.walk(test_func):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                # Direct call: foo()
                targets.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                # Method call: obj.method()
                targets.add(node.func.attr)

    # Strategy 3: Look for imports used in the test
    # (Already covered by call extraction)

    # Filter out common test utilities
    test_utilities = {
        "assert", "assertEqual", "assertTrue", "assertFalse",
        "assertRaises", "assertIsNone", "assertIsNotNone",
        "patch", "Mock", "MagicMock", "fixture",
        "pytest", "mark", "parametrize",
    }
    targets -= test_utilities

    return sorted(targets)


async def update_test_relationships(
    store: "NodeStateStore",
    project_root: Path,
) -> int:
    """
    Scan test files and update related_tests for all nodes.

    Returns:
        Number of nodes updated.
    """
    # Step 1: Build name -> node_id index
    name_to_ids: dict[str, list[str]] = {}
    all_nodes = await store.list_all_nodes()

    for node_id in all_nodes:
        node = await store.get(node_id)
        if node:
            name = node.node_name
            if name not in name_to_ids:
                name_to_ids[name] = []
            name_to_ids[name].append(node_id)

    # Step 2: Scan all test files
    test_files = list(project_root.rglob("test_*.py"))
    test_files.extend(project_root.rglob("*_test.py"))

    # node_id -> list of test node IDs
    node_to_tests: dict[str, list[str]] = {nid: [] for nid in all_nodes}

    for test_file in test_files:
        test_targets = extract_test_targets(test_file)

        for test_node_id, targets in test_targets.items():
            for target_name in targets:
                target_ids = name_to_ids.get(target_name, [])
                for target_id in target_ids:
                    if test_node_id not in node_to_tests[target_id]:
                        node_to_tests[target_id].append(test_node_id)

    # Step 3: Update nodes
    updated = 0
    for node_id, test_ids in node_to_tests.items():
        node = await store.get(node_id)
        if node is None:
            continue

        new_related_tests = test_ids if test_ids else None
        if node.related_tests != new_related_tests:
            node.related_tests = new_related_tests
            await store.set(node)
            updated += 1

    return updated
