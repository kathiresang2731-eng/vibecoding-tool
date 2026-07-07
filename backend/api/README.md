# Backend API Modules

`backend/main.py` owns the HTTP route declarations. This package holds the shared implementation behind those routes.

## Current structure

- `context.py` and `context_parts/`: app creation, current-user dependency, and request context bootstrap.
- `models.py`: request and payload schemas.
- `auth.py`, `admin_users.py`: authentication and admin user actions.
- `chat.py` and `chat_parts/`: project chat sessions, message serialization, and continuity state.
- `generation.py` and `generation_parts/`: generation pipeline routing, preflight/postflight, failure handling, and compatibility helpers.
- `generation_stream.py` and `generation_stream_parts/`: streaming generation wrapper, telemetry, worker thread, and NDJSON event loop.
- `failures.py` and `failures_parts/`: error classification, scoped-update guards, runtime parsing, and model validation.
- `previews.py` and `previews_parts/`: preview path rewriting, HTML injection, and browser navigation guards.
- `local_workspaces.py` and `local_workspaces_parts/`: linked folder discovery, validation, and sync helpers.
- `progress.py` and `progress_parts/`: progress event formatting and logging.
- `skills.py` and `skills_parts/`: skill discovery, bootstrap, creation, and project import.
- `memory_*`: memory episodes, learning, and preferences APIs.
- `project_download.py`: project archive creation and safe download naming.
- `run_locks.py`: project-level generation lock/cancellation state.
- `usage_enforcement.py`: generation quota checks.
- `v1/` and `v1/*_parts/`: versioned compatibility and event-schema helpers.

## End-to-end flow

1. `backend/main.py` receives the request.
2. It resolves context and user dependencies from `context.py`.
3. It validates the request model from `models.py`.
4. It calls a feature module such as `generation.py`, `chat.py`, `skills.py`, or `previews.py`.
5. That module delegates to its `*_parts/` submodules for the actual implementation.
6. Failures are normalized in `failures.py`, and progress/streaming responses go through `progress.py` and `generation_stream.py`.

## Safe update rule

When changing API behavior, prefer:

- thin facade modules at the top level
- small `*_parts/` modules underneath
- backward-compatible exports in `backend/api/__init__.py`
- compile verification after every structural change
