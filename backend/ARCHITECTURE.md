# Backend Architecture

The backend is organized by responsibility. Start with the HTTP layer, then
follow calls into the agent system and infrastructure packages.

```text
backend/
|-- main.py                 FastAPI routes and process entry point
|-- api/                    HTTP models, generation pipeline, streaming, errors
|-- agents/                 Agent-wise runtime, orchestration, providers, tools, evals
|-- agentic/                Lower-level runtime persistence and tool implementations
|-- storage/                Postgres persistence and authorization
|-- local_workspace/        Safe local project file access
|-- runtime.py              Vite preview build and publication
|-- visual_qa/              Browser-based preview validation
|-- audit_logging/          Structured model and tool audit events
|-- code_diff/              Bounded project-file diff generation
|-- config.py               Environment-backed application settings
`-- llm/                    Legacy import compatibility only
```

## Request Flow

1. `main.py` receives an HTTP request.
2. `api/` validates input and prepares generation state.
3. `agents/orchestration/` routes the request and coordinates the run.
4. `agents/runtime_agents/` explains which agent owns each action.
5. `agents/agent_runtime/` executes bounded tools and project edits.
6. `storage/`, `local_workspace/`, and `runtime.py` persist, validate, and
   preview the result.
7. `visual_qa/` checks the rendered website before commit.
8. `audit_logging/` and `code_diff/` produce safe operational evidence.

## Dependency Direction

- `api` may call `agents` and infrastructure packages.
- `agents` may call public infrastructure facades such as
  `backend.agent_tools`, `backend.storage`, and `backend.visual_qa`.
- Infrastructure packages must not depend on HTTP routes.
- Provider-specific code stays behind `agents/providers`.
- New AI code must use `backend.agents.*`; `backend.llm.*` is migration-only.

## Naming Rules

- Use a package when a capability has multiple focused modules.
- Keep compatibility facades small and point to the source-of-truth package.
- Put executable agent behavior behind `agents/runtime_agents/*_agent`, not in
  metadata-only catalog folders.
- Keep generated logs, caches, and runtime build output outside source
  packages.
