# Website Builder Backend Workflow Architecture

## End-to-End Flow

User prompt -> Frontend workspace -> FastAPI generation endpoint -> generation pipeline -> Gemini routing -> orchestration stage graph -> real agent runtime loop -> backend tools -> validation -> staged Vite preview -> browser/preview QA -> WRITE_PROJECT_FILES -> local sync -> memory/runtime persistence -> UI response.

## Source of Truth

- API entry: `backend/main.py`
- Generation pipeline: `backend/api/generation.py`
- Orchestrator: `backend/agents/orchestration/runner.py`
- Runtime loop: `backend/agents/agent_runtime_loop.py`
- Runtime actions: `backend/agents/agent_runtime/actions/*`
- Tool registry: `backend/agentic/tools/*`
- Dynamic agents: `backend/agents/dynamic_agenting/*`
- A2A transcript: `backend/agents/a2a/*`
- Validation: `backend/agents/artifacts/*`
- Preview runtime: `backend/runtime.py`
- Visual QA: `backend/visual_qa/*`

## Main Runtime Flow

1. User creates/selects a backend or local-folder-linked project.
2. Prompt enters `/api/projects/{project_id}/generate` or `/generate-stream`.
3. Backend loads user, project, original files, local folder state, and telemetry.
4. Gemini control/artifact providers are created.
5. Orchestrator routes the request and optionally pauses for confirmation.
6. Conversation turns return text only.
7. Generation/update turns enter the real supervised agent loop.
8. Python-bound backend tools read files, load memory, validate artifacts, build staged previews, run QA, write files, sync local folders, and persist memory.
9. Runtime metadata is projected into A2A, Google ADK, and LangChain summaries.
10. Agent run, generation run, tool calls, messages, memory, local sync, and audit logs are persisted.

## Dynamic Agent Flow

Dynamic agents are user-scoped reusable specialists. The registry matches capability tasks to existing agents, creates experimental agents only for allowed specialist tasks, executes them with guarded tools, validates candidate changes, records lifecycle metrics, promotes successful agents, and disables unsafe or repeatedly failing agents.
