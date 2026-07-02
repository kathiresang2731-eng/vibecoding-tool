from __future__ import annotations

from typing import Any

from .values import list_value, object_value, text_or_default


FRONTEND_RUNTIME_PREFIXES = ("src/", "public/")
FRONTEND_RUNTIME_ROOTS = {
  "index.html",
  "package.json",
  "vite.config.js",
  "vite.config.mjs",
  "vite.config.ts",
  "tailwind.config.js",
  "postcss.config.js",
}
BACKEND_RUNTIME_PREFIXES = (
  "backend/",
  "api/",
  "app/",
  "server/",
  "database/",
  "db/",
  "migrations/",
  "alembic/",
  "scripts/",
  "tests/",
)
BACKEND_RUNTIME_ROOTS = {
  "requirements.txt",
  "pyproject.toml",
  "poetry.lock",
  "Pipfile",
  "Pipfile.lock",
  "Dockerfile",
  "docker-compose.yml",
  "docker-compose.yaml",
  ".env.example",
}
def candidate_changed_paths(state: dict[str, Any]) -> list[str]:
  changed = list_value(state.get("changed_file_paths"))
  if changed:
    return [str(path) for path in changed if str(path).strip()]
  return [
    text_or_default(item.get("path"), "")
    for item in list_value(state.get("candidate_files"))
    if isinstance(item, dict) and text_or_default(item.get("path"), "")
  ]


def is_frontend_runtime_path(path: str) -> bool:
  return path in FRONTEND_RUNTIME_ROOTS or path.startswith(FRONTEND_RUNTIME_PREFIXES)


def is_backend_runtime_path(path: str) -> bool:
  return path in BACKEND_RUNTIME_ROOTS or path.startswith(BACKEND_RUNTIME_PREFIXES)


def should_skip_preview_for_backend_only_change(state: dict[str, Any]) -> bool:
  if object_value(state.get("validation_result")).get("status") != "valid":
    return False
  paths = candidate_changed_paths(state)
  if not paths:
    return False
  return all(is_backend_runtime_path(path) and not is_frontend_runtime_path(path) for path in paths)


def backend_only_preview_skip_result(state: dict[str, Any]) -> dict[str, Any]:
  paths = candidate_changed_paths(state)
  return {
    "project_id": text_or_default(state.get("project_id"), ""),
    "version": {
      "status": "ready",
      "preview_url": "",
      "mode": "backend_only_static_validation",
      "skipped_preview_build": True,
      "reason": "Only backend/database/config/test files changed, so Vite preview build was skipped.",
    },
    "staged": True,
    "skipped": True,
    "paths": paths,
  }


def backend_only_visual_qa_skip_result(state: dict[str, Any]) -> dict[str, Any]:
  return {
    "status": "passed",
    "mode": "backend_only_static_validation",
    "browser_rendered": False,
    "checks": [
      {
        "name": "backend_only_scope",
        "status": "passed",
        "detail": "No frontend runtime files changed; browser visual QA is not applicable.",
      }
    ],
    "warnings": [],
  }
