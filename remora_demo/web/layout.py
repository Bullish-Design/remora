"""Hierarchical tree layout with cursor-reactive expand/collapse.

Computes deterministic (x, y) positions using a "hybrid ripple" model:
- **Full detail**: the file the cursor is in (classes, methods, all internals)
- **File-only**: other files in the same directory (just the file node)
- **Collapsed**: all other directories (single summary node per directory)

When no cursor focus exists, falls back to showing everything expanded.

No external graph library required.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Layout constants (pixels)
NODE_W = 160
NODE_H = 36
COLLAPSED_W = 180  # wider for summary nodes
COLLAPSED_H = 48  # taller for summary nodes
H_GAP = 40  # horizontal gap between file columns
V_GAP = 8  # vertical gap between nodes within a column
GROUP_PAD = 8  # extra padding around class groups
GROUP_HEADER_H = 24  # height of a group header label
DIR_PAD = 12  # padding inside directory group boxes
DIR_HEADER_H = 28  # height of directory group header


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
class DirGroupBox:
    """Bounding box for a directory group."""

    label: str  # directory name to display
    path: str  # full directory path
    x: float
    y: float
    w: float
    h: float
    depth: int  # nesting depth (0 = root)


@dataclass
class CollapsedDir:
    """A collapsed directory summary node."""

    label: str  # display name (collapsed path)
    path: str  # full directory path for identification
    file_count: int  # how many files inside
    node_count: int  # total nodes (files + classes + functions)
    x: float = 0.0
    y: float = 0.0
    w: float = COLLAPSED_W
    h: float = COLLAPSED_H


@dataclass
class LayoutResult:
    """Complete layout computation result."""

    positions: dict[str, NodePosition] = field(default_factory=dict)
    groups: list[GroupBox] = field(default_factory=list)
    dir_groups: list[DirGroupBox] = field(default_factory=list)
    collapsed_dirs: list[CollapsedDir] = field(default_factory=list)
    total_width: float = 0.0
    total_height: float = 0.0


# ---------------------------------------------------------------------------
# Directory trie
# ---------------------------------------------------------------------------


class _DirNode:
    """Node in the directory trie."""

    __slots__ = ("name", "children", "files")

    def __init__(self, name: str) -> None:
        self.name = name
        self.children: dict[str, _DirNode] = {}  # subdir name -> node
        self.files: list[str] = []  # file paths rooted at this dir


def _build_dir_trie(file_paths: list[str]) -> _DirNode:
    """Build a trie of directories from file paths."""
    root = _DirNode("")
    for fp in sorted(file_paths):
        parts = fp.replace("\\", "/").split("/")
        node = root
        for part in parts[:-1]:
            if part not in node.children:
                node.children[part] = _DirNode(part)
            node = node.children[part]
        node.files.append(fp)
    return root


def _collapse_single_child_dirs(node: _DirNode) -> _DirNode:
    """Collapse single-child directory chains into combined labels."""
    while len(node.children) == 1 and not node.files:
        only_child_name = next(iter(node.children))
        only_child = node.children[only_child_name]
        new_name = f"{node.name}/{only_child_name}" if node.name else only_child_name
        node.name = new_name
        node.children = only_child.children
        node.files = only_child.files

    for child_name in list(node.children):
        node.children[child_name] = _collapse_single_child_dirs(node.children[child_name])

    return node


def _count_dir_contents(
    dir_node: _DirNode,
    file_members: dict[str, list[dict]],
) -> tuple[int, int]:
    """Count files and total nodes recursively under a dir node.

    Returns (file_count, node_count).
    """
    file_count = len(dir_node.files)
    # Each file is a node, plus all its members
    node_count = file_count + sum(len(file_members.get(fp, [])) for fp in dir_node.files)
    for child in dir_node.children.values():
        cf, cn = _count_dir_contents(child, file_members)
        file_count += cf
        node_count += cn
    return file_count, node_count


# ---------------------------------------------------------------------------
# Path normalisation
# ---------------------------------------------------------------------------


def _normalize_path(p: str) -> str:
    """Strip ``file://`` URI scheme to a plain filesystem path.

    Handles both ``file:///absolute/path`` and plain ``/absolute/path``.
    """
    if p.startswith("file:///"):
        return p[len("file://") :]  # keep the leading /
    if p.startswith("file://"):
        return p[len("file://") :]
    return p


# ---------------------------------------------------------------------------
# Visibility classification
# ---------------------------------------------------------------------------


def _get_dir_of_file(file_path: str) -> str:
    """Extract directory portion of a file path."""
    parts = file_path.replace("\\", "/").rsplit("/", 1)
    return parts[0] if len(parts) > 1 else ""


def _dir_contains_path(dir_node: _DirNode, dir_path: str, target_dir: str) -> bool:
    """Check if a dir_node (at dir_path) contains the target directory.

    The target_dir is considered contained if dir_path is a prefix of target_dir,
    OR if the collapsed dir_node name spans multiple segments that cover it.
    """
    # Normalize: the effective full path of files in this node uses dir_path
    # Check if any file in this node or its children is in target_dir
    for fp in dir_node.files:
        fp_dir = _get_dir_of_file(fp)
        if fp_dir == target_dir:
            return True
    for child_name in dir_node.children:
        child_path = f"{dir_path}/{child_name}" if dir_path else child_name
        if _dir_contains_path(dir_node.children[child_name], child_path, target_dir):
            return True
    return False


# ---------------------------------------------------------------------------
# File column layout helpers
# ---------------------------------------------------------------------------


def _layout_file_column_full(
    fp: str,
    file_node: dict | None,
    file_members: list[dict],
    by_id: dict[str, dict],
    children: dict[str, list[dict]],
    col_x: float,
    col_y: float,
    result: LayoutResult,
) -> tuple[float, float]:
    """Lay out a file with full detail (classes, methods, everything).

    Returns (column_width, column_bottom_y).
    """
    # Place file node at top of column
    if file_node:
        fid = file_node.get("remora_id") or file_node.get("id", "")
        result.positions[fid] = NodePosition(node_id=fid, x=col_x, y=col_y)
        col_y += NODE_H + V_GAP

    # Separate classes and standalone functions
    classes = [n for n in file_members if n.get("node_type") == "class"]
    standalone = [
        n
        for n in file_members
        if n.get("node_type") in ("function", "method")
        and (not n.get("parent_id") or by_id.get(n["parent_id"], {}).get("node_type") == "file")
    ]

    classes.sort(key=lambda n: n.get("start_line", 0))
    standalone.sort(key=lambda n: n.get("start_line", 0))

    for cls_node in classes:
        cls_id = cls_node.get("remora_id") or cls_node.get("id", "")
        group_start_y = col_y

        result.positions[cls_id] = NodePosition(
            node_id=cls_id,
            x=col_x + GROUP_PAD,
            y=col_y + GROUP_PAD,
        )
        col_y += GROUP_PAD + NODE_H + V_GAP

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

    for func_node in standalone:
        fid = func_node.get("remora_id") or func_node.get("id", "")
        result.positions[fid] = NodePosition(node_id=fid, x=col_x, y=col_y)
        col_y += NODE_H + V_GAP

    col_w = NODE_W + GROUP_PAD * 3
    return col_w, col_y


def _layout_file_column_fileonly(
    fp: str,
    file_node: dict | None,
    col_x: float,
    col_y: float,
    result: LayoutResult,
) -> tuple[float, float]:
    """Lay out a file as just its file node (no internals).

    Returns (column_width, column_bottom_y).
    """
    if file_node:
        fid = file_node.get("remora_id") or file_node.get("id", "")
        result.positions[fid] = NodePosition(node_id=fid, x=col_x, y=col_y)
        col_y += NODE_H + V_GAP

    return NODE_W, col_y


# ---------------------------------------------------------------------------
# Recursive directory group layout with visibility awareness
# ---------------------------------------------------------------------------


def _layout_dir_node(
    dir_node: _DirNode,
    dir_path: str,
    depth: int,
    x: float,
    y: float,
    file_nodes: dict[str, dict],
    file_members: dict[str, list[dict]],
    by_id: dict[str, dict],
    children_map: dict[str, list[dict]],
    result: LayoutResult,
    focused_file: str | None,
    focused_dir: str | None,
) -> tuple[float, float]:
    """Recursively lay out a directory node with visibility-aware expand/collapse.

    Visibility rules (when focused_file is set):
    - If this dir node contains the focused_dir: expand recursively
    - If this dir node IS the focused_dir: show files with appropriate detail
    - Otherwise: collapse to a single summary node

    Returns (total_width, total_height) of this directory group.
    """
    is_root = depth == 0 and not dir_node.name

    # Determine if this directory subtree contains the focused file
    contains_focus = focused_file is None or _dir_contains_path(dir_node, dir_path, focused_dir or "")

    # If no focus or this subtree doesn't contain the focus, and it's not root,
    # collapse to a summary node
    if not is_root and focused_file is not None and not contains_focus:
        file_count, node_count = _count_dir_contents(dir_node, file_members)
        collapsed = CollapsedDir(
            label=dir_node.name,
            path=dir_path,
            file_count=file_count,
            node_count=node_count,
            x=x,
            y=y,
        )
        result.collapsed_dirs.append(collapsed)
        return collapsed.w, collapsed.h

    # This directory is expanded -- lay out its contents
    pad = 0 if is_root else DIR_PAD
    header_h = 0 if is_root else DIR_HEADER_H

    inner_x = x + pad
    inner_y = y + pad + header_h

    cursor_x = inner_x
    max_bottom = inner_y

    # Lay out files in this directory
    sorted_files = sorted(dir_node.files)
    for fp in sorted_files:
        fn = file_nodes.get(fp)
        members = file_members.get(fp, [])

        if focused_file is None:
            # No cursor: show everything fully expanded
            col_w, col_bottom = _layout_file_column_full(
                fp, fn, members, by_id, children_map, cursor_x, inner_y, result
            )
        elif fp == focused_file:
            # This is THE focused file: full detail
            col_w, col_bottom = _layout_file_column_full(
                fp, fn, members, by_id, children_map, cursor_x, inner_y, result
            )
        else:
            # Same directory but not the focused file: file node only
            col_w, col_bottom = _layout_file_column_fileonly(fp, fn, cursor_x, inner_y, result)

        max_bottom = max(max_bottom, col_bottom)
        cursor_x += col_w + H_GAP

    # Lay out child directories
    for child_name in sorted(dir_node.children):
        child_node = dir_node.children[child_name]
        child_path = f"{dir_path}/{child_name}" if dir_path else child_name
        child_w, child_h = _layout_dir_node(
            child_node,
            child_path,
            depth + 1,
            cursor_x,
            inner_y,
            file_nodes,
            file_members,
            by_id,
            children_map,
            result,
            focused_file,
            focused_dir,
        )
        max_bottom = max(max_bottom, inner_y + child_h)
        cursor_x += child_w + H_GAP

    # Remove trailing H_GAP
    if cursor_x > inner_x:
        cursor_x -= H_GAP

    total_inner_w = max(cursor_x - inner_x, NODE_W)
    total_w = total_inner_w + pad * 2
    total_h = max(max_bottom - y, header_h + pad) + pad

    # Register the directory group box (skip invisible root)
    if not is_root:
        result.dir_groups.append(
            DirGroupBox(
                label=dir_node.name,
                path=dir_path,
                x=x,
                y=y,
                w=total_w,
                h=total_h,
                depth=depth,
            )
        )

    return total_w, total_h


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_layout(
    nodes: list[dict],
    edges: list[dict],
    cursor_focus: dict | None = None,
) -> LayoutResult:
    """Compute hierarchical positions with cursor-reactive expand/collapse.

    Args:
        nodes: All graph nodes.
        edges: All graph edges.
        cursor_focus: Optional dict with 'file_path' and/or 'agent_id'.
            When provided, drives the hybrid ripple visibility:
            - Focused file: full detail
            - Same directory: file-only
            - Other directories: collapsed summaries

    Algorithm:
    1. Build a directory trie from file paths
    2. Collapse single-child chains
    3. Determine focused file/directory from cursor_focus
    4. Recursively lay out with visibility-aware expansion:
       - Dirs containing the focus: expanded
       - Focused file: full detail
       - Sibling files: file-only
       - Other dirs: collapsed summary nodes
    """
    result = LayoutResult()

    if not nodes:
        return result

    # Index nodes by id and build parent -> children mapping
    by_id: dict[str, dict] = {}
    children_map: dict[str, list[dict]] = {}
    for n in nodes:
        nid = n.get("remora_id") or n.get("id", "")
        by_id[nid] = n
        children_map.setdefault(nid, [])

    for n in nodes:
        nid = n.get("remora_id") or n.get("id", "")
        pid = n.get("parent_id")
        if pid and pid in by_id:
            children_map[pid].append(n)

    # Group nodes by file path (normalised to plain paths)
    file_nodes: dict[str, dict] = {}
    file_members: dict[str, list[dict]] = {}
    all_file_paths: set[str] = set()
    for n in nodes:
        fp = _normalize_path(n.get("file_path", ""))
        nt = n.get("node_type", "")
        all_file_paths.add(fp)
        if nt == "file":
            file_nodes[fp] = n
        else:
            file_members.setdefault(fp, []).append(n)

    # Determine focused file and directory from cursor_focus
    focused_file: str | None = None
    focused_dir: str | None = None
    if cursor_focus:
        # Try to resolve focus via agent_id -> file_path, or direct file_path
        agent_id = cursor_focus.get("agent_id")
        if agent_id and agent_id in by_id:
            focused_file = _normalize_path(by_id[agent_id].get("file_path", ""))
        if not focused_file:
            raw = cursor_focus.get("file_path", "")
            focused_file = _normalize_path(raw) if raw else None
        if focused_file:
            focused_dir = _get_dir_of_file(focused_file)

    # Build and simplify directory trie
    trie_root = _build_dir_trie(sorted(all_file_paths))
    trie_root = _collapse_single_child_dirs(trie_root)

    # Layout starting from top-left margin
    start_x = 40.0
    start_y = 40.0
    total_w, total_h = _layout_dir_node(
        trie_root,
        "",
        0,
        start_x,
        start_y,
        file_nodes,
        file_members,
        by_id,
        children_map,
        result,
        focused_file,
        focused_dir,
    )

    result.total_width = start_x + total_w + 40
    result.total_height = start_y + total_h + 40

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

        x1 = from_pos.x + from_pos.w / 2
        y1 = from_pos.y + from_pos.h
        x2 = to_pos.x + to_pos.w / 2
        y2 = to_pos.y

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
