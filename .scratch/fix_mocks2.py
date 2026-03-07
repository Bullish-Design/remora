import os
from pathlib import Path

def fix_file(path):
    text = path.read_text()
    orig = text
    
    # Simple string replacements to inject .nodes = MagicMock()
    # We want to insert `obj.nodes = MagicMock()` right before `obj.nodes.method = AsyncMock(...)`
    # if it's not already there.
    
    lines = text.split('\n')
    new_lines = []
    
    for line in lines:
        if '.nodes.list_nodes = AsyncMock' in line or \
           '.nodes.get_node = AsyncMock' in line or \
           '.nodes.get_node_at_position = AsyncMock' in line:
            
            # extract the object part before .nodes
            parts = line.split('.nodes.')
            if len(parts) > 1:
                obj_part = parts[0].strip()
                # If obj_part starts with spaces, preserve indentation
                indent = ''
                for c in line:
                    if c == ' ':
                        indent += c
                    else:
                        break
                obj_clean = obj_part.strip()
                new_lines.append(f'{indent}{obj_clean}.nodes = __import__("unittest.mock").AsyncMock()')
        new_lines.append(line)
        
    text = '\n'.join(new_lines)

    # Let's also fix some assertion failures: `.get_node_at_position.assert_called` -> `.nodes.get_node_at_position.assert_called`
    text = text.replace('.get_node_at_position.assert_', '.nodes.get_node_at_position.assert_')
    text = text.replace('.get_node.assert_', '.nodes.get_node.assert_')
    text = text.replace('.list_nodes.assert_', '.nodes.list_nodes.assert_')
    
    # And there's also issues where `list_nodes` was replaced but maybe `set_node_status` shouldn't be
    # Actually `set_node_status` and `remove_nodes_for_file` are on EventStore now!
    text = text.replace('.nodes.set_node_status', '.set_node_status')
    text = text.replace('.nodes.remove_nodes_for_file', '.remove_nodes_for_file')
    
    # The `nodes` mock should also have `nodes.set_node_status` removed if it was mistakenly added?
    # No, test code calling them calls `.set_node_status`.

    if text != orig:
        print(f"Fixed {path}")
        path.write_text(text)

for root, _, files in os.walk("tests/unit"):
    for f in files:
        if f.endswith('.py'):
            fix_file(Path(root) / f)
