# vLLM FunctionGemma Related Docs:

## Tool Calling API Section:

Tool Calling

vLLM currently supports named function calling, as well as the auto, required (as of vllm>=0.8.3), and none options for the tool_choice field in the chat completion API.
Quickstart

Start the server with tool calling enabled. This example uses Meta's Llama 3.1 8B model, so we need to use the llama3_json tool calling chat template from the vLLM examples directory:

vllm serve meta-llama/Llama-3.1-8B-Instruct \
    --enable-auto-tool-choice \
    --tool-call-parser llama3_json \
    --chat-template examples/tool_chat_template_llama3.1_json.jinja

Next, make a request that triggers the model to use the available tools:

??? code

```python
from openai import OpenAI
import json

client = OpenAI(base_url="http://localhost:8000/v1", api_key="dummy")

def get_weather(location: str, unit: str):
    return f"Getting the weather for {location} in {unit}..."
tool_functions = {"get_weather": get_weather}

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather in a given location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City and state, e.g., 'San Francisco, CA'"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
                },
                "required": ["location", "unit"],
            },
        },
    },
]

response = client.chat.completions.create(
    model=client.models.list().data[0].id,
    messages=[{"role": "user", "content": "What's the weather like in San Francisco?"}],
    tools=tools,
    tool_choice="auto",
)

tool_call = response.choices[0].message.tool_calls[0].function
print(f"Function called: {tool_call.name}")
print(f"Arguments: {tool_call.arguments}")
print(f"Result: {tool_functions[tool_call.name](**json.loads(tool_call.arguments))}")
```

Example output:

Function called: get_weather
Arguments: {"location": "San Francisco, CA", "unit": "fahrenheit"}
Result: Getting the weather for San Francisco, CA in fahrenheit...

This example demonstrates:

    Setting up the server with tool calling enabled
    Defining an actual function to handle tool calls
    Making a request with tool_choice="auto"
    Handling the structured response and executing the corresponding function

You can also specify a particular function using named function calling by setting tool_choice={"type": "function", "function": {"name": "get_weather"}}. Note that this will use the structured outputs backend - so the first time this is used, there will be several seconds of latency (or more) as the FSM is compiled for the first time before it is cached for subsequent requests.

Remember that it's the caller's responsibility to:

    Define appropriate tools in the request
    Include relevant context in the chat messages
    Handle the tool calls in your application logic

For more advanced usage, including parallel tool calls and different model-specific parsers, see the sections below.
Named Function Calling

vLLM supports named function calling in the chat completion API by default. This should work with most structured outputs backends supported by vLLM. You are guaranteed a validly-parsable function call - not a high-quality one.

vLLM will use structured outputs to ensure the response matches the tool parameter object defined by the JSON schema in the tools parameter. For best results, we recommend ensuring that the expected output format / schema is specified in the prompt to ensure that the model's intended generation is aligned with the schema that it's being forced to generate by the structured outputs backend.

To use a named function, you need to define the functions in the tools parameter of the chat completion request, and specify the name of one of the tools in the tool_choice parameter of the chat completion request.
Required Function Calling

vLLM supports the tool_choice='required' option in the chat completion API. Similar to the named function calling, it also uses structured outputs, so this is enabled by default and will work with any supported model. However, support for alternative decoding backends are on the roadmap for the V1 engine.

When tool_choice='required' is set, the model is guaranteed to generate one or more tool calls based on the specified tool list in the tools parameter. The number of tool calls depends on the user's query. The output format strictly follows the schema defined in the tools parameter.
None Function Calling

vLLM supports the tool_choice='none' option in the chat completion API. When this option is set, the model will not generate any tool calls and will respond with regular text content only, even if tools are defined in the request.

!!! note When tools are specified in the request, vLLM includes tool definitions in the prompt by default, regardless of the tool_choice setting. To exclude tool definitions when tool_choice='none', use the --exclude-tools-when-tool-choice-none option.
Automatic Function Calling

To enable this feature, you should set the following flags:

    --enable-auto-tool-choice -- mandatory Auto tool choice. It tells vLLM that you want to enable the model to generate its own tool calls when it deems appropriate.
    --tool-call-parser -- select the tool parser to use (listed below). Additional tool parsers will continue to be added in the future. You can also register your own tool parsers in the --tool-parser-plugin.
    --tool-parser-plugin -- optional tool parser plugin used to register user defined tool parsers into vllm, the registered tool parser name can be specified in --tool-call-parser.
    --chat-template -- optional for auto tool choice. It's the path to the chat template which handles tool-role messages and assistant-role messages that contain previously generated tool calls. Hermes, Mistral and Llama models have tool-compatible chat templates in their tokenizer_config.json files, but you can specify a custom template. This argument can be set to tool_use if your model has a tool use-specific chat template configured in the tokenizer_config.json. In this case, it will be used per the transformers specification. More on this here from HuggingFace; and you can find an example of this in a tokenizer_config.json here.

If your favorite tool-calling model is not supported, please feel free to contribute a parser & tool use chat template!


### Functiongemma Specific Section:

FunctionGemma Models (functiongemma)

Google's FunctionGemma is a lightweight (270M parameter) model specifically designed for function calling. It's built on Gemma 3 and optimized for edge deployment on devices like laptops and phones.

Supported models:

    google/functiongemma-270m-it

FunctionGemma uses a unique output format with <start_function_call> and <end_function_call> tags:

<start_function_call>call:get_weather{location:<escape>London<escape>}<end_function_call>

The model is designed to be fine-tuned for specific function-calling tasks for best results.

Flags: --tool-call-parser functiongemma --chat-template examples/tool_chat_template_functiongemma.jinja

!!! note FunctionGemma is intended to be fine-tuned for your specific function-calling task. The base model provides general function calling capabilities, but best results are achieved with task-specific fine-tuning. See Google's FunctionGemma documentation for fine-tuning guides.



## Tool Parsers API Section:
vllm.tool_parsers.functiongemma_tool_parser ¶
FunctionGemmaToolParser ¶

Bases: ToolParser

Tool parser for Google's FunctionGemma model (google/functiongemma-270m-it).

Handles the FunctionGemma function call format: call:func_name{param:value}
Source code in vllm/tool_parsers/functiongemma_tool_parser.py

class FunctionGemmaToolParser(ToolParser):
    """
    Tool parser for Google's FunctionGemma model (google/functiongemma-270m-it).

    Handles the FunctionGemma function call format:
    <start_function_call>call:func_name{param:<escape>value<escape>}<end_function_call>
    """

    def __init__(self, tokenizer: TokenizerLike):
        super().__init__(tokenizer)

        # Streaming state
        self.current_tool_name_sent: bool = False
        self.prev_tool_call_arr: list[dict] = []
        self.current_tool_id: int = -1
        self.streamed_args_for_tool: list[str] = []

        # FunctionGemma tokens
        self.tool_call_start_token: str = "<start_function_call>"
        self.tool_call_end_token: str = "<end_function_call>"

        # Regex patterns
        self.tool_call_regex = re.compile(
            r"<start_function_call>call:(\w+)\{(.*?)\}<end_function_call>"
            r"|<start_function_call>call:(\w+)\{(.*)",
            re.DOTALL,
        )
        self.arg_regex = re.compile(
            r"(\w+):<escape>(.*?)<escape>",
            re.DOTALL,
        )

        if self.model_tokenizer:
            self.tool_call_start_token_ids = self.model_tokenizer.encode(
                self.tool_call_start_token, add_special_tokens=False
            )
            self.tool_call_end_token_ids = self.model_tokenizer.encode(
                self.tool_call_end_token, add_special_tokens=False
            )
        else:
            self.tool_call_start_token_ids = []
            self.tool_call_end_token_ids = []

        self.buffered_delta_text = ""

    def _parse_arguments(self, args_str: str) -> dict:
        """Parse FunctionGemma argument string into a dictionary."""
        arguments = {}
        if not args_str:
            return arguments

        matches = self.arg_regex.findall(args_str)
        for key, value in matches:
            try:
                parsed_value = json.loads(value)
                arguments[key] = parsed_value
            except json.JSONDecodeError:
                arguments[key] = value

        return arguments

    def adjust_request(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        request = super().adjust_request(request)
        if request.tools and request.tool_choice != "none":
            request.skip_special_tokens = False
        return request

    def extract_tool_calls(
        self,
        model_output: str,
        request: ChatCompletionRequest,
    ) -> ExtractedToolCallInformation:
        if self.tool_call_start_token not in model_output:
            return ExtractedToolCallInformation(
                tools_called=False, tool_calls=[], content=model_output
            )

        try:
            matches = self.tool_call_regex.findall(model_output)

            if not matches:
                return ExtractedToolCallInformation(
                    tools_called=False, tool_calls=[], content=model_output
                )

            tool_calls: list[ToolCall] = []

            for match in matches:
                func_name = match[0] if match[0] else match[2]
                args_str = match[1] if match[1] else match[3]

                if not func_name:
                    continue

                arguments = self._parse_arguments(args_str)

                tool_calls.append(
                    ToolCall(
                        type="function",
                        function=FunctionCall(
                            name=func_name,
                            arguments=json.dumps(arguments, ensure_ascii=False),
                        ),
                    )
                )

            if tool_calls:
                content_end = model_output.find(self.tool_call_start_token)
                content = (
                    model_output[:content_end].strip() if content_end > 0 else None
                )

                return ExtractedToolCallInformation(
                    tools_called=True,
                    tool_calls=tool_calls,
                    content=content if content else None,
                )

            return ExtractedToolCallInformation(
                tools_called=False, tool_calls=[], content=model_output
            )

        except Exception:
            logger.exception("Error extracting tool calls from FunctionGemma response")
            return ExtractedToolCallInformation(
                tools_called=False, tool_calls=[], content=model_output
            )

    def _buffer_delta_text(self, delta_text: str) -> str:
        """Buffer incoming delta text to handle multi-token special sequences."""
        potential_start = "<start_function_call>"
        potential_end = "<end_function_call>"

        combined = self.buffered_delta_text + delta_text

        if combined.endswith(potential_start) or combined.endswith(potential_end):
            self.buffered_delta_text = ""
            return combined

        for tag in [potential_start, potential_end]:
            for i in range(1, len(tag)):
                if combined.endswith(tag[:i]):
                    self.buffered_delta_text = combined[-(i):]
                    return combined[:-i]

        self.buffered_delta_text = ""
        return combined

    def extract_tool_calls_streaming(
        self,
        previous_text: str,
        current_text: str,
        delta_text: str,
        previous_token_ids: Sequence[int],
        current_token_ids: Sequence[int],
        delta_token_ids: Sequence[int],
        request: ChatCompletionRequest,
    ) -> DeltaMessage | None:
        delta_text = self._buffer_delta_text(delta_text)
        current_text = previous_text + delta_text

        if self.tool_call_start_token not in current_text:
            if delta_text:
                return DeltaMessage(content=delta_text)
            return None

        try:
            start_count = current_text.count(self.tool_call_start_token)
            end_count = current_text.count(self.tool_call_end_token)
            prev_start_count = previous_text.count(self.tool_call_start_token)
            prev_end_count = previous_text.count(self.tool_call_end_token)

            if self.tool_call_start_token not in current_text:
                return DeltaMessage(content=delta_text)

            # Starting a new function call
            if start_count > prev_start_count and start_count > end_count:
                self.current_tool_id += 1
                self.current_tool_name_sent = False
                self.streamed_args_for_tool.append("")
                self.prev_tool_call_arr.append({})
                logger.debug("Starting new tool call %d", self.current_tool_id)
                return None

            # In the middle of a function call
            if start_count > end_count:
                last_start = current_text.rfind(self.tool_call_start_token)
                partial_call = current_text[
                    last_start + len(self.tool_call_start_token) :
                ]

                if partial_call.startswith("call:"):
                    func_part = partial_call[5:]

                    if "{" in func_part:
                        func_name = func_part.split("{")[0]
                        args_part = (
                            func_part.split("{", 1)[1] if "{" in func_part else ""
                        )

                        if not self.current_tool_name_sent and func_name:
                            self.current_tool_name_sent = True
                            self.prev_tool_call_arr[self.current_tool_id] = {
                                "name": func_name,
                                "arguments": {},
                            }
                            return DeltaMessage(
                                tool_calls=[
                                    DeltaToolCall(
                                        index=self.current_tool_id,
                                        type="function",
                                        id=make_tool_call_id(),
                                        function=DeltaFunctionCall(
                                            name=func_name
                                        ).model_dump(exclude_none=True),
                                    )
                                ]
                            )

                        if self.current_tool_name_sent and args_part:
                            current_args = self._parse_arguments(args_part)
                            if current_args:
                                current_args_json = json.dumps(
                                    current_args, ensure_ascii=False
                                )
                                prev_streamed = self.streamed_args_for_tool[
                                    self.current_tool_id
                                ]

                                if len(current_args_json) > len(prev_streamed):
                                    diff = current_args_json[len(prev_streamed) :]
                                    self.streamed_args_for_tool[
                                        self.current_tool_id
                                    ] = current_args_json
                                    self.prev_tool_call_arr[self.current_tool_id][
                                        "arguments"
                                    ] = current_args

                                    return DeltaMessage(
                                        tool_calls=[
                                            DeltaToolCall(
                                                index=self.current_tool_id,
                                                function=DeltaFunctionCall(
                                                    arguments=diff
                                                ).model_dump(exclude_none=True),
                                            )
                                        ]
                                    )

                return None

            # Function call just ended
            if end_count > prev_end_count:
                if self.current_tool_id >= 0 and self.current_tool_id < len(
                    self.prev_tool_call_arr
                ):
                    all_calls = self.tool_call_regex.findall(current_text)
                    args = {}
                    if self.current_tool_id < len(all_calls):
                        match = all_calls[self.current_tool_id]
                        if match[0]:
                            args_str = match[1]
                            args = self._parse_arguments(args_str)
                            self.prev_tool_call_arr[self.current_tool_id][
                                "arguments"
                            ] = args

                    if args:
                        args_json = json.dumps(args, ensure_ascii=False)
                        prev_streamed = self.streamed_args_for_tool[
                            self.current_tool_id
                        ]
                        if len(args_json) > len(prev_streamed):
                            diff = args_json[len(prev_streamed) :]
                            self.streamed_args_for_tool[self.current_tool_id] = (
                                args_json
                            )
                            return DeltaMessage(
                                tool_calls=[
                                    DeltaToolCall(
                                        index=self.current_tool_id,
                                        function=DeltaFunctionCall(
                                            arguments=diff
                                        ).model_dump(exclude_none=True),
                                    )
                                ]
                            )
                return None

            if delta_text:
                return DeltaMessage(content=delta_text)
            return None

        except Exception:
            logger.exception("Error in streaming tool call extraction")
            return None

Source code in vllm/tool_parsers/functiongemma_tool_parser.py:

class FunctionGemmaToolParser(ToolParser):
    """
    Tool parser for Google's FunctionGemma model (google/functiongemma-270m-it).

    Handles the FunctionGemma function call format:
    <start_function_call>call:func_name{param:<escape>value<escape>}<end_function_call>
    """

    def __init__(self, tokenizer: TokenizerLike):
        super().__init__(tokenizer)

        # Streaming state
        self.current_tool_name_sent: bool = False
        self.prev_tool_call_arr: list[dict] = []
        self.current_tool_id: int = -1
        self.streamed_args_for_tool: list[str] = []

        # FunctionGemma tokens
        self.tool_call_start_token: str = "<start_function_call>"
        self.tool_call_end_token: str = "<end_function_call>"

        # Regex patterns
        self.tool_call_regex = re.compile(
            r"<start_function_call>call:(\w+)\{(.*?)\}<end_function_call>"
            r"|<start_function_call>call:(\w+)\{(.*)",
            re.DOTALL,
        )
        self.arg_regex = re.compile(
            r"(\w+):<escape>(.*?)<escape>",
            re.DOTALL,
        )

        if self.model_tokenizer:
            self.tool_call_start_token_ids = self.model_tokenizer.encode(
                self.tool_call_start_token, add_special_tokens=False
            )
            self.tool_call_end_token_ids = self.model_tokenizer.encode(
                self.tool_call_end_token, add_special_tokens=False
            )
        else:
            self.tool_call_start_token_ids = []
            self.tool_call_end_token_ids = []

        self.buffered_delta_text = ""

    def _parse_arguments(self, args_str: str) -> dict:
        """Parse FunctionGemma argument string into a dictionary."""
        arguments = {}
        if not args_str:
            return arguments

        matches = self.arg_regex.findall(args_str)
        for key, value in matches:
            try:
                parsed_value = json.loads(value)
                arguments[key] = parsed_value
            except json.JSONDecodeError:
                arguments[key] = value

        return arguments

    def adjust_request(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        request = super().adjust_request(request)
        if request.tools and request.tool_choice != "none":
            request.skip_special_tokens = False
        return request

    def extract_tool_calls(
        self,
        model_output: str,
        request: ChatCompletionRequest,
    ) -> ExtractedToolCallInformation:
        if self.tool_call_start_token not in model_output:
            return ExtractedToolCallInformation(
                tools_called=False, tool_calls=[], content=model_output
            )

        try:
            matches = self.tool_call_regex.findall(model_output)

            if not matches:
                return ExtractedToolCallInformation(
                    tools_called=False, tool_calls=[], content=model_output
                )

            tool_calls: list[ToolCall] = []

            for match in matches:
                func_name = match[0] if match[0] else match[2]
                args_str = match[1] if match[1] else match[3]

                if not func_name:
                    continue

                arguments = self._parse_arguments(args_str)

                tool_calls.append(
                    ToolCall(
                        type="function",
                        function=FunctionCall(
                            name=func_name,
                            arguments=json.dumps(arguments, ensure_ascii=False),
                        ),
                    )
                )

            if tool_calls:
                content_end = model_output.find(self.tool_call_start_token)
                content = (
                    model_output[:content_end].strip() if content_end > 0 else None
                )

                return ExtractedToolCallInformation(
                    tools_called=True,
                    tool_calls=tool_calls,
                    content=content if content else None,
                )

            return ExtractedToolCallInformation(
                tools_called=False, tool_calls=[], content=model_output
            )

        except Exception:
            logger.exception("Error extracting tool calls from FunctionGemma response")
            return ExtractedToolCallInformation(
                tools_called=False, tool_calls=[], content=model_output
            )

    def _buffer_delta_text(self, delta_text: str) -> str:
        """Buffer incoming delta text to handle multi-token special sequences."""
        potential_start = "<start_function_call>"
        potential_end = "<end_function_call>"

        combined = self.buffered_delta_text + delta_text

        if combined.endswith(potential_start) or combined.endswith(potential_end):
            self.buffered_delta_text = ""
            return combined

        for tag in [potential_start, potential_end]:
            for i in range(1, len(tag)):
                if combined.endswith(tag[:i]):
                    self.buffered_delta_text = combined[-(i):]
                    return combined[:-i]

        self.buffered_delta_text = ""
        return combined

    def extract_tool_calls_streaming(
        self,
        previous_text: str,
        current_text: str,
        delta_text: str,
        previous_token_ids: Sequence[int],
        current_token_ids: Sequence[int],
        delta_token_ids: Sequence[int],
        request: ChatCompletionRequest,
    ) -> DeltaMessage | None:
        delta_text = self._buffer_delta_text(delta_text)
        current_text = previous_text + delta_text

        if self.tool_call_start_token not in current_text:
            if delta_text:
                return DeltaMessage(content=delta_text)
            return None

        try:
            start_count = current_text.count(self.tool_call_start_token)
            end_count = current_text.count(self.tool_call_end_token)
            prev_start_count = previous_text.count(self.tool_call_start_token)
            prev_end_count = previous_text.count(self.tool_call_end_token)

            if self.tool_call_start_token not in current_text:
                return DeltaMessage(content=delta_text)

            # Starting a new function call
            if start_count > prev_start_count and start_count > end_count:
                self.current_tool_id += 1
                self.current_tool_name_sent = False
                self.streamed_args_for_tool.append("")
                self.prev_tool_call_arr.append({})
                logger.debug("Starting new tool call %d", self.current_tool_id)
                return None

            # In the middle of a function call
            if start_count > end_count:
                last_start = current_text.rfind(self.tool_call_start_token)
                partial_call = current_text[
                    last_start + len(self.tool_call_start_token) :
                ]

                if partial_call.startswith("call:"):
                    func_part = partial_call[5:]

                    if "{" in func_part:
                        func_name = func_part.split("{")[0]
                        args_part = (
                            func_part.split("{", 1)[1] if "{" in func_part else ""
                        )

                        if not self.current_tool_name_sent and func_name:
                            self.current_tool_name_sent = True
                            self.prev_tool_call_arr[self.current_tool_id] = {
                                "name": func_name,
                                "arguments": {},
                            }
                            return DeltaMessage(
                                tool_calls=[
                                    DeltaToolCall(
                                        index=self.current_tool_id,
                                        type="function",
                                        id=make_tool_call_id(),
                                        function=DeltaFunctionCall(
                                            name=func_name
                                        ).model_dump(exclude_none=True),
                                    )
                                ]
                            )

                        if self.current_tool_name_sent and args_part:
                            current_args = self._parse_arguments(args_part)
                            if current_args:
                                current_args_json = json.dumps(
                                    current_args, ensure_ascii=False
                                )
                                prev_streamed = self.streamed_args_for_tool[
                                    self.current_tool_id
                                ]

                                if len(current_args_json) > len(prev_streamed):
                                    diff = current_args_json[len(prev_streamed) :]
                                    self.streamed_args_for_tool[
                                        self.current_tool_id
                                    ] = current_args_json
                                    self.prev_tool_call_arr[self.current_tool_id][
                                        "arguments"
                                    ] = current_args

                                    return DeltaMessage(
                                        tool_calls=[
                                            DeltaToolCall(
                                                index=self.current_tool_id,
                                                function=DeltaFunctionCall(
                                                    arguments=diff
                                                ).model_dump(exclude_none=True),
                                            )
                                        ]
                                    )

                return None

            # Function call just ended
            if end_count > prev_end_count:
                if self.current_tool_id >= 0 and self.current_tool_id < len(
                    self.prev_tool_call_arr
                ):
                    all_calls = self.tool_call_regex.findall(current_text)
                    args = {}
                    if self.current_tool_id < len(all_calls):
                        match = all_calls[self.current_tool_id]
                        if match[0]:
                            args_str = match[1]
                            args = self._parse_arguments(args_str)
                            self.prev_tool_call_arr[self.current_tool_id][
                                "arguments"
                            ] = args

                    if args:
                        args_json = json.dumps(args, ensure_ascii=False)
                        prev_streamed = self.streamed_args_for_tool[
                            self.current_tool_id
                        ]
                        if len(args_json) > len(prev_streamed):
                            diff = args_json[len(prev_streamed) :]
                            self.streamed_args_for_tool[self.current_tool_id] = (
                                args_json
                            )
                            return DeltaMessage(
                                tool_calls=[
                                    DeltaToolCall(
                                        index=self.current_tool_id,
                                        function=DeltaFunctionCall(
                                            arguments=diff
                                        ).model_dump(exclude_none=True),
                                    )
                                ]
                            )
                return None

            if delta_text:
                return DeltaMessage(content=delta_text)
            return None

        except Exception:
            logger.exception("Error in streaming tool call extraction")
            return None

_buffer_delta_text ¶

_buffer_delta_text(delta_text: str) -> str

Buffer incoming delta text to handle multi-token special sequences.
Source code in vllm/tool_parsers/functiongemma_tool_parser.py

def _buffer_delta_text(self, delta_text: str) -> str:
    """Buffer incoming delta text to handle multi-token special sequences."""
    potential_start = "<start_function_call>"
    potential_end = "<end_function_call>"

    combined = self.buffered_delta_text + delta_text

    if combined.endswith(potential_start) or combined.endswith(potential_end):
        self.buffered_delta_text = ""
        return combined

    for tag in [potential_start, potential_end]:
        for i in range(1, len(tag)):
            if combined.endswith(tag[:i]):
                self.buffered_delta_text = combined[-(i):]
                return combined[:-i]

    self.buffered_delta_text = ""
    return combined

Source code in vllm/tool_parsers/functiongemma_tool_parser.py

def _buffer_delta_text(self, delta_text: str) -> str:
    """Buffer incoming delta text to handle multi-token special sequences."""
    potential_start = "<start_function_call>"
    potential_end = "<end_function_call>"

    combined = self.buffered_delta_text + delta_text

    if combined.endswith(potential_start) or combined.endswith(potential_end):
        self.buffered_delta_text = ""
        return combined

    for tag in [potential_start, potential_end]:
        for i in range(1, len(tag)):
            if combined.endswith(tag[:i]):
                self.buffered_delta_text = combined[-(i):]
                return combined[:-i]

    self.buffered_delta_text = ""
    return combined

_parse_arguments ¶

_parse_arguments(args_str: str) -> dict

Parse FunctionGemma argument string into a dictionary.
Source code in vllm/tool_parsers/functiongemma_tool_parser.py

def _parse_arguments(self, args_str: str) -> dict:
    """Parse FunctionGemma argument string into a dictionary."""
    arguments = {}
    if not args_str:
        return arguments

    matches = self.arg_regex.findall(args_str)
    for key, value in matches:
        try:
            parsed_value = json.loads(value)
            arguments[key] = parsed_value
        except json.JSONDecodeError:
            arguments[key] = value

    return arguments

def _parse_arguments(self, args_str: str) -> dict:
    """Parse FunctionGemma argument string into a dictionary."""
    arguments = {}
    if not args_str:
        return arguments

    matches = self.arg_regex.findall(args_str)
    for key, value in matches:
        try:
            parsed_value = json.loads(value)
            arguments[key] = parsed_value
        except json.JSONDecodeError:
            arguments[key] = value

    return arguments


