import json
import os
import shlex
from typing import Dict, Any


def translate_tool_call_to_bash(tool_name: str, arguments: Dict[str, Any], allow_recursive: bool = False) -> str:
    """
    Translate Gorilla file system tool calls to bash commands.
    Uses shlex.quote() to safely escape all arguments and prevent command injection.

    Args:
        tool_name: Name of the tool/function
        arguments: Dictionary of arguments
        allow_recursive: Whether to allow recursive directory removal

    Returns:
        Bash command string with properly escaped arguments
    """
    if tool_name == "cat":
        return f"cat {shlex.quote(arguments['file_name'])}"

    elif tool_name == "cd":
        return f"cd {shlex.quote(arguments['folder'])}"

    elif tool_name == "cp":
        return f"cp -r {shlex.quote(arguments['source'])} {shlex.quote(arguments['destination'])}"

    elif tool_name == "diff":
        return f"diff {shlex.quote(arguments['file_name1'])} {shlex.quote(arguments['file_name2'])}"

    elif tool_name == "du":
        if arguments.get('human_readable', False):
            return "du -h"
        return "du"

    elif tool_name == "echo":
        content = arguments['content']
        file_name = arguments.get('file_name', 'None')
        if file_name and file_name != 'None':
            # Use >> for appending to file
            return f"echo {shlex.quote(content)} >> {shlex.quote(file_name)}"
        else:
            return f"echo {shlex.quote(content)}"

    elif tool_name == "find":
        path = arguments.get('path', '.')
        name = arguments.get('name', 'None')
        if name and name != 'None':
            return f"find {shlex.quote(path)} -name {shlex.quote('*' + name + '*')}"
        else:
            return f"find {shlex.quote(path)}"

    elif tool_name == "grep":
        return f"grep {shlex.quote(arguments['pattern'])} {shlex.quote(arguments['file_name'])}"

    elif tool_name == "ls":
        if arguments.get('a', False):
            return "ls -a"
        return "ls"

    elif tool_name == "mkdir":
        return f"mkdir {shlex.quote(arguments['dir_name'])}"

    elif tool_name == "mv":
        return f"mv {shlex.quote(arguments['source'])} {shlex.quote(arguments['destination'])}"

    elif tool_name == "pwd":
        return "pwd"

    elif tool_name == "rm":
        file_name = arguments['file_name']
        if allow_recursive:
            # With --allow_recursive, add -r flag (regular rm behavior)
            return f"rm -r {shlex.quote(file_name)}"
        else:
            # Without --allow_recursive, use regular rm (will fail for non-empty dirs)
            return f"rm {shlex.quote(file_name)}"

    elif tool_name == "rmdir":
        return f"rmdir {shlex.quote(arguments['dir_name'])}"

    elif tool_name == "sort":
        return f"sort {shlex.quote(arguments['file_name'])}"

    elif tool_name == "tail":
        lines = arguments.get('lines', 10)
        return f"tail -n {lines} {shlex.quote(arguments['file_name'])}"

    elif tool_name == "touch":
        return f"touch {shlex.quote(arguments['file_name'])}"

    elif tool_name == "wc":
        mode = arguments.get('mode', 'l')
        return f"wc -{mode} {shlex.quote(arguments['file_name'])}"

    else:
        return f"# Unknown command: {tool_name}"


def is_dangerous_rm_command(tool_name: str, arguments: Dict[str, Any]) -> bool:
    """
    Check if rm command is dangerous (rm / or rm *) based on tool call structure.
    Ban removal of / or a * in the current directory.

    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments dictionary

    Returns:
        True if dangerous, False otherwise
    """
    if tool_name != "rm":
        return False

    file_name = arguments.get("file_name", "").strip()

    # Check for root directory deletion
    if file_name in ("/", "/*", "/.", "/.."):
        return True

    # Check for wildcard deletion at current directory level
    if file_name in ("*", ".*", "./*", "./.*"):
        return True

    chars = set(file_name)
    if chars in ["*", "/"]:
        return True

    file_name = os.path.realpath(file_name)
    if file_name == '/':
        return True

    return False


def parse_llm_response(llm_response: str | Any) -> tuple[str, Dict[str, Any]]:
    """
    Parse LLM response and extract tool call.

    Args:
        llm_response: Response from LLM (string or tool_call object)

    Returns:
        Tuple of (function_name, arguments)
    """
    try:
        # Handle OpenAI tool_call object format
        if not isinstance(llm_response, str):
            function_name = llm_response.function.name
            arguments = json.loads(llm_response.function.arguments)
            return function_name, arguments

        # Handle JSON string format
        response_data = json.loads(llm_response)

        # Handle direct format: {"name": "...", "parameters": {...}}
        if "name" in response_data and "parameters" in response_data:
            return response_data["name"], response_data["parameters"]

        # Handle OpenAI format with tool_calls
        if "tool_calls" in response_data and len(response_data["tool_calls"]) > 0:
            tool_call = response_data["tool_calls"][0]
            function_name = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"])
            return function_name, arguments

        raise ValueError("Could not parse LLM response")

    except (json.JSONDecodeError, KeyError, AttributeError) as e:
        raise ValueError(f"Failed to parse LLM response: {e}")
