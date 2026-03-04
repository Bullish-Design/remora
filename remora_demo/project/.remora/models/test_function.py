"""Extension config for test functions."""

from remora.extensions import AgentExtension


class TestFunctionExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "function" and name.startswith("test_")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "TestFunction",
            "custom_system_prompt": (
                "You are a test function agent. Your job is to verify the correctness "
                "of the code under test. When the function you test changes, examine the "
                "diff and update your assertions to match the new behavior. Use "
                "`rewrite_self` to propose test updates. Use `read_node` to check "
                "the current source of the function you test."
            ),
        }
