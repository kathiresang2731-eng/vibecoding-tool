# Runtime Agents

Start here when explaining the agent-wise backend flow.

`registry.py` is the source of truth for:

- which runtime agents exist
- which actions each agent can perform
- which backend tools each action may call
- the high-level phase order of the agent loop

## Main Flow

1. `Supervisor Agent` chooses the next legal action from `ACTION_REGISTRY`.
2. `agent_runtime/actions/dispatcher.py` records the handoff and calls the matching runtime-agent handler.
3. The selected agent handler reads or updates shared runtime state.
4. Quality gates validate, build, preview, and optionally repair.
5. `Commit Agent` writes files only after validation and preview pass.
6. `Memory Agent` persists the final run summary.

## Agent Folders

- `memory_agent/`: project reads, memory loading, memory persistence.
- `error_handling_agent/`: runtime/build/API/database error diagnosis.
- `update_analysis_agent/`: existing-project update classification and scoped-file selection.
- `scoped_update_agent/`: bounded update patches over approved existing files.
- `prompt_analyst_agent/`: structured brief creation.
- `planner_agent/`: section, layout, interaction, and implementation planning.
- `agent_registry_agent/`: dynamic specialist planning and execution.
- `review_agents/`: UX and accessibility review agents.
- `code_agent/`: full artifact generation.
- `code_generator_agent/`: integration of validated dynamic-agent patches.
- `materialize_agent/`: candidate-file materialization before quality gates.
- `repair_agent/`: artifact repair after validation/build failures.
- `validation_agent/`: artifact contract validation.
- `preview_agent/`: staged preview build.
- `visual_qa_agent/`: preview integrity QA.
- `commit_agent/`: final file write after all completion gates pass.

The older `agent_runtime/actions/*.py` modules still contain stable helper
implementations. New agent-facing code should enter through these folders so the
runtime remains explainable by agent name.
