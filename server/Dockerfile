FROM vllm/vllm-openai:latest

WORKDIR /app
COPY entrypoint.sh /app/entrypoint.sh
COPY tool_chat_template_functiongemma.jinja /app/tool_chat_template_functiongemma.jinja
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
