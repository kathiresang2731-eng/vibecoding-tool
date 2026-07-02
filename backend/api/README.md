# Backend API Modules

`backend/main.py` owns FastAPI route declarations. Shared implementation is split here so routing, generation, previews, and local workspace behavior are easier to update safely.

- `context.py`: app creation, settings/store context, and current-user dependency.
- `models.py`: request body models.
- `generation.py`: generation pipeline execution.
- `failures.py`: structured generation error classification.
- `progress.py`: progress/NDJSON event helpers.
- `local_workspaces.py`: local folder listing/linking helpers.
- `previews.py`: preview HTML rewrite helpers.
- `errors.py`: HTTP error mapping.
- `constants.py`: API constants.
