# Code Diff

Project-file diff helpers used by generation progress and audit logging.

- `normalization.py` converts API file payloads into a path-to-code map.
- `builder.py` builds bounded unified diffs with line counts and hashes.
- `redaction.py` strips diff bodies before audit persistence.
- `hashing.py` owns stable text hashing.
- `constants.py` stores diff limits.

Import public helpers from `backend.code_diff`; the package keeps the previous module API stable.
