"""Extension config for MONITOR.md: meta-observation of all agent activity.

The SwarmMonitor agent watches all other agents without them knowing.
It subscribes to agent lifecycle events and logs a summary of activity
to its own file, demonstrating meta-observation in the reactive swarm.
"""

from remora.extensions import AgentExtension


class SwarmMonitorExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
        return node_type == "file" and name == "MONITOR"

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "SwarmMonitor",
            "custom_system_prompt": (
                "You are a meta-observation agent. You silently observe all agent "
                "activity in the swarm without them knowing. When you receive an "
                "agent lifecycle event (completion, error, or tool call), log a "
                "concise summary to your own file using `rewrite_self`. Monitor "
                "patterns like frequent errors, long-running agents, or unusual "
                "tool usage. You never message other agents directly."
            ),
            "extra_subscriptions": [
                {
                    "event_types": ["AgentCompleteEvent", "AgentErrorEvent", "ToolCallEvent"],
                },
            ],
        }
