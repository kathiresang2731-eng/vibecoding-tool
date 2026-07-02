# ADK mapping modules

This package owns the static Google ADK mapping used by generation prompts and response metadata.

- `constants.py` stores ADK agent mappings, runtime plan bullets, and notes.
- `mapping.py` builds the structured mapping payload.
- `formatting.py` renders the mapping as JSON for prompts.

`backend/agents/adk_mapping.py` remains the compatibility facade for existing imports.
