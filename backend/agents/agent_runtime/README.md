# Agent runtime helpers

This package keeps focused helpers for the real agent runtime loop.

- `state.py` initializes runtime state and records agent messages/steps.
- `actions/` contains the executable runtime action handlers and dispatcher used by the main loop.
- `supervision/` owns the action registry, legal next-action policy, model supervisor guardrails, and scoped dynamic workflow planning.
- `model_agents.py` wraps Gemini/control-model calls for prompt analysis, planning, review, artifact generation, and model-call soft timeouts.
- `memory.py` handles project memory loading and persistence snapshots.
- `tooling.py` records backend tool calls, artifact validation, repair events, and rollback restores.
- `runtime_summary.py` builds the final runtime report and dynamic-agent lifecycle summaries.
- `scoped_update/` contains scoped patch parsing/validation helpers; `scoped_update/runtime.py` runs the scoped patch model workflow.
- `targeted_updates.py` contains deterministic targeted patch primitives; `targeted_runtime.py` applies the runtime shortcut.
- `progress/` contains runtime progress messages, completion proof, preview sync, and loop-budget enforcement.
- `compaction.py`, `prompts.py`, `timeouts.py`, `schemas.py`, `values.py`, `file_ops.py`, `fallbacks.py`, and `scaffolding.py` contain shared primitives used by the runtime modules.

`backend/agents/agent_runtime_loop.py` remains the compatibility entry point for
the workflow. Keep orchestration there; put new helper behavior into the
focused module above.
