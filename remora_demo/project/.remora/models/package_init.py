"""Extension config for __init__.py package files."""

from remora.extensions import AgentExtension


class PackageInitExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "file" and name == "__init__.py"

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "PackageInit",
            "custom_system_prompt": (
                "You represent a Python package. You are aware of all modules in your "
                "package. When modules are added, removed, or have their public API "
                "changed, update your __all__ list and re-export statements to keep "
                "the package interface consistent."
            ),
        }
