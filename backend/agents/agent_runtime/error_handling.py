from __future__ import annotations

import re
from typing import Any

from .file_ops import unique_paths
from .values import list_value, text_or_default


PATH_RE = re.compile(
  r"(?P<path>(?:src|backend|api|app|server|database|db|migrations|alembic|scripts|tests)/[A-Za-z0-9_./@-]+\.[A-Za-z0-9]+|"
  r"[A-Za-z0-9_.-]+\.(?:jsx|tsx|js|ts|css|py|sql|json|toml|ya?ml|java|go|php|rb|cs))"
)

API_ROUTE_RE = re.compile(r"(?P<route>/api/[A-Za-z0-9_./{}:-]+)")


def analyze_error_context(
  prompt: str,
  *,
  existing_files: list[dict[str, Any]],
  code_search_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
  text = prompt or ""
  lowered = text.lower()
  languages = infer_error_languages(text)
  categories = infer_error_categories(lowered)
  mentioned_paths = infer_mentioned_paths(text)
  api_routes = unique_paths(match.group("route") for match in API_ROUTE_RE.finditer(text))
  candidate_files = infer_error_candidate_files(
    existing_files=existing_files,
    mentioned_paths=mentioned_paths,
    api_routes=api_routes,
    languages=languages,
    code_search_matches=code_search_matches or [],
  )
  return {
    "agent": "Universal Error Handling Agent",
    "strategy": "single_orchestrating_agent_with_language_specific_diagnostics",
    "languages": languages,
    "categories": categories,
    "api_routes": api_routes[:12],
    "mentioned_paths": mentioned_paths[:12],
    "candidate_files": candidate_files[:4],
    "root_cause_hints": root_cause_hints(lowered, api_routes=api_routes),
    "repair_rules": [
      "Use the provided error text as the primary reproduction signal.",
      "Patch the smallest root cause instead of redesigning unrelated code.",
      "If an API route is missing, update the backend route or frontend endpoint contract consistently.",
      "If a value is not an array/object as expected, add defensive normalization at the data boundary and fix the producer when available.",
      "Validate imports, routes, schemas, and runtime contracts for the detected language stack.",
    ],
  }


def infer_error_languages(text: str) -> list[str]:
  lowered = text.lower()
  languages: list[str] = []
  markers = [
    ("javascript", ("react", ".jsx", ".tsx", ".js", "typeerror", "referenceerror", "uncaught", "react-dom")),
    ("python", ("traceback", ".py", "fastapi", "pydantic", "sqlalchemy", "uvicorn")),
    ("sql", ("sqlstate", ".sql", "postgres", "postgresql", "psycopg", "sqlite", "mysql", "migration")),
    ("java", (".java", "spring", "maven", "gradle")),
    ("go", (".go", "gin.", "fiber", "panic:")),
    ("php", (".php", "laravel", "symfony")),
    ("ruby", (".rb", "rails", "bundler")),
    ("csharp", (".cs", ".net", "asp.net", "entity framework")),
  ]
  for language, tokens in markers:
    if any(token in lowered for token in tokens):
      languages.append(language)
  return languages or ["unknown"]


def infer_error_categories(lowered: str) -> list[str]:
  categories: list[str] = []
  checks = [
    ("missing_api_route", ("failed to load resource", "404", "/api/")),
    (
      "data_shape_mismatch",
      ("map is not a function", "not iterable", "undefined is not a function", "cannot read properties", "undefined (reading"),
    ),
    ("runtime_exception", ("uncaught", "typeerror", "referenceerror", "traceback", "exception")),
    ("compile_or_import_error", ("module not found", "cannot find module", "import", "syntaxerror", "compile error")),
    ("database_error", ("sqlstate", "postgres", "psycopg", "sqlite", "mysql", "migration")),
  ]
  for category, tokens in checks:
    if any(token in lowered for token in tokens):
      categories.append(category)
  return categories or ["runtime_error"]


def infer_mentioned_paths(text: str) -> list[str]:
  paths = []
  for match in PATH_RE.finditer(text or ""):
    path = match.group("path").strip("`'\"")
    if path and path not in paths:
      paths.append(path)
  return paths


def infer_error_candidate_files(
  *,
  existing_files: list[dict[str, Any]],
  mentioned_paths: list[str],
  api_routes: list[str],
  languages: list[str],
  code_search_matches: list[dict[str, Any]],
) -> list[str]:
  existing_paths = [
    text_or_default(item.get("path"), "")
    for item in existing_files
    if isinstance(item, dict) and text_or_default(item.get("path"), "")
  ]
  existing_path_set = set(existing_paths)
  candidates: list[str] = [path for path in mentioned_paths if path in existing_path_set]
  candidates.extend(
    text_or_default(item.get("path"), "")
    for item in code_search_matches
    if isinstance(item, dict) and text_or_default(item.get("path"), "") in existing_path_set
  )
  if api_routes:
    candidates.extend(path for path in existing_paths if path.startswith(("backend/", "api/", "app/", "server/")))
    candidates.extend(path for path in existing_paths if path.startswith("src/") and path.endswith((".js", ".jsx", ".ts", ".tsx")))
  if "javascript" in languages:
    candidates.extend(path for path in existing_paths if path.startswith("src/") and path.endswith((".js", ".jsx", ".ts", ".tsx")))
  if "python" in languages:
    candidates.extend(path for path in existing_paths if path.endswith(".py"))
  if "sql" in languages:
    candidates.extend(path for path in existing_paths if path.endswith(".sql") or path.startswith(("database/", "db/", "migrations/", "alembic/")))
  return unique_paths(path for path in candidates if path)


def root_cause_hints(lowered: str, *, api_routes: list[str]) -> list[str]:
  hints: list[str] = []
  if api_routes and ("404" in lowered or "failed to load resource" in lowered):
    hints.append("Frontend is calling API route(s) that the active backend does not expose.")
  if "map is not a function" in lowered:
    hints.append("A render path expects an array but received an object, null, error payload, or failed fetch response.")
  if "cannot read properties" in lowered and ("reading 'name'" in lowered or 'reading "name"' in lowered):
    hints.append("A render path is reading .name from an undefined or null object; add a safe fallback at the data boundary or caller.")
  if "unsupported react renderer" in lowered or "locator" in lowered:
    hints.append("locator-js messages are development-tool noise unless the app runtime also crashes.")
  if not hints:
    hints.append("Use the error stack and current project files to locate the smallest producer/consumer contract mismatch.")
  return hints
