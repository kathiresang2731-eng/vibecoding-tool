# Storage

Postgres persistence for users, projects, generated files, agent runtime records, memory, preview versions, and events.

- `store.py` defines the concrete `PostgresStore` facade.
- `projects.py` owns project and project-file persistence.
- `agent_runtime.py` owns generation runs, agent runs, messages, tool calls, and checkpoints.
- `memory.py` owns memory items and dynamic agent definitions.
- `versions_events.py` owns preview versions and event history.
- `bootstrap.py` keeps database schema DDL out of runtime methods.
- `permissions.py` centralizes read/write authorization checks.

Import public storage APIs from `backend.storage`; the previous module import surface is preserved.
