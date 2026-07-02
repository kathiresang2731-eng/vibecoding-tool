# Website Builder Engineer KT

## Purpose

This KT explains the active Worktual AI website-builder flow for engineers who need to debug, extend, or test the platform. It starts where the user types a prompt in the React workspace and follows the request through FastAPI, generation streaming, orchestration, agent actions, Gemini calls, validation, staged preview, file writes, memory persistence, local write-back, and UI refresh.

Scope is the active website-builder platform. It excludes generated runtime folders, caches, logs, `node_modules`, and unrelated leftovers unless they affect the active flow.

## One-Screen Flow

```text
src/main.jsx prompt form
  -> submitWebsitePrompt
  -> streamGeneration
  -> POST /api/projects/{project_id}/generate-stream
  -> backend/main.py route
  -> backend/api/generation_stream.py worker + NDJSON events
  -> backend/api/generation.py run_generation_pipeline
  -> backend/agents/generator.generate_website
  -> backend/agents/orchestration/runner.py
  -> backend/agents/agent_runtime_loop.py
  -> backend/agents/agent_runtime/actions/*
  -> backend/agentic/tools/*
  -> artifact validation
  -> staged Vite preview
  -> preview QA
  -> WRITE_PROJECT_FILES
  -> optional local workspace/browser folder sync
  -> project memory + runtime persistence
  -> complete payload back to src/main.jsx
```

## Frontend Entry Flow

### `src/main.jsx`

This is the active React application entrypoint. `src/App.jsx` is only a null stub and is not the website-builder platform entrypoint.

Main responsibilities:

- Defines `API_BASE_URL` from `VITE_API_BASE_URL` or defaults to `http(s)://<current-host>:8787`.
- Owns project list, active project, selected file, Monaco editor content, chat messages, live progress, preview URL, model selection, and browser-folder state.
- Renders the workspace shell: left project panel, center chat/progress panel, right code/preview panel.
- Renders the prompt form and sends user prompts.
- Reads, imports, and writes browser-selected local folders through browser File System Access APIs where permission is available.
- Calls backend project, file, local folder, generation, preview, and event APIs.

Important functions:

| Function | Usage |
| --- | --- |
| `generateWebsite(event)` | Form submit handler. Prevents default submit and calls `submitWebsitePrompt(prompt.trim())`. |
| `submitWebsitePrompt(nextPrompt)` | Main frontend generation/update flow. Sets loading state, clears prompt, appends user chat, streams backend generation, appends assistant message, applies returned files, updates preview URL, syncs browser workspace, refreshes events, and displays failures. |
| `streamGeneration(projectId, prompt, model, onProgress)` | Sends `POST /api/projects/{project_id}/generate-stream` with `{ prompt, model? }`, reads NDJSON from `response.body`, and returns the final complete payload. |
| `handleGenerationStreamLine(line, onProgress, finalPayload)` | Parses one NDJSON line. `progress` updates UI progress. `complete` stores final payload. `error` throws a frontend error with backend failure detail. |
| `api(path, options)` | Shared JSON fetch helper for normal non-stream API calls. |
| `saveCurrentFile()` | Saves Monaco editor edits with `PUT /api/projects/{project_id}/files/{path}` and then attempts browser-folder write-back. |
| `syncGeneratedFilesToBrowserWorkspace()` | Writes returned generated files to the browser-selected folder when a writable directory handle exists. |

Frontend stream contract:

- The UI expects NDJSON lines.
- `progress` events are merged into live progress UI.
- `complete` provides the payload with `generation`, `files`, `generation_run`, `agent_run`, `local_sync`, and `local_sync_error`.
- `error` becomes the visible "Generation failed" message and also lands in live progress as `generation.failed`.
- The backend has an internal `end` queue event, but it is a worker sentinel and is not part of the UI contract.

Frontend routes/API calls used by the workspace:

| UI action | Backend route |
| --- | --- |
| Health/session load | `GET /api/health`, `GET /api/session` |
| List/create/open/delete project | `GET /api/projects`, `POST /api/projects`, `GET /api/projects/{id}`, `DELETE /api/projects/{id}` |
| List/save files | `GET /api/projects/{id}/files`, `PUT /api/projects/{id}/files/{path}` |
| Link/sync local workspace | `PUT /api/projects/{id}/local-path`, `POST /api/projects/{id}/sync-local` |
| Browse/create local folders | `GET /api/local-directories`, `POST /api/local-directories` |
| Browser folder import | `POST /api/projects/{id}/import-directory` |
| Generate/update stream | `POST /api/projects/{id}/generate-stream` |
| Manual preview build | `POST /api/projects/{id}/build-preview` |
| Read preview asset | `GET /api/previews/{project_id}/{version_id}/...` |
| Runtime/event panel | `GET /api/events?project_id=...` |

## FastAPI Entry Flow

### `backend/main.py`

This file owns FastAPI route declarations and wires shared API helpers to the app.

Generation-related route path:

1. `generate_project_stream()` handles `POST /api/projects/{project_id}/generate-stream`.
2. `_read_generate_request()` accepts JSON, raw text fallback, or query params.
3. `_coerce_generate_request_payload()` normalizes supported prompt keys: `prompt`, `message`, `content`, `text`, `query`, `input`.
4. Empty prompt raises `400`.
5. Valid prompts return `StreamingResponse(generation_stream_events(...), media_type="application/x-ndjson")`.
6. The route injects `context` and `user` with FastAPI dependencies.

Non-stream generation also exists at `POST /api/projects/{project_id}/generate`, but the active React flow uses `/generate-stream`.

Project/local/preview responsibilities:

- Project CRUD and file save/list APIs call `context.store`.
- Local workspace routes use `backend/api/local_workspaces.py` and `backend/local_workspace`.
- Browser folder import accepts files from the frontend and stores them in the backend project store.
- Preview serving uses `backend/runtime.py` to locate built assets and `backend/api/previews.py` to rewrite absolute asset references.

## Generation Stream

### `backend/api/generation_stream.py`

This module isolates streaming behavior from the main pipeline.

Core responsibilities:

- Starts `run_generation_pipeline` inside a daemon worker thread.
- Creates a `Queue` for progress, complete, error, and internal end events.
- Wraps the worker in a telemetry scope.
- Normalizes progress events with status, detail, and timestamp.
- Tracks the latest running step/message for heartbeat and failure enrichment.
- On worker success, queues `{ "type": "complete", "payload": ... }`.
- On worker failure, converts exceptions through `generation_failure_payload()` and queues `{ "type": "error", ... }`.
- Emits heartbeat `progress` events when no event arrives before `GENERATION_STREAM_HEARTBEAT_SECONDS`.
- Serializes events with `ndjson_event()`.

Important distinction:

- `progress`, `complete`, and `error` are sent to the frontend.
- `end` is only an internal queue sentinel used to stop the generator loop.

## Generation Pipeline

### `backend/api/generation.py`

`run_generation_pipeline()` is the first full backend business-flow function after the stream layer.

Pipeline responsibilities:

1. Create/reuse telemetry.
2. Log `query.received`.
3. Load the project and enforce permissions via `context.store.get_project`.
4. Load current files through `context.store.list_files`.
5. Load recent chat history.
6. Build Gemini chat history from current project context plus prior chat messages.
7. Detect follow-up enhancement/error prompts and enrich `effective_prompt` with previous context.
8. Persist the user chat message.
9. Handle greeting-only prompts with a deterministic fast path.
10. For non-greeting prompts, construct Gemini providers and create an agent run.
11. Call `generate_website()` with provider roles, project ID, tool context, user, and progress callback.
12. Persist generated files or use tool-source-of-truth output from the agent runtime.
13. Optionally sync linked local folder.
14. Create generation run.
15. Persist agent runtime output, tool calls, messages, memory, and model chat message.
16. Complete agent run or mark it failed.

### Greeting fast path

`is_greeting_only_prompt()` recognizes greetings such as `hi`, `hello`, `hey`, and related simple variants.

For greeting-only prompts:

- Gemini is not constructed.
- No generation/update tools run.
- No files are written.
- `current_project_summary()` inspects current project name, workspace mode, local path/browser-folder metadata, file count, key files, and sample paths.
- `format_greeting_project_summary()` returns a concise project summary plus "Tell me what you want to build or update next."
- User and assistant chat messages are persisted.
- Agent/generation runs are recorded as completed deterministic conversation turns.

Workspace summary modes:

| Mode | Detection |
| --- | --- |
| `local` | `project.local_path` is set. |
| `browser_local` | Description starts with `Browser-selected local workspace:`. |
| `browser_upload` | Description starts with `Browser-uploaded project folder:`. |
| `backend` | No linked local/browser workspace metadata. |

## Orchestrator Flow

### `backend/agents/generator/__init__.py`

This package exports `generate_website`, `generate_website_or_error`, and `normalize_generation`. The active path calls `generate_website`, which delegates into the orchestration service/runner.

### `backend/agents/orchestration/runner.py`

`WorktualGenerationOrchestrator` owns the high-level AI flow.

Main responsibilities:

- Resolve control and artifact providers.
- Check any pending confirmation for the project.
- Evaluate confirmation replies as confirm, revise, cancel, new request, or still pending.
- Route new prompts through `route_generation_action_tool()`.
- Optionally prepare and persist a confirmation brief before any file-changing work.
- Build response sections such as multi-agent metadata, Gemini tool setup, ADK projection, orchestration flow, A2A communication, and proactive thinking.
- For conversation-only intents, call `generate_conversation_response()` and stop before artifact generation.
- For generation/update intents, call `execute_real_agent_runtime_loop()`.

Primary intents:

| Intent | Result |
| --- | --- |
| `greeting` | Conversation-only response. In the current API pipeline, simple greetings are handled even earlier by the deterministic fast path. |
| `needs_more_detail` | Conversation-only request for missing website details. |
| `project_info` | Conversation-only current project summary/explanation. |
| `needs_confirmation` | Pauses execution until explicit user confirmation. |
| `website_generation` | Enters real runtime loop for new project artifact. |
| `website_update` | Enters real runtime loop for existing project update. |

Confirmation behavior:

- Confirmation state is stored in project memory/runtime context.
- Confirm resumes the original effective request.
- Revise creates a revised brief and pauses again if required.
- Cancel marks pending work cancelled with no file writes.
- A new request supersedes the pending confirmation.

## Agent Runtime Loop

### `backend/agents/agent_runtime_loop.py`

`execute_real_agent_runtime_loop()` is the Python-owned guarded execution loop.

Core safety model:

- The runtime state starts with the routed prompt.
- Only legal next actions from `available_runtime_actions()` can run.
- `supervisor_choose_next_action()` selects or policy-falls back to the next action.
- Each action is executed by `execute_loop_action()`.
- Completion requires proof: files exist, artifact valid, staged preview ready, visual QA passed, files committed, and memory prepared.
- If the loop exhausts budget or has no legal action, previous files are restored where possible.
- If a repairable error occurs, the error is stored in `state["repair_errors"]` and the loop can run repair actions until the repair budget is exhausted.

Important budget controls:

- `runtime_timeout_seconds()`
- `scoped_update_sequence_timeout_seconds()`
- `artifact_model_soft_timeout_seconds()`
- `repair_model_soft_timeout_seconds()`
- `max_steps`
- `max_tool_calls`
- effective repair attempt budget

Common failure categories seen in UI:

| Symptom | Runtime source |
| --- | --- |
| Scoped update timed out | `RUN_SCOPED_UPDATE_AGENT` waiting for model patch under scoped update timeout. |
| Project safety check blocked update | Scoped update validation rejected empty, broad, unsafe, or unapproved changes. |
| Staged Vite preview failed | `BUILD_STAGED_PROJECT_PREVIEW` returned version status other than `ready`. |
| Import unresolved | Preview build log classified by project IO repair helpers. |
| Preview/runtime crash | Vite built but visual/browser QA or runtime console checks failed. |
| No local write | `WRITE_PROJECT_FILES` or local sync failed after backend commit attempt. |

### `backend/agents/agent_runtime/actions/dispatcher.py`

Maps runtime action names to handler functions.

Active actions:

```text
READ_PROJECT_FILES
LOAD_PROJECT_MEMORY
RUN_UPDATE_ANALYST
RUN_ERROR_HANDLING_AGENT
RUN_SCOPED_UPDATE_AGENT
RUN_PROMPT_ANALYST
RUN_DYNAMIC_AGENT_PLANNER
RUN_PLANNER
RUN_DYNAMIC_SPECIALISTS
RUN_UX_REVIEW_AGENT
RUN_ACCESSIBILITY_AGENT
RUN_CODE_AGENT
RUN_REPAIR_AGENT
RUN_DYNAMIC_PATCH_INTEGRATOR
VALIDATE_PROJECT_ARTIFACT
BUILD_STAGED_PROJECT_PREVIEW
RUN_PREVIEW_VISUAL_QA
WRITE_PROJECT_FILES
PERSIST_PROJECT_MEMORY
```

### Runtime action groups

| Group | Files | Responsibility |
| --- | --- | --- |
| Read/context | `actions/project_io.py`, `memory.py`, `targeted_updates.py` | Read project files, build file keyword index, load memory, hydrate dynamic agent registry. |
| Analysis | `actions/analysis.py`, `model_agents.py`, `update_analysis/__init__.py` | Prompt analysis, update analysis, error diagnosis, planner, UX/accessibility review. |
| Generation/update | `actions/generation.py`, `scoped_update/runtime.py`, `model_agents.py` | Run full artifact code agent, repair agent, or scoped update agent. |
| Dynamic specialists | `actions/dynamic.py`, `dynamic_agenting/*` | Plan, create, execute, and integrate bounded specialist outputs. |
| Validation/preview | `actions/project_io.py`, `artifacts/*`, `runtime.py`, `visual_qa/*` | Validate artifact shape, normalize scaffold/imports, build staged preview, run QA. |
| Commit/memory | `actions/project_io.py`, `agentic/tools/handlers.py`, `storage/*` | Write files, sync local folder, persist project memory and runtime state. |

## Scoped Update Flow

### `backend/agents/agent_runtime/update_analysis/__init__.py`

`run_update_analysis_agent()` calls the update-analysis prompt and then normalizes the response.

It decides:

- `update_mode`: `targeted_patch`, `bug_fix`, `feature_patch`, `full_regeneration`, or `needs_clarification`.
- `execution_strategy`: deterministic patch, scoped model patch, full dynamic workflow, or clarify.
- Candidate existing files, capped and validated against the actual file index.
- Candidate new files only when feature patch requires them.
- Preserve rules and scoped update tasks.
- Whether error diagnosis should force bug-fix behavior.

The update analyzer intentionally avoids static backend path choices. It derives candidate files from current project files, code-search matches, error diagnosis, frontend/domain clues, and user request.

### `backend/agents/agent_runtime/scoped_update/runtime.py`

`run_scoped_update_agent()` and `run_scoped_update_sequence()` own bounded existing-project updates.

Key responsibilities:

- Filter update-analysis candidate files against loaded project files.
- Prioritize candidate paths for known problem classes, including onboarding chat changes and undefined `.name` runtime crashes.
- Reject oversized files for safe patching.
- Run deterministic fallbacks for known safe fixes before calling the model.
- Build a scoped edit plan and call Gemini with `build_scoped_update_patch_prompt()`.
- Require strict JSON and a scoped response schema.
- Retry once for invalid JSON or empty patch responses.
- Validate returned edits/changed files with `validate_scoped_update_changes()`.
- For multi-step updates, apply each task to an in-memory working file set and only return final bounded changed files.

Why scoped update failures are expected sometimes:

- The agent returned no usable edits.
- The edit target was ambiguous.
- A changed file was outside approved paths.
- The model tried to rewrite too much of a file.
- The primary patch call exceeded the scoped update timeout.
- Validation or preview later proved the patch unsafe.

## Prompt and Model Usage

### `backend/agents/prompts.py`

This is the public prompt facade. It re-exports prompt builders, contracts, and system instructions from `backend/agents/prompting`.

Use this import path from runtime code unless there is a strong reason to import from lower-level prompt modules.

### `backend/agents/prompting/builders.py`

Important prompt builders:

| Builder | Used for |
| --- | --- |
| `build_routing_prompt()` | Classifies greeting, needs-more-detail, project-info, generation, or update. |
| `build_routing_repair_prompt()` | Repairs invalid routing JSON. |
| `build_conversation_response_prompt()` | Produces assistant response for conversation-only turns. |
| `build_update_analysis_prompt()` | Selects smallest safe update mode, candidate files, new files, required agents, and preserve rules. |
| `build_scoped_update_patch_prompt()` | Requests strict scoped SEARCH/REPLACE edits for approved files only. |
| `build_task_decomposition_prompt()` | Breaks complex generation into dynamic capability tasks. |
| `build_dynamic_agent_definition_prompt()` | Defines reusable specialist agents. |
| `build_workflow_planning_prompt()` | Plans safe task order and parallel groups. |
| `build_domain_research_prompt()` | Uses deterministic or Gemini search-assisted domain context. |
| `build_website_prompt()` | Requests final website/backend/full-stack artifact JSON. |

### `backend/agents/prompting/instructions.py`

Important instructions:

- `SYSTEM_INSTRUCTION`: global Gemini-native website-builder policy. Requires valid JSON, current live code context, React/Vite/Tailwind conventions, modular architecture, and guarded updates.
- `ENTERPRISE_AI_NATIVE_BLUEPRINT`: higher-level generation quality policy for component architecture, tokens, adaptive copy, states, accessibility, and update reliability.
- `build_gemini_system_instruction()`: combines the global system instruction, blueprint, and optional extra instruction.
- `ROUTING_SYSTEM_INSTRUCTION`: strict routing JSON only.
- `CONVERSATION_SYSTEM_INSTRUCTION`: strict conversation JSON only.

### `backend/agents/agent_runtime/model_agents.py`

This module wraps model calls for runtime agents:

- Prompt analyst: system instruction `"You are a prompt analyst agent. Return strict JSON only."`
- Domain research: optional Gemini Google Search grounding when enabled.
- Planner: system instruction `"You are a website planning agent. Return strict JSON only."`
- Review agents: UX/accessibility style structured review.
- Code/repair artifact agent: builds `build_website_prompt()` with compact project context and previous build errors when repairing.
- Soft-timeout model execution via `run_artifact_provider_with_soft_timeout()`.

### Gemini provider/client flow

| File | Responsibility |
| --- | --- |
| `backend/agents/providers/gemini.py` | Provider wrapper used as both control and artifact provider. Holds chat history and delegates JSON generation to `GeminiClient`. |
| `backend/agents/gemini_client/client.py` | Builds Gemini payloads, loads env config, logs model calls, posts requests, extracts text, parses JSON, logs token usage. |
| `backend/agents/gemini_client/transport.py` | Low-level `urllib.request` call to `generateContent`, HTTP/network/timeout error wrapping. |
| `backend/agents/gemini_client/parsing.py` | Parses model text into JSON. |
| `backend/agents/gemini_client/response.py` | Extracts model text from Gemini response payload. |
| `backend/agents/gemini_client/config.py` | Loads dotenv and parses timeout settings. |
| `backend/agents/gemini_client/usage.py` | Logs token usage metadata. |

## Backend Tools

### `backend/agent_tools.py`

Compatibility facade that re-exports tool definitions, handlers, registry, and visual QA runner from `backend/agentic/tools`.

### `backend/agentic/tools/registry.py`

Defines tool schemas and dispatches tool calls.

Important tools:

| Tool | Purpose |
| --- | --- |
| `READ_PROJECT_FILES` | Reads current supported files from backend store or linked local workspace. |
| `LOAD_PROJECT_MEMORY` | Loads relevant persisted project/user memory. |
| `PERSIST_PROJECT_MEMORY` | Stores generation summary, project state, dynamic registry, and error checkpoints. |
| `WRITE_PROJECT_FILES` | Commits candidate files to the project store and linked local folder after checks pass. |
| `VALIDATE_PROJECT_ARTIFACT` | Validates generated website artifact shape/files. |
| `BUILD_PROJECT_PREVIEW` | Builds committed project files. |
| `BUILD_STAGED_PROJECT_PREVIEW` | Builds candidate files before final commit. |
| `RUN_PREVIEW_VISUAL_QA` | Checks staged preview readiness and browser/render warnings. |
| `SYNC_LOCAL_PROJECT` | Pulls from or pushes to linked local workspace. |

### `backend/agentic/tools/handlers.py`

Implements tool behavior. Runtime actions call tools through `execute_tool_call()`, which logs requests/results into runtime state and audit logs.

Important safety point:

- Models do not write files directly.
- Runtime actions request Python tools.
- Python validates arguments, project/user permissions, artifact shape, preview build status, and local path safety.

## Storage and Persistence

### `backend/storage`

Storage is implemented through mixins collected by the store.

| File | Responsibility |
| --- | --- |
| `store.py` | Main store class composition. |
| `drivers.py` | Database connection plumbing. |
| `bootstrap.py` | Schema/table bootstrap. |
| `projects.py` | Users, projects, project files, local path, replace/apply generated files. |
| `chat.py` | Project chat message persistence and recent chat retrieval. |
| `memory.py` | Project/user memory records. |
| `agent_runtime.py` | Agent runs, runtime output, tool calls, messages. |
| `versions_events.py` | Preview versions and event log records. |
| `permissions.py` | Project read/write checks. |
| `roles.py` | Role constants. |
| `serialization.py` | Row-to-dict serialization. |
| `ids.py` | ID generation. |
| `user.py` | User context model. |
| `errors.py` | Storage exceptions. |

Persistence sequence after a successful generation/update:

1. Agent runtime writes candidate files through `WRITE_PROJECT_FILES`, or the pipeline applies generated files when the runtime did not already write them.
2. Local sync runs if the project has a linked local path and write-back is allowed.
3. `create_generation_run()` stores the generation response.
4. `persist_agent_runtime_output()` stores runtime messages/tool calls/memory.
5. `complete_agent_run()` marks the agent run complete.
6. The model chat message is recorded with response summary and run metadata.

## Local Workspace and Browser Folder Behavior

### `backend/local_workspace`

This package contains path safety, file normalization, read/write, ignored-file rules, binary asset handling, and import validation.

Important rules:

- Local paths must resolve inside configured allowed roots.
- Ignored folders include `.git`, `.runtime`, `.venv`, `__pycache__`, `dist`, and `node_modules`.
- Large files and unsupported paths are rejected.
- Binary public assets are encoded/decoded safely.
- Complete imports must include root files such as `index.html` and `package.json` and source files under `src/`.

### `backend/api/local_workspaces.py`

Provides route helper behavior for:

- Listing local directories inside allowed roots.
- Creating local folders.
- Resolving project local roots.
- Writing linked project files to local disk.

### Frontend browser folder mode

When the user chooses a folder in the browser:

- The browser can upload/import files into the backend project store.
- If a writable `FileSystemDirectoryHandle` is still available, the frontend can write generated/saved files back to the selected folder.
- If the handle is unavailable, the backend project store still remains the source of truth, and the UI shows that the browser folder is not currently writable.

No static user path should be hard-coded in backend code or env for general users. The selected project/local workspace metadata must drive where files are read and written.

## Preview Runtime

### `backend/runtime.py`

Builds Vite previews for committed or staged files.

Committed backend-store preview:

1. Load project and files from store.
2. Prepare `.runtime/projects/{project_id}/pending`.
3. Write project files.
4. Run Vite build.
5. Create a version.
6. Move pending workspace to `.runtime/projects/{project_id}/{version_id}`.
7. Serve assets through `/api/previews/...`.

Staged preview:

1. Receive candidate files from runtime action.
2. Normalize preview files.
3. Build in a pending runtime workspace or linked local `.worktual-staging`.
4. Create a preview version with status/build log.
5. Publish built `dist` only if ready.
6. Do not commit generated files yet.

Linked local preview:

- Builds inside the linked local folder or a temporary `.worktual-staging` folder.
- Publishes `dist` to backend runtime preview storage when ready.
- Removes staging after the attempt.

### `backend/api/previews.py`

Rewrites absolute Vite asset references in preview HTML so built assets resolve under the API preview URL.

## Validation and Commit Gate

For website generation/update, files are not supposed to be committed until all required checks pass:

```text
candidate files exist
  -> artifact contract valid
  -> staged preview status ready
  -> preview visual QA passed or intentionally skipped by safe fast path
  -> WRITE_PROJECT_FILES completed
  -> PERSIST_PROJECT_MEMORY completed
  -> DONE allowed
```

`backend/agents/agent_runtime/actions/project_io.py` is the main gatekeeper for preview and commit:

- Ensures Vite scaffold files when missing.
- Ensures Tailwind runtime files when Tailwind utilities are used.
- Normalizes React imports.
- Normalizes unsupported frontend runtime imports to platform shims.
- Builds staged preview.
- Classifies preview build failures.
- Persists build errors to memory.
- Runs static fast QA for small targeted fixes when safe.
- Runs browser visual QA for larger/visual changes.
- Writes files only through `WRITE_PROJECT_FILES`.

## Debugging Checkpoints

### 1. User prompt never starts

Check:

- `src/main.jsx` prompt button disabled conditions: active project, `isGenerating`, non-empty prompt.
- Browser network call to `/api/projects/{id}/generate-stream`.
- `backend/main.py` empty prompt handling.
- Backend server and `API_BASE_URL`.

### 2. Stream starts but UI looks stuck

Check:

- `generation_stream_events()` heartbeat events.
- Last live progress step in UI.
- Latest runtime progress event in `/api/events`.
- Last runtime step in failure detail if it fails.

Likely blocking areas:

- Gemini routing/model call.
- Scoped update model patch call.
- Staged preview build.
- Browser visual QA.

### 3. Greeting should summarize current project

Check:

- `backend/api/generation.py:is_greeting_only_prompt()`.
- `current_project_summary()`.
- `deterministic_greeting_generation()`.
- Confirm no Gemini construction and no file writes for greeting-only prompts.

Expected behavior:

- Response includes project name, workspace label, file count/key files, and storage summary.
- Agent/generation/chat records are persisted.

### 4. Scoped update timeout or safety block

Check:

- `backend/agents/agent_runtime/update_analysis/__init__.py` candidate files and update mode.
- `backend/agents/agent_runtime/scoped_update/runtime.py` deadline, candidate path prioritization, deterministic fallbacks, model timeout.
- `SCOPED_UPDATE_SEQUENCE_TIMEOUT_SECONDS`.
- Whether user prompt is too broad or does not name a concrete component/behavior.
- Whether the model returned empty JSON, unapproved paths, or a full-file rewrite.

### 5. Generated files fail staged Vite preview

Check:

- `backend/runtime.py` build log in preview version.
- `backend/agents/agent_runtime/actions/project_io.py:preview_build_failure_reason`.
- Missing Vite scaffold, unsafe React import, unresolved runtime import, Tailwind config, or missing dependency.
- Whether repair budget ran out before `RUN_REPAIR_AGENT`.

### 6. Unresolved import such as `react-router-dom`

Check:

- `normalize_frontend_runtime_imports()`.
- Runtime import shim path list in scaffolding.
- `package.json` dependency generated by artifact model.
- Whether preview build failed before deterministic normalization could retry.

### 7. Preview builds but app crashes

Check:

- Preview browser console/runtime QA result.
- `RUN_PREVIEW_VISUAL_QA`.
- Data-shape assumptions such as reading `.name` from `undefined`.
- Whether the error should route as `project_info` for explanation or `website_update` for fix.

### 8. Code generated but not written locally

Check:

- Did staged preview and QA pass?
- Did `WRITE_PROJECT_FILES` run?
- Does project have `local_path`?
- For browser-selected folders, does the frontend still have writable directory handle permission?
- `local_sync_error` in complete payload.
- `backend/api/local_workspaces.py:write_linked_project_files()`.
- Frontend `syncGeneratedFilesToBrowserWorkspace()`.

## Folder-Wise File Map

### Frontend

| File | Usage |
| --- | --- |
| `src/main.jsx` | Active app, workspace UI, chat/prompt, streaming, project/file/local/preview APIs, Monaco editor, browser folder import/write-back. |
| `src/styles.css` | Active stylesheet imported by `src/main.jsx`. |
| `src/App.jsx` | Null stub, not the active platform entrypoint. |
| `src/index.css` | Project stylesheet if used by build setup, but active app imports `styles.css`. |
| `src/data/roadmap.js` | Static frontend data when referenced by UI. |

### API layer

| File | Usage |
| --- | --- |
| `backend/main.py` | FastAPI app, route declarations, dependency wiring, project/file/local/generation/preview/event endpoints. |
| `backend/api/context.py` | App context type/dependency shape. |
| `backend/api/models.py` | Request/response models including generation/local import payloads. |
| `backend/api/generation.py` | Main generation pipeline, greeting fast path, provider setup, persistence. |
| `backend/api/generation_stream.py` | NDJSON streaming worker and heartbeat/error normalization. |
| `backend/api/failures.py` | Converts raw exceptions into user-facing generation failure categories/messages. |
| `backend/api/progress.py` | Progress event helpers and audit/runtime progress logging. |
| `backend/api/local_workspaces.py` | Local directory listing/creation and linked folder write helpers. |
| `backend/api/previews.py` | Preview HTML asset rewriting. |
| `backend/api/errors.py` | Storage/runtime exception to HTTP error helpers. |
| `backend/api/constants.py` | API constants such as host/port, favicon, preview headers, stream heartbeat. |

### LLM orchestration

| File/folder | Usage |
| --- | --- |
| `backend/agents/generator` | Public generation service exports. |
| `backend/agents/orchestration/runner.py` | Main orchestrator, routing, confirmation, conversation response, real runtime handoff. |
| `backend/agents/orchestration/routing.py` | Calls and normalizes route-generation model output. |
| `backend/agents/orchestration/conversation.py` | Conversation-only response generation and response package. |
| `backend/agents/orchestration/state.py` | Pipeline state object. |
| `backend/agents/orchestration/artifact_response.py` | Website artifact response normalization/package helpers. |
| `backend/agents/orchestration/runtime_metadata.py` | Response metadata, stage summaries, backend routing metadata. |
| `backend/agents/orchestration/tool_registry.py` | Tool registry metadata exposed in response. |
| `backend/agents/orchestration/constants.py` | Stage order, default agents, default tool registry. |

### Runtime loop

| File/folder | Usage |
| --- | --- |
| `backend/agents/agent_runtime_loop.py` | Guarded supervisor/action loop. |
| `backend/agents/agent_runtime/state.py` | Runtime state creation and step/message helpers. |
| `backend/agents/agent_runtime/actions/dispatcher.py` | Action-to-handler mapping. |
| `backend/agents/agent_runtime/actions/project_io.py` | Read files, validate, staged preview, visual QA, write files, persist memory. |
| `backend/agents/agent_runtime/actions/analysis.py` | Prompt/update/error/planner/review action handlers. |
| `backend/agents/agent_runtime/actions/generation.py` | Code, repair, and scoped update action handlers. |
| `backend/agents/agent_runtime/actions/dynamic.py` | Dynamic agent planner/specialist/integrator actions. |
| `backend/agents/agent_runtime/model_agents.py` | Runtime model calls for analyst/planner/review/code/repair. |
| `backend/agents/agent_runtime/supervision` | Legal actions, supervisor policy, completion proof, guardrails. |
| `backend/agents/agent_runtime/progress` | Progress labels, completion status, timeout enforcement, diff events. |
| `backend/agents/agent_runtime/scoped_update` | Scoped update analysis, prompt rendering, response normalization, validation, deterministic fallbacks. |
| `backend/agents/agent_runtime/update_analysis` | Existing-project update mode and file candidate selection. |
| `backend/agents/agent_runtime/scaffolding.py` | Vite/Tailwind/import shim normalization. |
| `backend/agents/agent_runtime/tooling.py` | Tool execution helpers and restore behavior. |
| `backend/agents/agent_runtime/memory.py` | Memory load/persist helpers. |
| `backend/agents/agent_runtime/runtime_summary.py` | Runtime summary for final response. |

### Prompting and provider

| File/folder | Usage |
| --- | --- |
| `backend/agents/prompts.py` | Prompt facade re-exporting builders/contracts/instructions. |
| `backend/agents/prompting/builders.py` | Routing, conversation, update analysis, scoped patch, dynamic workflow, domain research, artifact prompts. |
| `backend/agents/prompting/instructions.py` | Global, blueprint, routing, and conversation system instructions. |
| `backend/agents/prompting/contracts.py` | JSON contracts expected from model outputs. |
| `backend/agents/providers/gemini.py` | Gemini provider wrapper and role bridge. |
| `backend/agents/gemini_client/client.py` | Payload construction, env loading, model call logging, response parsing. |
| `backend/agents/gemini_client/transport.py` | Low-level HTTP transport to Gemini API. |
| `backend/agents/gemini_tool_calling` | Native Gemini tool-calling compatibility loop. |

### Tools, storage, preview, QA

| File/folder | Usage |
| --- | --- |
| `backend/agent_tools.py` | Tool facade for runtime imports. |
| `backend/agentic/tools/registry.py` | Tool definitions/schemas and dispatcher. |
| `backend/agentic/tools/handlers.py` | Tool implementations for file IO, memory, preview, QA, local sync. |
| `backend/storage` | Postgres-backed projects/files/chat/versions/events/memory/agent runtime persistence. |
| `backend/local_workspace` | Local path safety, import validation, file read/write, ignored paths, binary asset support. |
| `backend/runtime.py` | Vite preview build, staged preview, runtime asset storage/serving. |
| `backend/visual_qa` | Browser preview QA and visual/runtime checks. |
| `backend/audit_logging` | Query/model/tool/runtime audit events. |
| `backend/code_diff` | Candidate/generated file diff summaries for UI/audit. |

## Public Contracts To Preserve

- `POST /api/projects/{project_id}/generate-stream` accepts `{ "prompt": string, "model"?: string }`.
- Empty prompts return `400`.
- The stream media type is `application/x-ndjson`.
- UI-visible stream types are `progress`, `complete`, and `error`.
- Complete payload includes generation metadata and current project files.
- Greeting-only prompts return a deterministic conversation/project summary and skip Gemini/file writes.
- Update/generation prompts must pass validation, staged preview, QA, write, and memory persistence before DONE.
- Confirmation-required work must pause until explicit confirm/revise/cancel/new-request handling.
- Backend and env must not contain user-specific static write paths for general users; use project/local workspace metadata.

## Regression Commands

Run these after code changes in this flow:

```bash
pytest -q
python -m pytest -q
npm run build -- --outDir /private/tmp/worktual-ai-dev-build-check
```

Focused regression areas:

- Provider split and Gemini model construction.
- Greeting fast path and current project summary.
- Static favicon route compatibility.
- Stream payload normalization.
- Confirmation pause/resume.
- Scoped update timeout/error handling.
- Staged Vite preview repair.
- Unsupported runtime import normalization.
- Local workspace/browser-folder write-back.
