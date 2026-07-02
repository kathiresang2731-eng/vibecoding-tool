# LLM Providers

This package contains provider adapters and role enforcement for the website
builder pipeline.

- `gemini.py` owns the Gemini dual-role provider.
- `local_model.py` owns local control-model adapters and endpoint support.
- `openai.py` owns the OpenAI Responses API tool-calling provider.
- `mock.py` provides deterministic local artifacts for tests/development.
- `roles.py`, `constants.py`, `errors.py`, and `protocols.py` hold shared provider contracts.

Import public names from `backend.agents.providers` to avoid coupling callers to
the internal module layout.
