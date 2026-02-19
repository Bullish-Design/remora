"""Error codes for Remora."""

"""Standard error codes used across Remora."""

CONFIG_001 = "CONFIG_001"
CONFIG_002 = "CONFIG_002"
CONFIG_003 = "CONFIG_003"
CONFIG_004 = "CONFIG_004"
DISC_001 = "DISC_001"
DISC_002 = "DISC_002"
DISC_003 = "DISC_003"
DISC_004 = "DISC_004"
AGENT_001 = "AGENT_001"
AGENT_002 = "AGENT_002"
AGENT_003 = "AGENT_003"
AGENT_004 = "AGENT_004"
SERVER_001 = "SERVER_001"
SERVER_002 = "SERVER_002"

ERROR_DOCS = {
    CONFIG_001: "Missing or unreadable configuration source.",
    CONFIG_002: "Configuration value failed validation.",
    CONFIG_003: "Configuration file could not be loaded.",
    CONFIG_004: "Agents directory could not be found.",
    DISC_001: "Discovery query pack not found.",
    DISC_002: "Unexpected tree-sitter output during discovery.",
    DISC_003: "Invalid tree-sitter query syntax.",
    DISC_004: "Source file failed to parse during discovery.",
    AGENT_001: "Subagent definition or tool registry error.",
    AGENT_002: "Model server connection error.",
    AGENT_003: "Runner turn or validation failure.",
    AGENT_004: "Runner exceeded configured turn limit.",
    SERVER_001: "Server configuration is invalid.",
    SERVER_002: "Server returned an unexpected response.",
}
