"""Extension config for non-test functions: scaffolds test files.

When a function (that isn't a test itself) is discovered, this extension
equips the agent with a tool to create test file stubs, demonstrating
cascading reactivity: function -> test file -> test agents.
"""

from remora.extensions import AgentExtension


class FunctionTestScaffoldExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
        return node_type == "function" and not name.startswith("test_")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "FunctionTestScaffold",
            "custom_system_prompt": (
                "You are a test scaffolding agent for a Python function. When triggered, "
                "generate test stubs that cover the function's behavior. Use the "
                "`create_test_file` tool to write a test file at "
                "`tests/test_<module>.py` with pytest-style test functions. Each test "
                "stub should have a descriptive name and a TODO comment explaining "
                "what to assert."
            ),
            "extra_tools": [
                {
                    "name": "create_test_file",
                    "description": "Create or update a test file with test stubs for this function",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path for the test file (e.g. tests/test_billing.py)",
                            },
                            "content": {
                                "type": "string",
                                "description": "Python source code for the test file",
                            },
                        },
                        "required": ["path", "content"],
                    },
                },
            ],
            "extra_subscriptions": [
                {
                    "event_types": ["NodeDiscoveredEvent", "ContentChangedEvent"],
                },
            ],
        }
