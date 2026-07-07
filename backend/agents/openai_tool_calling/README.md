# OpenAI Tool Calling

This package keeps the OpenAI Responses API tool loop split by responsibility.

- `client.py` owns Responses API transport and environment-based client creation.
- `loop.py` runs the multi-step function-call exchange.
- `response.py` parses function calls, arguments, and text output.
- `models.py`, `errors.py`, `config.py`, and `values.py` hold small shared primitives.

Import public helpers from `backend.agents.openai_tool_calling` so callers do not
depend on internal file layout.
