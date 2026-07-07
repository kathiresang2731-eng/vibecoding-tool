# Gemini Tool Calling

This package keeps Gemini native tool-calling logic split by responsibility.

- `loop.py` runs the multi-step model/tool exchange.
- `schema.py` converts OpenAI-style tool schemas into Gemini declarations.
- `messages.py` converts chat messages into Gemini contents.
- `response.py` parses Gemini text and function-call responses.
- `mode.py`, `models.py`, `errors.py`, and `values.py` hold small shared primitives.

Import public helpers from `backend.agents.gemini_tool_calling` to keep callers stable.
