# Orchestration Graph

This package records the backend orchestration graph trace that wraps each
generation run.

- `constants.py` defines the stable node-to-stage map.
- `trace.py` builds graph traces, edges, and node trace payloads.
- `executor.py` runs stages in graph order and records progress/failures.
- `time.py` contains timestamp helpers.

Import from `backend.agents.orchestration_graph` to keep callers independent of
the internal file layout.
