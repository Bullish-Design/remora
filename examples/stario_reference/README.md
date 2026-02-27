# Stario Reference Frontend

This is a minimal Stario-based frontend template that connects to a Remora service.

## Requirements

- Python 3.14+
- `stario` and an HTTP client such as `httpx`

## Running

```bash
export REMORA_URL="http://localhost:8420"
python app.py
```

Then open `http://localhost:9000/` to view the dashboard shell.

## Notes

- `/subscribe` proxies Remora's Datastar patch stream.
- `/run` and `/input` forward JSON requests to Remora.
- This template is intentionally thin and should be customized for your UI.
