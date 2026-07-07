# LLM Prompting

Prompting is split by responsibility so generation and update failures are easier to debug.

- `instructions.py`: long-lived system instructions for control/artifact calls.
- `contracts.py`: strict JSON output contracts.
- `builders.py`: prompt-builder functions that combine user/project context with contracts.

`backend.agents.prompts` is a compatibility facade. Keep new prompt work in this package.
