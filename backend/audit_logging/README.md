# Audit Logging

This package owns structured audit events for model calls, backend tools, and
dynamic agents.

- `context.py` manages request/user/project telemetry context.
- `logger.py` writes daily JSONL audit streams.
- `sanitize.py` redacts secrets and summarizes prompt/code/file payloads.
- `registry.py` owns the process-wide logger instance and convenience functions.
- `constants.py` and `values.py` hold shared names and parsing helpers.

Import public helpers from `backend.audit_logging` so callers stay independent
of the internal file layout.
