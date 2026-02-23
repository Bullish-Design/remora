import pytest
from typing import Any
from pathlib import Path

class MockNodeStateStore:
    def __init__(self) -> None:
        self.nodes = {}
        
    async def get(self, node_id: str) -> Any:
        return self.nodes.get(node_id)
        
    async def set(self, node: Any) -> None:
        self.nodes[node.key] = node

    async def list_all_nodes(self) -> list[str]:
        return list(self.nodes.keys())

    async def invalidate_file(self, file_path: str) -> None:
        pass

    async def set_file_index(self, index: Any) -> None:
        pass

    async def delete_file_index(self, file_path: str) -> None:
        pass

    async def get_status(self) -> Any:
        class DummyStatus:
            indexed_files = 100
            indexed_nodes = 500
            running = True
        return DummyStatus()

@pytest.fixture
def mock_store() -> Any:
    return MockNodeStateStore()

@pytest.fixture
def mock_grail_executor() -> Any:
    from tests.hub.test_integration import SimpleGrailExecutor
    return SimpleGrailExecutor()
