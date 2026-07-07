# Gemini client

This package wraps Gemini JSON generation, response parsing, transport errors, and token-usage logging.

- `client.py` owns `GeminiClient`, request payload construction, and model-call orchestration.
- `transport.py` performs the HTTP `generateContent` request and maps network/API failures.
- `parsing.py` repairs and parses Gemini JSON text responses.
- `response.py` extracts text from Gemini candidate responses.
- `usage.py` logs audit/token usage metadata.
- `config.py` loads `.env` values and parses timeout settings.
- `errors.py` defines `GeminiClientError`.

Import from `backend.agents.gemini_client`; `__init__.py` keeps the previous public names stable.
