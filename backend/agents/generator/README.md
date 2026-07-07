# Generator Entry Points

This package exposes the public website-generation entry points used by the API
and tests.

- `service.py` creates and runs the Worktual generation orchestrator.
- `normalization.py` applies the response contract sanitizer.
- `error_handling.py` maps expected generation failures to HTTP-style payloads.

Import from `backend.agents.generator` rather than internal modules.
