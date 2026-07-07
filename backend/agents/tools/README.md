# Agent Tools

Canonical import facade for tools used by runtime agents.

The lower-level implementations still live in `backend/agentic/tools` because
they are also used by persistence and compatibility layers. New agent runtime
code should import through `backend.agents.tools` so readers can find agent
behavior and agent tools together.

## Tool Groups

- Project context: `READ_PROJECT_FILES`
- Memory: `LOAD_PROJECT_MEMORY`, `PERSIST_PROJECT_MEMORY`
- Artifact guardrails: `VALIDATE_PROJECT_ARTIFACT`
- Preview guardrails: `BUILD_STAGED_PROJECT_PREVIEW`, `RUN_PREVIEW_VISUAL_QA`
- Commit: `WRITE_PROJECT_FILES`
