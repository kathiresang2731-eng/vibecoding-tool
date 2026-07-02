# Artifact validation

This package validates and normalizes generated website artifacts before files are staged or written.

- `validation.py` owns top-level artifact, theme, section, and file validation.
- `paths.py` enforces the allowed project file surface.
- `react.py` normalizes generated React source imports when JSX or `React.*` is used.
- `fields.py` contains required/optional text coercion helpers.
- `constants.py` contains path, extension, and regex policy.
- `errors.py` defines `ArtifactValidationError`.

Import from `backend.agents.artifacts`; `__init__.py` keeps the previous public names stable.
