import os
import re
from pathlib import Path

def process():
    for root, _, files in os.walk("tests/unit"):
        for file in files:
            if not file.endswith(".py"):
                continue
            path = Path(root) / file
            content = path.read_text()
            
            # If the file has `.nodes.get_node = AsyncMock`, the object (`<var>.nodes`) 
            # will be evaluated as a MagicMock unless we explicitly do `<var>.nodes = MagicMock()` first.
            # But tests might do `<var>.nodes = ...` multiple times if there are multiple methods.
            # A cleaner way is to find all such assignments and just prepend `<var>.nodes = MagicMock()` 
            # right before the FIRST one in a function/block.
            
            # Actually, the simplest fix is just replace `.nodes.` with `.` and then in the EventStore setup, do `mock.nodes = mock`. Wait, no.
            
            # Let's just manually replace:
            # `mock_store.nodes.list_nodes = AsyncMock(...)`
            # `mock_store.nodes = MagicMock(); mock_store.nodes.list_nodes = AsyncMock(...)`
            # This is exactly what the sed command was supposed to do, but sed syntax was wrong.
            
            new_content = re.sub(r'([a-zA-Z0-9_]+)\.nodes\.(list_nodes|get_node|get_node_at_position|set_node_status|remove_nodes_for_file) = AsyncMock', 
                                 r'\1.nodes = __import__("unittest.mock").MagicMock() if not hasattr(\1, "nodes") or isinstance(\1.nodes, __import__("unittest.mock").AsyncMock) else \1.nodes; \1.nodes.\2 = __import__("unittest.mock").AsyncMock', 
                                 content)
                                 
            if new_content != content:
                print(f"Modifying {path}")
                path.write_text(new_content)

if __name__ == "__main__":
    process()
