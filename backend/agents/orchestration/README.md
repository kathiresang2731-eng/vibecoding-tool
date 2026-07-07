# Website Generation Orchestration

This package keeps the website builder pipeline split by responsibility.

- `runner.py`: main `WorktualGenerationOrchestrator` flow and stage execution.
- `routing.py`: intent routing tool normalization and repair.
- `conversation.py`: greeting, missing-detail, and confirmation responses.
- `artifact_response.py`: generated website artifact normalization and response assembly.
- `runtime_metadata.py`: final runtime metadata projection and backend routing response updates.
- `tool_registry.py`: tool registry merging and tool-call logging.
- `provider_utils.py`: provider naming and default provider helpers.
- `constants.py`: orchestration stages, routing config, agent team, and tool definitions.
- `state.py`: `GenerationPipelineState`.

`backend.agents.orchestrator` is a compatibility facade. Keep new orchestration
logic in this package instead of expanding the facade.
