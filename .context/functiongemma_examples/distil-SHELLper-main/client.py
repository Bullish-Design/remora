import json
from typing import List, Dict
from openai import OpenAI


def load_tools(job_description_path: str = "data/job_description.json") -> tuple[str, List[Dict]]:
    """Load task description and tools from job_description.json"""
    with open(job_description_path, 'r') as f:
        data = json.load(f)
    return data["task_description"], data["tools"]


class GorillaLLM:
    def __init__(self, model_name: str, task_description: str, tools: List[Dict], api_key: str = "EMPTY", port: int = 11434):
        self.model_name = model_name
        self.task_description = task_description
        self.tools = tools
        self.client = OpenAI(base_url=f"http://127.0.0.1:{port}/v1", api_key=api_key)

    def get_system_prompt(self) -> str:
        """Generate system prompt with tools"""
        return f"""You are a tool-calling model working on:
<task_description>{self.task_description}</task_description>

Respond to the conversation history by generating an appropriate tool call that satisfies the user request. Generate only the tool call according to the provided tool schema, do not generate anything else. Always respond with a tool call.

"""

    def invoke(self, conversation_history: List[Dict[str, str]]) -> str:
        """
        Invoke the model with conversation history.

        Args:
            conversation_history: List of message dicts with 'role' and 'content'

        Returns:
            Model response as string
        """
        messages = [{"role": "system", "content": self.get_system_prompt()}]
        messages.extend(conversation_history)

        chat_response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0,
            tools=self.tools,
            reasoning_effort="none",
        )

        response = chat_response.choices[0].message
        return response.content if response.content and len(response.content.strip('\n')) else response.tool_calls[0]