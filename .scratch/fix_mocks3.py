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
            
            orig = content
            
            # We want to replace `<var>.get_node = AsyncMock` with `<var>.nodes.get_node = AsyncMock`
            # but ONLY if it's not already `.nodes.get_node`.
            
            # Using regex:
            content = re.sub(r'(?<!\.nodes)\.get_node\s*=\s*(AsyncMock\()', r'.nodes.get_node = \1', content)
            content = re.sub(r'(?<!\.nodes)\.list_nodes\s*=\s*(AsyncMock\()', r'.nodes.list_nodes = \1', content)
            content = re.sub(r'(?<!\.nodes)\.get_node_at_position\s*=\s*(AsyncMock\()', r'.nodes.get_node_at_position = \1', content)
                                 
            if content != orig:
                print(f"Modifying {path}")
                path.write_text(content)

if __name__ == "__main__":
    process()
