# ASSUMPTIONS — vLLM Message Delivery Failure

- Primary user symptom: chat message is not reaching the vLLM server.
- Scope includes Remora LSP command path, agent execution path, and outbound model call path.
- vLLM is expected to be reachable via configured OpenAI-compatible endpoint (`base_url` from Remora config).
- Existing scan-manifest and startup issues may coexist, but this project isolates delivery to vLLM specifically.
- Success criteria:
  - A user chat message produces an outbound request to vLLM.
  - vLLM receives the request and returns a response.
  - Remora surfaces the response back to the UI path.
