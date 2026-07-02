# Runtime action implementation modules

This package keeps stable low-level action implementations out of
`agent_runtime_loop.py`.

For the agent-wise map, start at `backend/agents/runtime_agents/README.md`.
The dispatcher imports through `runtime_agents/*_agent/handlers.py` so the main
execution path is explainable by agent name.

- `dispatcher.py` records supervisor handoff metadata and routes each legal action to one handler.
- `context.py` defines `RuntimeActionContext`, the shared argument object passed to handlers.
- `project_io.py` handles file reads, memory loading/persistence, validation, preview build, visual QA, and final write.
- `analysis.py` handles update analysis, prompt analysis, planning, and review actions.
- `dynamic.py` handles dynamic-agent workflow planning, specialist execution, and candidate patch integration.
- `generation.py` handles scoped updates plus full artifact generation/repair.
