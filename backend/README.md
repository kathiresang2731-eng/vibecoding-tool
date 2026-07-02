# Vibe Platform Backend

Python backend for the local prompt-to-website builder foundation. It provides
Postgres-backed projects, files, versions, dev auth, generation orchestration,
and local Vite preview builds.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the responsibility-based package map.
See [AGENTIC_EXECUTION_FLOW.md](AGENTIC_EXECUTION_FLOW.md) for the Gemini-only
dynamic-agent runtime and source-of-truth generation flowchart.

## Package Map

- `api/`: HTTP request handling, streaming, and failure responses.
- `agents/`: agent-wise runtime, orchestration, providers, tools, and evals.
- `agentic/`: lower-level backend tool implementations and agent-run persistence.
- `storage/`: Postgres data access and permissions.
- `local_workspace/`: safe local project reads and writes.
- `visual_qa/`: rendered preview checks.
- `audit_logging/`: structured operational telemetry.
- `code_diff/`: bounded project change summaries.
- `llm/`: legacy import compatibility; do not add new implementation here.

## Environment

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Set the local backend configuration in `.env`:

```env
DATABASE_URL=postgres://user:password@localhost:5432/vibe_builder
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
DEV_USER_EMAIL=dev@vibe.local
GEMINI_API_KEY=your_real_key
GEMINI_MODEL=gemini-3.1-pro-preview
GEMINI_TIMEOUT_SECONDS=180
REPAIR_MODEL_SOFT_TIMEOUT_SECONDS=90
ENABLE_GEMINI_GOOGLE_SEARCH=true
GEMINI_TOOL_CALLING_MODE=VALIDATED
AUDIT_LOG_DIR=logs
GEMINI_TOKEN_USAGE_LOG_DIR=gemini_token_usage
DYNAMIC_AGENT_TIMEOUT_SECONDS=60
DYNAMIC_AGENT_MAX_TOOL_CALLS=6
```

Do not use `VITE_GEMINI_API_KEY`; model provider keys must stay server-side.
Gemini handles routing, conversation, planning, dynamic-agent tool calling,
generation, review, and repair. Local GPT settings remain compatibility-only
and are not used by the normal website-builder runtime.

## Run

```bash
python3 backend/main.py
```

Alternative Uvicorn command:

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8787
```

Health check:

```bash
curl http://127.0.0.1:8787/api/health
```

Session:

```bash
curl http://127.0.0.1:8787/api/session
```

Create a project:

```bash
curl -X POST http://127.0.0.1:8787/api/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"Local website"}'
```

Generate files for a project:

```bash
curl -X POST http://127.0.0.1:8787/api/projects/PROJECT_ID/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Build a website for a B2B SaaS CRM"}'
```

Build a preview:

```bash
curl -X POST http://127.0.0.1:8787/api/projects/PROJECT_ID/build-preview
```

## Generation contract

Every successful `/api/generate` response is packaged by the Python backend into
these six top-level sections:

```json
{
  "multi_agent_system": {},
  "gemini_tool_calling_setup": {},
  "google_adk_usage": {},
  "orchestration_flow": {},
  "agent_to_agent_communication": {},
  "proactive_thinking": {}
}
```

The generated website artifacts live inside:

```text
orchestration_flow.generated_website
```

For React project generation, `generated_website.files` is strict: it must include
`src/App.jsx`, every file must have non-empty code, and paths must stay inside
the allowed project surface. Static HTML projects may instead use root
`index.html`, common root CSS files, and common root JavaScript files.

## Dynamic Agents V2

- Core and reusable specialist definitions are global.
- Experimental dynamic agents are owned by one user and persisted in
  `dynamic_agent_definitions` for reuse across that user's projects.
- Dynamic agents can use only `READ_PROJECT_FILES` and `LOAD_PROJECT_MEMORY`.
- Python binds user/project identity, validates candidate file proposals,
  integrates accepted proposals, and owns validation, preview QA, rollback,
  and final commit.
- Experimental agents require three successful runs, at least an 80% success
  rate, and no safety violations before promotion. Three consecutive failures
  disable the agent.

## Audit Logs

The backend writes supplementary append-only UTC daily JSONL audit streams:

```text
logs/YYYY-MM-DD/query_model_tool.jsonl
logs/YYYY-MM-DD/dynamic_agents.jsonl
```

Prompt/output previews are truncated and hashed, secret-like fields are
redacted, and generated code bodies are never written to these logs. Postgres
agent runs, messages, and tool calls remain the queryable source of truth.
