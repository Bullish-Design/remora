import json
import os
import argparse
from typing import Optional, Dict, Any, List

from client import GorillaLLM, load_tools
from parsing import parse_llm_response, translate_tool_call_to_bash, is_dangerous_rm_command


# ============================================================================
# INTERACTION HANDLERS
# ============================================================================

def handle_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    allow_recursive: bool,
    verbose: bool = False
) -> Optional[str]:
    """
    Handle a single tool call: validate and print command.

    Args:
        tool_name: Name of the tool/function
        arguments: Tool arguments dictionary
        allow_recursive: Whether recursive deletion is allowed
        verbose: Whether to print the tool call details

    Returns:
        The bash command string if successful, None if blocked
    """
    # Check for dangerous rm commands before translation
    if is_dangerous_rm_command(tool_name, arguments):
        print(f"\n🚫 BLOCKED: Dangerous command detected: rm {arguments.get('file_name', '')}")
        print("Commands like 'rm /' or 'rm *' are not allowed.\n")
        print('-------------------------------------------------------------')
        return None

    # Translate to bash command
    bash_command = translate_tool_call_to_bash(tool_name, arguments, allow_recursive)

    # Print the tool call (matching test.jsonl format) only in verbose mode
    if verbose:
        print(f"\nTool call: {json.dumps({'name': tool_name, 'parameters': arguments})}")

    # Print the bash command
    print(f"COMMAND: {bash_command}")

    return bash_command


def execute_cd(folder: str) -> None:
    """
    Execute a cd command using os.chdir - os.popen does not work
    because it is a subprocess.

    Args:
        folder: The directory to change to
    """
    try:
        os.chdir(folder)
        print(f"✓ Changed directory to: {os.getcwd()}\n")
    except Exception as e:
        print(f"\n❌ Error changing directory: {e}\n")


def execute_bash_command(bash_command: str) -> None:
    """
    Execute a bash command.

    Args:
        bash_command: The bash command to execute
    """
    try:
        result = os.popen(bash_command).read()
        if result:
            print(f"\nOUTPUT:\n{result}")
        else:
            print("✓ Command executed successfully.\n")

    except Exception as e:
        print(f"\n❌ Error executing command: {e}\n")


def exit_program() -> None:
    """Print goodbye message and exit."""
    print("\nGoodbye!")
    exit(0)


# ============================================================================
# MAIN DEMO
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Gorilla File System Assistant - Multi-turn Demo")
    parser.add_argument("--job-description", type=str, default="data/job_description.json",
                        help="Path to job_description.json")
    parser.add_argument("--api-key", type=str, default="EMPTY",
                        help="API key (default: EMPTY)")
    parser.add_argument("--model", type=str, default="distil_model",
                        help="Model name")
    parser.add_argument("--port", type=int, default=11434,
                        help="API port (default: 11434)")
    parser.add_argument("--allow_recursive", action="store_true",
                        help="Allow recursive directory removal with rm -r (default: False)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print the tool call returned from the model")

    args = parser.parse_args()

    # Load tools and task description
    task_description, tools = load_tools(args.job_description)

    # Initialize LLM client
    client = GorillaLLM(
        model_name=args.model,
        task_description=task_description,
        tools=tools,
        api_key=args.api_key,
        port=args.port
    )

    # Print welcome message
    print(f"""-------------------------------------------------------------
[ GORILLA FILE SYSTEM ASSISTANT - {args.model} ]
-------------------------------------------------------------
I can help you navigate and manage files in the file system.
Recursive removal: {'ALLOWED' if args.allow_recursive else 'NOT ALLOWED (use rmdir for directories)'}

Type "exit" to finish.

Ask me anything:
""")

    # Conversation history (for multi-turn support)
    conversation_history: List[Dict[str, str]] = []

    while True:
        # Get user input
        try:
            user_input = input("USER: ").strip()
        except EOFError:
            exit_program()

        if user_input.lower() == "exit":
            exit_program()

        if not user_input:
            continue

        # Add user message to history
        conversation_history.append({"role": "user", "content": user_input})

        try:
            # Get model response
            llm_response = client.invoke(conversation_history)

            # Parse the response
            tool_name, arguments = parse_llm_response(llm_response)

            # Handle the tool call (validate and print)
            bash_command = handle_tool_call(tool_name, arguments, args.allow_recursive, args.verbose)

            # If blocked, remove user message from history and continue
            if bash_command is None:
                conversation_history.pop()  # Remove user message
                continue

            # Ask for confirmation before executing
            try:
                confirmation = input("Execute? [y/N]: ").strip().lower()
            except EOFError:
                exit_program()
            if confirmation != 'y':
                print("⚠️  Command skipped.\n")
                conversation_history.pop()  # Remove user message
                print('-------------------------------------------------------------')
                continue

            # Add assistant response to history as tool call (matching test.jsonl format)
            conversation_history.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments)
                    }
                }]
            })

            # Execute the command
            if tool_name == "cd":
                execute_cd(arguments["folder"])
            else:
                execute_bash_command(bash_command)

            print('-------------------------------------------------------------')

        except ValueError as e:
            print(f"\n❌ Error: {e}\n")
            print('-------------------------------------------------------------')
            # Remove failed user message from history
            conversation_history.pop()
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}\n")
            print('-------------------------------------------------------------')
            # Remove failed user message from history
            conversation_history.pop()


if __name__ == "__main__":
    main()
