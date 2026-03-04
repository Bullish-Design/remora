"""Extension config for class nodes: generates API documentation.

When a class is discovered or changed, this extension equips the agent with
a tool to create documentation files and subscribes it to content changes
so it can keep docs in sync.
"""

from remora.extensions import AgentExtension


class ClassDocGeneratorExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
        return node_type == "class"

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "ClassDocGenerator",
            "custom_system_prompt": (
                "You are a documentation agent for a Python class. When triggered by "
                "a content change or discovery event, generate comprehensive API "
                "documentation for your class. Use the `create_doc_file` tool to write "
                "a Markdown file at `docs/<classname>.md` documenting all public methods, "
                "their signatures, and docstrings. When your class changes, regenerate "
                "the documentation to keep it in sync."
            ),
            "extra_tools": [
                {
                    "name": "create_doc_file",
                    "description": "Create or update a documentation file for this class",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path for the doc file (e.g. docs/MyClass.md)",
                            },
                            "content": {
                                "type": "string",
                                "description": "Markdown content for the documentation",
                            },
                        },
                        "required": ["path", "content"],
                    },
                },
            ],
            "extra_subscriptions": [
                {
                    "event_types": ["ContentChangedEvent", "NodeDiscoveredEvent"],
                },
            ],
        }
