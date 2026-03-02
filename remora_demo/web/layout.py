"""Hierarchical tree layout for the graph view.

Computes deterministic (x, y) positions for each node:
- Files are columns (horizontal spacing)
- Classes are groups within columns
- Functions/methods are leaf rows within groups

No external graph library required.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Layout constants (pixels)
NODE_W = 160
NODE_H = 36
H_GAP = 40  # horizontal gap between file columns
V_GAP = 8  # vertical gap between nodes within a column
GROUP_PAD = 8  # extra padding around class groups
GROUP_HEADER_H = 28  # height of the class group header


@dataclass
class NodePosition:
    """Computed position for a single node."""

    node_id: str
    x: float
    y: float
    w: float = NODE_W
    h: float = NODE_H


@dataclass
class GroupBox:
    """Bounding box for a class group."""

    node_id: str  # class node id
    x: float
    y: float
    w: float
    h: float


@dataclass
class LayoutResult:
    """Complete layout computation result."""

    positions: dict[str, NodePosition] = field(default_factory=dict)
    groups: list[GroupBox] = field(default_factory=list)
    total_width: float = 0.0
    total_height: float = 0.0


def compute_layout(nodes: list[dict], edges: list[dict]) -> LayoutResult:
    """Compute hierarchical positions for all nodes.

    Algorithm:
    1. Group nodes by file_path
    2. Within each file, separate into: file node, class groups, standalone functions
    3. Lay out each file as a column
    4. Classes become sub-groups with their methods stacked vertically inside
    """
    result = LayoutResult()

    if not nodes:
        return result

    # Index nodes by id and build parent -> children mapping
    by_id: dict[str, dict] = {}
    children: dict[str, list[dict]] = {}
    for n in nodes:
        nid = n.get("remora_id") or n.get("id", "")
        by_id[nid] = n
        children.setdefault(nid, [])

    for n in nodes:
        nid = n.get("remora_id") or n.get("id", "")
        pid = n.get("parent_id")
        if pid and pid in by_id:
            children[pid].append(n)

    # Group nodes by file
    files: dict[str, list[dict]] = {}
    file_nodes: dict[str, dict] = {}
    for n in nodes:
        fp = n.get("file_path", "")
        nid = n.get("remora_id") or n.get("id", "")
        nt = n.get("node_type", "")
        if nt == "file":
            file_nodes[fp] = n
        else:
            files.setdefault(fp, []).append(n)

    # Sort files deterministically
    sorted_files = sorted(set(list(files.keys()) + list(file_nodes.keys())))

    col_x = 40.0  # left margin

    for fp in sorted_files:
        col_y = 40.0  # top margin

        # Place file node at top of column
        fn = file_nodes.get(fp)
        if fn:
            fid = fn.get("remora_id") or fn.get("id", "")
            result.positions[fid] = NodePosition(node_id=fid, x=col_x, y=col_y)
            col_y += NODE_H + V_GAP

        # Separate classes and standalone functions
        file_members = files.get(fp, [])
        classes = [n for n in file_members if n.get("node_type") == "class"]
        standalone = [
            n
            for n in file_members
            if n.get("node_type") in ("function", "method")
            and (not n.get("parent_id") or by_id.get(n["parent_id"], {}).get("node_type") == "file")
        ]

        # Sort classes by start_line for determinism
        classes.sort(key=lambda n: n.get("start_line", 0))
        standalone.sort(key=lambda n: n.get("start_line", 0))

        # Layout classes with their methods
        for cls_node in classes:
            cls_id = cls_node.get("remora_id") or cls_node.get("id", "")
            group_start_y = col_y

            # Class header
            result.positions[cls_id] = NodePosition(
                node_id=cls_id,
                x=col_x + GROUP_PAD,
                y=col_y + GROUP_PAD,
            )
            col_y += GROUP_PAD + NODE_H + V_GAP

            # Methods within this class
            methods = [c for c in children.get(cls_id, []) if c.get("node_type") in ("method", "function")]
            methods.sort(key=lambda n: n.get("start_line", 0))

            for method in methods:
                mid = method.get("remora_id") or method.get("id", "")
                result.positions[mid] = NodePosition(
                    node_id=mid,
                    x=col_x + GROUP_PAD * 2,
                    y=col_y,
                )
                col_y += NODE_H + V_GAP

            group_h = col_y - group_start_y + GROUP_PAD
            result.groups.append(
                GroupBox(
                    node_id=cls_id,
                    x=col_x,
                    y=group_start_y,
                    w=NODE_W + GROUP_PAD * 3,
                    h=group_h,
                )
            )
            col_y += GROUP_PAD

        # Layout standalone functions
        for func_node in standalone:
            fid = func_node.get("remora_id") or func_node.get("id", "")
            result.positions[fid] = NodePosition(
                node_id=fid,
                x=col_x,
                y=col_y,
            )
            col_y += NODE_H + V_GAP

        # Track column width and move to next column
        col_w = NODE_W + GROUP_PAD * 3
        result.total_height = max(result.total_height, col_y)
        col_x += col_w + H_GAP

    result.total_width = col_x

    return result


def compute_edge_paths(
    positions: dict[str, NodePosition],
    edges: list[dict],
) -> list[dict]:
    """Compute SVG path data for edges between positioned nodes.

    Returns list of dicts: {from_id, to_id, edge_type, path_d}
    where path_d is an SVG path string.
    """
    paths = []
    for edge in edges:
        from_id = edge.get("from_id", "")
        to_id = edge.get("to_id", "")
        edge_type = edge.get("edge_type", "parent_of")

        from_pos = positions.get(from_id)
        to_pos = positions.get(to_id)
        if not from_pos or not to_pos:
            continue

        # Compute center points
        x1 = from_pos.x + from_pos.w / 2
        y1 = from_pos.y + from_pos.h
        x2 = to_pos.x + to_pos.w / 2
        y2 = to_pos.y

        # Simple bezier curve
        mid_y = (y1 + y2) / 2
        path_d = f"M {x1} {y1} C {x1} {mid_y}, {x2} {mid_y}, {x2} {y2}"

        paths.append(
            {
                "from_id": from_id,
                "to_id": to_id,
                "edge_type": edge_type,
                "path_d": path_d,
            }
        )

    return paths
