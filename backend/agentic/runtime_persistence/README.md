# Agent Runtime Persistence

This package records the durable agentic run trace after a generation/update turn.

- `input.py`: agent-run input payloads.
- `output.py`: top-level persistence orchestration.
- `records.py`: tool-call and agent-handoff records.
- `memory.py`: memory summary construction.
- `utils.py`: small value normalization helpers.

`backend.agent_runtime` is a compatibility facade. Keep persistence changes in this package.
