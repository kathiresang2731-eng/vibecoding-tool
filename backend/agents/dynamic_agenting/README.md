# Dynamic agent modules

This package owns the agentic website-builder runtime pieces that used to live in `backend/agents/dynamic_agents.py`. The legacy module now re-exports these symbols so older imports and tests keep working.

- `constants.py` keeps capability and safety policy constants.
- `config.py` reads dynamic-agent environment limits.
- `models.py` defines serializable agent, task, assignment, and workflow dataclasses.
- `policy.py` enforces which capabilities/tools can become reusable dynamic agents.
- `prompts.py` stores reusable dynamic-agent system prompts and specialist task prompt builders.
- `registry.py` creates, scores, assigns, promotes, and disables agent definitions.
- `planning.py` decomposes requests and builds guarded workflow plans.
- `execution.py` runs dynamic specialists with bounded tools and candidate-change validation.
- `persistence.py` hydrates and persists reusable user-scoped agents.
