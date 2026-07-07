from __future__ import annotations

from pathlib import Path

try:
  from ..config import Settings
except ImportError:
  from config import Settings

from .constants import ALLOWED_DOT_DIRECTORIES, IGNORED_DIRECTORIES, IGNORED_FILE_NAMES
from .errors import LocalWorkspaceError


PROJECT_ROOT_PREFIXES = {
  "src",
  "public",
  "backend",
  "api",
  "app",
  "server",
  "database",
  "db",
  "migrations",
  "alembic",
  "scripts",
  "tests",
}
PROJECT_ROOT_FILES = {
  "index.html",
  "app.js",
  "index.js",
  "main.js",
  "script.js",
  "main.css",
  "style.css",
  "styles.css",
  "package.json",
  "package-lock.json",
  "requirements.txt",
  "pyproject.toml",
  "poetry.lock",
  "Pipfile",
  "Pipfile.lock",
  "Dockerfile",
  "docker-compose.yml",
  "docker-compose.yaml",
  ".env.example",
  "vite.config.js",
  "vite.config.mjs",
  "vite.config.cjs",
  "vite.config.ts",
  "tailwind.config.js",
  "tailwind.config.mjs",
  "tailwind.config.cjs",
  "tailwind.config.ts",
  "postcss.config.js",
  "postcss.config.mjs",
  "postcss.config.cjs",
  "eslint.config.js",
  "eslint.config.mjs",
  "eslint.config.cjs",
  "tsconfig.json",
  "tsconfig.app.json",
  "tsconfig.node.json",
  "jsconfig.json",
  "components.json",
  "vercel.json",
  "todo.md",
  "WEBSITE.md",
}


def strip_accidental_project_folder(path: str) -> str:
  parts = [part for part in path.split("/") if part]
  if len(parts) < 2:
    return path
  first = parts[0]
  if first in {".", ".."}:
    return path
  if first in IGNORED_DIRECTORIES or (first.startswith(".") and first not in ALLOWED_DOT_DIRECTORIES):
    return path
  if first in PROJECT_ROOT_PREFIXES or first in PROJECT_ROOT_FILES:
    return path
  second = parts[1]
  if second in PROJECT_ROOT_PREFIXES or second in PROJECT_ROOT_FILES:
    return "/".join(parts[1:])
  return path


def resolve_local_project_path(settings: Settings, raw_path: str) -> Path:
  if not isinstance(raw_path, str) or not raw_path.strip():
    raise LocalWorkspaceError("Local path is required.")

  candidate = Path(raw_path.strip()).expanduser()
  if not candidate.is_absolute():
    candidate = settings.app_root / candidate
  resolved = candidate.resolve(strict=False)

  if resolved == settings.app_root.resolve(strict=False):
    raise LocalWorkspaceError("The platform app folder cannot be used as a generated website output folder.")

  if not any(path_is_inside(resolved, root) for root in settings.local_workspace_roots):
    allowed = ", ".join(str(root) for root in settings.local_workspace_roots)
    raise LocalWorkspaceError(f"Local path is outside the allowed workspace roots: {allowed}")

  return resolved


def safe_project_file(root: Path, relative_path: str) -> Path:
  destination = (root / relative_path).resolve(strict=False)
  if not path_is_inside(destination, root):
    raise LocalWorkspaceError(f"Unsafe local file path: {relative_path}")
  return destination


def normalize_project_file_path(path: str) -> str:
  cleaned = str(path).replace("\\", "/").strip()
  while cleaned.startswith("./"):
    cleaned = cleaned[2:]
  if cleaned.startswith("/") or ".." in cleaned.split("/"):
    raise LocalWorkspaceError(f"Project file path is not allowed: {path}")
  cleaned = strip_accidental_project_folder(cleaned)
  if not cleaned:
    raise LocalWorkspaceError("Project file path cannot be empty.")
  if cleaned.startswith("/") or ".." in cleaned.split("/"):
    raise LocalWorkspaceError(f"Project file path is not allowed: {path}")
  parts = [part for part in cleaned.split("/") if part]
  if not parts:
    raise LocalWorkspaceError("Project file path cannot be empty.")
  if any(
    part in IGNORED_DIRECTORIES or (part.startswith(".") and part not in ALLOWED_DOT_DIRECTORIES)
    for part in parts[:-1]
  ):
    raise LocalWorkspaceError(f"Project file path is inside an ignored folder: {path}")
  if parts[-1] in IGNORED_FILE_NAMES:
    raise LocalWorkspaceError(f"Project file is ignored: {path}")
  return "/".join(parts)


def path_is_inside(path: Path, root: Path) -> bool:
  resolved_root = root.resolve(strict=False)
  return path == resolved_root or resolved_root in path.parents


def should_ignore(path: Path, root: Path) -> bool:
  relative_parts = path.relative_to(root).parts
  return any(
    part in IGNORED_DIRECTORIES or (part.startswith(".") and part not in ALLOWED_DOT_DIRECTORIES)
    for part in relative_parts
  )
