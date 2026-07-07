# Agentic flow projection

This package builds the legacy Python agentic-flow projection from a normalized generation response.

- `core.py` owns `execute_agentic_flow` and branch routing.
- `artifact.py` builds the website generation/update step sequence.
- `conversation.py` builds the conversation-only step sequence.
- `steps.py` creates canonical agent step dictionaries.
- `handoffs.py` derives handoff messages between adjacent steps.
- `memory.py` prepares generation memory text.
- `constants.py` contains the runtime name and static agent roster.
- `values.py` contains safe coercion helpers.

Import from `backend.agents.agentic_flow`; `__init__.py` keeps the old public names stable.
