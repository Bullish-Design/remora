"""Tool registry for dynamic tool selection."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolDefinition:
    """Definition of an available tool."""
    name: str
    description: str
    category: str
    factory: Callable[..., Any]  # Creates tool instance given workspace


class ToolRegistry:
    """
    Registry for managing available tools and presets.

    Provides a way to select tools by name or preset, and creates
    tool instances bound to a specific workspace.
    """

    # Tool definitions
    _TOOLS: dict[str, ToolDefinition] = {}

    # Preset groupings
    PRESETS: dict[str, list[str]] = {
        "file_ops": [
            "read_file",
            "write_file",
            "list_dir",
            "file_exists",
            "search_files",
        ],
        "code_analysis": [
            "discover_symbols",
        ],
        "all": [],  # Populated dynamically
    }

    @classmethod
    def register(
        cls,
        name: str,
        description: str,
        category: str,
        factory: Callable[..., Any],
    ) -> None:
        """Register a tool definition."""
        cls._TOOLS[name] = ToolDefinition(
            name=name,
            description=description,
            category=category,
            factory=factory,
        )
        # Update "all" preset
        if name not in cls.PRESETS["all"]:
            cls.PRESETS["all"].append(name)

    @classmethod
    def get_tools(
        cls,
        workspace: Any,
        presets: list[str] | None = None,
        tool_names: list[str] | None = None,
    ) -> list[Any]:
        """
        Get tool instances for the given workspace.

        Args:
            workspace: The workspace to bind tools to
            presets: List of preset names to include
            tool_names: List of individual tool names to include

        Returns:
            List of tool instances
        """
        # Collect tool names from presets and explicit names
        names: set[str] = set()

        if presets:
            for preset in presets:
                if preset in cls.PRESETS:
                    names.update(cls.PRESETS[preset])

        if tool_names:
            names.update(tool_names)

        # Create tool instances
        tools = []
        for name in names:
            if name in cls._TOOLS:
                tool_def = cls._TOOLS[name]
                tool = tool_def.factory(workspace)
                tools.append(tool)

        return tools

    @classmethod
    def list_tools(cls) -> list[dict]:
        """List all available tools with metadata."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
            }
            for t in cls._TOOLS.values()
        ]

    @classmethod
    def list_presets(cls) -> dict[str, list[str]]:
        """List all available presets."""
        return cls.PRESETS.copy()


# Register built-in tools
def _register_cairn_tools():
    """Register Cairn file operation tools."""

    def make_read_file(workspace):
        from structured_agents import Tool

        async def read_file(path: str) -> str:
            """Read the contents of a file."""
            return await workspace.read_file(path)

        return Tool.from_function(read_file)

    def make_write_file(workspace):
        from structured_agents import Tool

        async def write_file(path: str, content: str) -> bool:
            """Write content to a file."""
            await workspace.write_file(path, content)
            return True

        return Tool.from_function(write_file)

    def make_list_dir(workspace):
        from structured_agents import Tool

        async def list_dir(path: str = ".") -> list[str]:
            """List files and directories at the given path."""
            return await workspace.list_dir(path)

        return Tool.from_function(list_dir)

    def make_file_exists(workspace):
        from structured_agents import Tool

        async def file_exists(path: str) -> bool:
            """Check if a file exists."""
            return await workspace.file_exists(path)

        return Tool.from_function(file_exists)

    def make_search_files(workspace):
        from structured_agents import Tool

        async def search_files(pattern: str) -> list[str]:
            """Search for files matching a glob pattern."""
            return await workspace.search_files(pattern)

        return Tool.from_function(search_files)

    ToolRegistry.register("read_file", "Read file contents", "file_ops", make_read_file)
    ToolRegistry.register("write_file", "Write content to file", "file_ops", make_write_file)
    ToolRegistry.register("list_dir", "List directory contents", "file_ops", make_list_dir)
    ToolRegistry.register("file_exists", "Check if file exists", "file_ops", make_file_exists)
    ToolRegistry.register("search_files", "Search files by pattern", "file_ops", make_search_files)


def _register_discovery_tools():
    """Register code analysis tools."""

    def make_discover_symbols(workspace):
        from structured_agents import Tool
        from remora.core.discovery import discover

        async def discover_symbols(path: str = ".") -> list[dict]:
            """
            Discover code symbols (functions, classes) in the given path.

            Returns a list of symbols with their names, types, and locations.
            """
            from pathlib import Path

            full_path = workspace.resolve_path(path)
            symbols = []

            for node in discover([full_path]):
                symbols.append({
                    "name": node.name,
                    "type": node.node_type,
                    "file": str(node.file_path),
                    "line": node.start_line,
                })

            return symbols

        return Tool.from_function(discover_symbols)

    ToolRegistry.register(
        "discover_symbols",
        "Discover code symbols (functions, classes)",
        "code_analysis",
        make_discover_symbols,
    )


# Initialize tools on module load
_register_cairn_tools()
_register_discovery_tools()