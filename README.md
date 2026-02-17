# Remora

Local code analysis and enhancement using FunctionGemma subagents.

## Ollama setup

Remora uses the stock FunctionGemma model via Ollama. Install Ollama and pull the model:

```bash
ollama pull functiongemma-4b-it
```

Install the `llm` Ollama plugin after installing Remora:

```bash
llm install llm-ollama
```

Verify the model is reachable:

```bash
llm -m ollama/functiongemma-4b-it "Say hello"
```
