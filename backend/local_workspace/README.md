# Local Workspace

Helpers for linking generated website projects to a real local folder.

- `paths.py` resolves and validates local/project-relative paths.
- `io.py` imports local files, writes project files, and prunes stale files during full syncs.
- `content.py` handles text and data URL encoded binary assets.
- `validation.py` checks that imports look like a complete Vite/React project.
- `constants.py` stores file limits, required files, ignored names, and ignored directories.

Import public helpers from `backend.local_workspace`; the package preserves the previous module API.
