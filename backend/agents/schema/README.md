# LLM Response Schema

This package owns the six-section generation response contract.

- `constants.py` defines required top-level sections and required nested paths.
- `validation.py` validates the response shape.
- `response.py` creates and sanitizes generation responses.
- `helpers.py` contains nested traversal helpers.
- `errors.py` contains the contract exception.

Import from `backend.agents.schema` to keep callers independent of the internal
file layout.
