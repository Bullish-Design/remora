#!/usr/bin/env python
"""End-to-end test for Companion demo.

Tests the full pipeline:
1. Index a codebase
2. Simulate cursor movement
3. Verify agent cascade
4. Check sidebar output

Usage:
    python -m remora_demo.companion.test_e2e

    # Or with a specific directory:
    python -m remora_demo.companion.test_e2e /path/to/codebase
"""

import asyncio
import sys
import tempfile
from pathlib import Path


async def test_full_pipeline(workspace_path: Path | None = None) -> bool:
    """Test the full Companion pipeline."""
    from remora_demo.companion.runtime import CompanionConfig, CompanionRuntime

    print("\n" + "=" * 60)
    print("🧠 Companion E2E Test")
    print("=" * 60 + "\n")

    # Use temp directory if no path provided
    if workspace_path is None:
        # Use the remora source as test data
        workspace_path = Path(__file__).parent.parent.parent.parent / "src" / "remora"
        if not workspace_path.exists():
            workspace_path = Path.cwd()

    print(f"📂 Workspace: {workspace_path}")

    # Create a temp directory for the index
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        config = CompanionConfig(
            workspace_path=workspace_path,
            db_path=db_path,
            auto_index=True,
        )

        runtime = CompanionRuntime(config)

        try:
            # ----------------------------------------
            # Step 1: Start runtime (triggers indexing)
            # ----------------------------------------
            print("\n1️⃣  Starting runtime and indexing...")
            await runtime.start()
            print("   ✅ Runtime started")

            # Check index stats
            stats = runtime.indexer.store.stats()
            print(f"   📊 Indexed {stats.get('total_chunks', 0)} chunks")

            if stats.get("total_chunks", 0) == 0:
                print("   ⚠️  Warning: No chunks indexed")

            # ----------------------------------------
            # Step 2: Simulate cursor movement
            # ----------------------------------------
            print("\n2️⃣  Simulating cursor movement...")

            # Find a Python file to test with
            test_file = None
            for f in workspace_path.rglob("*.py"):
                if f.stat().st_size > 100:  # Non-trivial file
                    test_file = f
                    break

            if test_file is None:
                print("   ❌ No Python files found to test with")
                return False

            print(f"   📄 Testing with: {test_file.name}")

            # Trigger cursor movement
            await runtime.on_cursor_moved(str(test_file), 10, 0)

            # Wait for agents to process
            print("   ⏳ Waiting for agent cascade...")
            await asyncio.sleep(0.5)

            # ----------------------------------------
            # Step 3: Check workspace state
            # ----------------------------------------
            print("\n3️⃣  Checking workspace state...")

            context = await runtime.get_context()

            if context.get("file_path"):
                print(f"   ✅ file_path: {context['file_path']}")
            else:
                print("   ❌ file_path not set")

            if context.get("cursor_position"):
                print(f"   ✅ cursor_position: {context['cursor_position']}")
            else:
                print("   ❌ cursor_position not set")

            if context.get("content_type"):
                print(f"   ✅ content_type: {context['content_type']}")
            else:
                print("   ⚠️  content_type not set (may be normal)")

            # ----------------------------------------
            # Step 4: Check agent activations
            # ----------------------------------------
            print("\n4️⃣  Checking agent activations...")

            activations = runtime.get_activations()
            print(f"   📊 Total activations: {len(activations)}")

            agents_activated = set()
            for act in activations:
                agents_activated.add(act["agent"])
                status_icon = "✅" if act["status"] == "success" else "⚠️"
                print(f"   {status_icon} {act['agent']}: {act['status']}")

            expected_agents = {"context_extractor", "embedding_searcher", "sidebar_composer"}
            missing = expected_agents - agents_activated
            if missing:
                print(f"   ⚠️  Missing agents: {missing}")

            # ----------------------------------------
            # Step 5: Check sidebar output
            # ----------------------------------------
            print("\n5️⃣  Checking sidebar output...")

            sidebar = await runtime.get_sidebar()

            if sidebar:
                print(f"   ✅ Sidebar generated ({len(sidebar)} chars)")
                # Show preview
                preview_lines = sidebar.split("\n")[:10]
                for line in preview_lines:
                    print(f"      {line[:60]}")
                if len(sidebar.split("\n")) > 10:
                    print("      ...")
            else:
                print("   ❌ No sidebar generated")

            # ----------------------------------------
            # Step 6: Test search functionality
            # ----------------------------------------
            print("\n6️⃣  Testing search functionality...")

            search_results = runtime.indexer.search("function", limit=3)
            if search_results:
                print(f"   ✅ Search returned {len(search_results)} results")
                for r in search_results[:3]:
                    print(f"      - {r.chunk.file_path}: {r.score:.2f}")
            else:
                print("   ⚠️  Search returned no results")

            # ----------------------------------------
            # Summary
            # ----------------------------------------
            print("\n" + "=" * 60)
            print("📋 Test Summary")
            print("=" * 60)

            success = (
                stats.get("total_chunks", 0) > 0
                and context.get("file_path") is not None
                and len(activations) > 0
                and sidebar is not None
            )

            if success:
                print("✅ All tests passed!")
            else:
                print("❌ Some tests failed")

            return success

        finally:
            # Cleanup
            print("\n🧹 Cleaning up...")
            await runtime.stop()
            print("   ✅ Runtime stopped")


async def test_connection_finder() -> bool:
    """Test the connection finder agent specifically."""
    from remora_demo.companion.agents.analyzers import ConnectionFinder
    from remora_demo.companion.agents.base import InMemoryWorkspace
    from remora_demo.companion.models.workspace import SimilarResult, Structure

    print("\n" + "=" * 60)
    print("🔗 Connection Finder Test")
    print("=" * 60 + "\n")

    workspace = InMemoryWorkspace()
    finder = ConnectionFinder(workspace)

    # Set up context
    await workspace.write("/companion/context/file_path", "src/foo.py")
    await workspace.write(
        "/companion/context/structure",
        Structure(
            structure_type="function",
            name="process_data",
            parent="DataProcessor",
        ),
    )
    await workspace.write("/companion/context/content_type", "code")

    # Add some search results
    await workspace.write(
        "/companion/search/similar/0",
        SimilarResult(
            file="tests/test_foo.py",
            snippet="def test_process_data():",
            score=0.85,
            content_type="code",
        ),
    )
    await workspace.write(
        "/companion/search/similar/1",
        SimilarResult(
            file="docs/processing.md",
            snippet="# Data Processing\n\nThe process_data function...",
            score=0.72,
            content_type="markdown",
        ),
    )

    # Trigger analysis
    from remora_demo.companion.models.events import PathChanged

    await finder.on_search_results(
        PathChanged(
            path="/companion/search/similar/0",
            value=None,
            previous=None,
        )
    )

    # Check connections
    connection_paths = await workspace.list("/companion/analysis/connections/*")
    print(f"   Found {len(connection_paths)} connections:")

    for path in connection_paths:
        conn = await workspace.read(path)
        if conn:
            print(f"   - {conn.connection_type}: {conn.insight}")

    success = len(connection_paths) > 0
    print(f"\n{'✅' if success else '❌'} Connection finder test {'passed' if success else 'failed'}")

    return success


async def main():
    """Run all tests."""
    workspace_path = None
    if len(sys.argv) > 1:
        workspace_path = Path(sys.argv[1])

    results = []

    # Test 1: Full pipeline
    results.append(await test_full_pipeline(workspace_path))

    # Test 2: Connection finder
    results.append(await test_connection_finder())

    # Final summary
    print("\n" + "=" * 60)
    print("🏁 Final Results")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"✅ All {total} tests passed!")
        return 0
    else:
        print(f"❌ {passed}/{total} tests passed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
