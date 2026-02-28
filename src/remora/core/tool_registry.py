"""Tool registry for dynamic tool selection."""

from dataclasses import dataclass
from typing import Any, Callable
from structured_agents import Tool


@dataclass
class ToolDefinition:
    """Definition of an available tool."""

    name: str
    description: str
    category: str
    factory: Callable[..., Any]


# Add lazy initialization:
_tools_registered = False


class ToolRegistry:
    """Registry for managing available tools and presets."""

    _TOOLS: dict[str, ToolDefinition] = {}

    PRESETS: dict[str, list[str]] = {
        "file_ops": ["read_file", "write_file", "list_dir", "file_exists", "search_files"],
        "code_analysis": ["discover_symbols"],
        "all": [],
    }

    @classmethod
    def _ensure_registered(cls):
        global _tools_registered
        if not _tools_registered:
            _register_tools()
            _tools_registered = True

    @classmethod
    def register(cls, name: str, description: str, category: str, factory: Callable) -> None:
        """Register a tool definition."""
        cls._TOOLS[name] = ToolDefinition(name, description, category, factory)
        if name not in cls.PRESETS["all"]:
            cls.PRESETS["all"].append(name)

    @classmethod
    def get_tools(cls, workspace: Any, presets: list[str]) -> list[Any]:
        """Get tool instances for the given workspace."""
        names: set[str] = set()
        for preset in presets:
            if preset in cls.PRESETS:
                names.update(cls.PRESETS[preset])

        return [cls._TOOLS[name].factory(workspace) for name in names if name in cls._TOOLS]

    @classmethod
    def list_presets(cls) -> dict[str, list[str]]:
        """List available presets and their tools."""
        return {k: v for k, v in cls.PRESETS.items() if v}  # Exclude empty


## Tool registration (abbreviated - see full version in previous doc)
def _register_tools():
    def make_read_file(workspace):
        async def read_file(path: str) -> str:
            """Read file contents."""
            return await workspace.read_file(path)

        return Tool.from_function(read_file)

    def make_write_file(workspace):
        async def write_file(path: str, content: str) -> bool:
            """Write content to file."""
            await workspace.write_file(path, content)
            return True

        return Tool.from_function(write_file)

    def make_list_dir(workspace):
        async def list_dir(path: str = ".") -> list[str]:
            """List directory contents."""
            return await workspace.list_dir(path)

        return Tool.from_function(list_dir)

    def make_file_exists(workspace):
        async def file_exists(path: str) -> bool:
            """Check if file exists."""
            return await workspace.file_exists(path)

        return Tool.from_function(file_exists)

    def make_search_files(workspace):
        async def search_files(pattern: str) -> list[str]:
            """Search files by glob pattern."""
            return await workspace.search_files(pattern)

        return Tool.from_function(search_files)

    def make_discover_symbols(workspace):
        from remora.core.discovery import discover

        async def discover_symbols(path: str = ".") -> list[dict]:
            """Discover code symbols (functions, classes)."""
            full_path = workspace.resolve_path(path)
            return [
                {"name": n.name, "type": n.node_type, "file": str(n.file_path), "line": n.start_line}
                for n in discover([full_path])
            ]

        return Tool.from_function(discover_symbols)

    ToolRegistry.register("read_file", "Read file contents", "file_ops", make_read_file)
    ToolRegistry.register("write_file", "Write to file", "file_ops", make_write_file)
    ToolRegistry.register("list_dir", "List directory", "file_ops", make_list_dir)
    ToolRegistry.register("file_exists", "Check file exists", "file_ops", make_file_exists)
    ToolRegistry.register("search_files", "Search by pattern", "file_ops", make_search_files)
    ToolRegistry.register("discover_symbols", "Find code symbols", "code_analysis", make_discover_symbols)


# _register_tools()
