"""Detect greenfield vs existing codebases for generation context."""

from __future__ import annotations

import json
from typing import Any

_MEANINGFUL_PREFIXES = (
  "src/",
  "index.html",
  "package.json",
  "vite.config",
  "public/",
  "app/",
  "pages/",
  "components/",
)

_STANDALONE_CODE_EXTENSIONS = (
  ".py",
  ".java",
  ".js",
  ".ts",
  ".go",
  ".rs",
  ".c",
  ".cc",
  ".cpp",
  ".cs",
  ".kt",
  ".swift",
  ".rb",
  ".php",
  ".pl",
  ".scala",
  ".sh",
  ".ps1",
  ".sql",
)

_FRONTEND_RUNTIME_PATHS = {
  "index.html",
  "vite.config.js",
  "vite.config.ts",
  "tailwind.config.js",
  "postcss.config.js",
  "src/main.jsx",
  "src/main.tsx",
  "src/App.jsx",
  "src/App.tsx",
  "src/index.css",
}

_FRONTEND_RUNTIME_PREFIXES = (
  "public/",
  "src/components/",
  "src/pages/",
  "src/routes/",
)

_FRONTEND_PACKAGE_MARKERS = (
  '"@vitejs/',
  '"vite"',
  '"react"',
  '"react-dom"',
  '"next"',
  '"vue"',
  '"svelte"',
  '"tailwindcss"',
)


def _normalized_project_path(path: str) -> str:
  return str(path or "").strip().replace("\\", "/")


def _is_hidden_project_path(path: str) -> bool:
  return any(segment.startswith(".") for segment in path.split("/") if segment)


def is_meaningful_project_source_path(path: str) -> bool:
  normalized = _normalized_project_path(path)
  if not normalized:
    return False
  if _is_hidden_project_path(normalized):
    return False
  return normalized.startswith(_MEANINGFUL_PREFIXES) or normalized in {"package.json", "index.html"}


def is_standalone_code_source_path(path: str) -> bool:
  normalized = _normalized_project_path(path)
  if not normalized or _is_hidden_project_path(normalized):
    return False
  lowered = normalized.lower()
  if lowered in {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "vite.config.js",
    "vite.config.ts",
    "tailwind.config.js",
    "postcss.config.js",
    "tsconfig.json",
  }:
    return False
  return lowered.endswith(_STANDALONE_CODE_EXTENSIONS)


def meaningful_project_source_files(files: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
  if not isinstance(files, list):
    return []
  return [
    item
    for item in files
    if isinstance(item, dict) and is_meaningful_project_source_path(str(item.get("path") or ""))
  ]


def standalone_code_source_files(files: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
  if not isinstance(files, list):
    return []
  return [
    item
    for item in files
    if isinstance(item, dict) and is_standalone_code_source_path(str(item.get("path") or ""))
  ]


def _files_content_map(files: list[dict[str, Any]] | None) -> dict[str, str]:
  if not isinstance(files, list):
    return {}
  merged: dict[str, str] = {}
  for item in files:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").strip()
    if not path:
      continue
    content = item.get("content")
    if content is None:
      content = item.get("code")
    merged[path] = content if isinstance(content, str) else ""
  return merged


def has_frontend_runtime_files(files: list[dict[str, Any]] | None) -> bool:
  files_map = _files_content_map(files)
  for path, content in files_map.items():
    normalized = _normalized_project_path(path)
    lowered = normalized.lower()
    if normalized in _FRONTEND_RUNTIME_PATHS or lowered in _FRONTEND_RUNTIME_PATHS:
      return True
    if any(lowered.startswith(prefix.lower()) for prefix in _FRONTEND_RUNTIME_PREFIXES):
      return True
    if lowered.endswith((".jsx", ".tsx", ".vue", ".svelte")):
      return True
    if lowered == "package.json" and any(marker in content.lower() for marker in _FRONTEND_PACKAGE_MARKERS):
      return True
  return False


def is_standalone_code_project(files: list[dict[str, Any]] | None) -> bool:
  """True for code/script/backend-only projects that must not receive a Vite shell."""
  return bool(standalone_code_source_files(files)) and not has_frontend_runtime_files(files)


def is_vite_scaffold_complete(files: list[dict[str, Any]] | None) -> bool:
  try:
    from .agent_runtime.scaffolding import is_default_app_shell_content, is_valid_scaffold_file_content
  except ImportError:
    from agents.agent_runtime.scaffolding import is_default_app_shell_content, is_valid_scaffold_file_content

  files_map = _files_content_map(files)
  required_paths = (
    "package.json",
    "index.html",
    "vite.config.js",
    "tailwind.config.js",
    "postcss.config.js",
    "src/main.jsx",
    "src/index.css",
    "src/App.jsx",
  )
  for path in required_paths:
    if not is_valid_scaffold_file_content(path, files_map.get(path, "")):
      return False
  package_json = files_map.get("package.json", "").strip()
  try:
    payload = json.loads(package_json)
  except json.JSONDecodeError:
    return False
  if not isinstance(payload, dict) or not payload.get("dependencies"):
    return False
  has_generated_pages = any(
    _normalized_project_path(path).startswith("src/pages/")
    and _normalized_project_path(path).endswith((".js", ".jsx", ".ts", ".tsx"))
    and str(content or "").strip()
    for path, content in files_map.items()
  )
  if has_generated_pages and is_default_app_shell_content(files_map.get("src/App.jsx", "")):
    return False
  return True


def is_greenfield_codebase(files: list[dict[str, Any]] | None) -> bool:
  if standalone_code_source_files(files):
    return False
  return len(meaningful_project_source_files(files)) == 0


def is_greenfield_generation(*, intent: str, files: list[dict[str, Any]] | None) -> bool:
  if intent not in {"website_generation", "simple_code"}:
    return False
  if is_standalone_code_project(files):
    return False
  if is_greenfield_codebase(files):
    return True
  return not is_vite_scaffold_complete(files)


def needs_vite_scaffold_repair(files: list[dict[str, Any]] | None) -> bool:
  if is_standalone_code_project(files):
    return False
  return not is_vite_scaffold_complete(files)


def is_scaffold_only_codebase(files: list[dict[str, Any]] | None) -> bool:
  """Vite scaffold exists but no real pages/components yet — treat as parallel greenfield generation."""
  if standalone_code_source_files(files):
    return False
  if is_greenfield_codebase(files):
    return True
  if not is_vite_scaffold_complete(files):
    return False
  files_map = _files_content_map(files)
  has_pages = any(path.startswith("src/pages/") for path in files_map)
  has_components = any(path.startswith("src/components/") for path in files_map)
  return not has_pages and not has_components
