from __future__ import annotations

import re

from .constants import ALLOWED_EXACT_PATHS, ALLOWED_PREFIXES, ROOT_DOCUMENT_EXTENSIONS, ROOT_STANDALONE_CODE_EXTENSIONS
from .errors import ArtifactValidationError

ROOT_STANDALONE_CODE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SRC_RELATIVE_PREFIXES = (
  "pages/",
  "components/",
  "hooks/",
  "lib/",
  "utils/",
  "styles/",
  "assets/",
  "constants/",
  "services/",
  "context/",
  "types/",
  "data/",
  "routes/",
  "views/",
  "layouts/",
  "features/",
  "store/",
)
PROJECT_ROOT_PREFIXES = {"src", "public", "backend", "api", "app", "server", "database", "db", "migrations", "alembic", "scripts", "tests"}
IGNORED_PROJECT_PREFIXES = {
  ".git",
  ".runtime",
  ".worktual-staging",
  ".venv",
  "__pycache__",
  "dist",
  "node_modules",
}
WORKTUAL_SKILL_PREFIX = ".worktual/skills/"


def is_allowed_worktual_meta_path(path: str) -> bool:
  if path in {".worktual/AGENTS.md", "AGENTS.md", f"{WORKTUAL_SKILL_PREFIX}skills.md"}:
    return True
  if not path.startswith(WORKTUAL_SKILL_PREFIX):
    return False
  parts = [part for part in path.split("/") if part]
  # .worktual/skills/<name>/SKILL.md
  return len(parts) == 4 and parts[0] == ".worktual" and parts[1] == "skills" and parts[-1] == "SKILL.md"


def strip_accidental_project_folder(path: str) -> str:
  parts = [part for part in path.split("/") if part]
  if len(parts) < 2:
    return path
  first = parts[0]
  if first in {".", ".."}:
    return path
  if first in IGNORED_PROJECT_PREFIXES or (first.startswith(".") and first != ".worktual"):
    return path
  if first in PROJECT_ROOT_PREFIXES or first in ALLOWED_EXACT_PATHS:
    return path
  second = parts[1]
  if second in PROJECT_ROOT_PREFIXES or second in ALLOWED_EXACT_PATHS:
    return "/".join(parts[1:])
  return path


def collapse_repeated_path_segments(path: str) -> str:
  cleaned = path.replace("\\", "/").strip().strip("/")
  if not cleaned:
    return cleaned
  parts = cleaned.split("/")
  for span in range(len(parts) // 2, 0, -1):
    index = 0
    while index + 2 * span <= len(parts):
      if parts[index : index + span] == parts[index + span : index + 2 * span]:
        del parts[index + span : index + 2 * span]
        continue
      index += 1
  return "/".join(parts)


def normalize_artifact_path(path: str) -> str:
  cleaned = path.replace("\\", "/").strip()
  while cleaned.startswith("./"):
    cleaned = cleaned[2:]
  if cleaned.startswith("/") or ".." in cleaned.split("/"):
    raise ArtifactValidationError(f"Generated file path is not allowed: {path}")
  cleaned = strip_accidental_project_folder(cleaned)
  cleaned = collapse_repeated_path_segments(cleaned)
  for prefix in SRC_RELATIVE_PREFIXES:
    if cleaned.startswith(prefix):
      cleaned = f"src/{cleaned}"
      break
  if not cleaned:
    raise ArtifactValidationError("Generated file path cannot be empty.")
  if cleaned.startswith("/") or ".." in cleaned.split("/"):
    raise ArtifactValidationError(f"Generated file path is not allowed: {path}")
  if cleaned.startswith(ALLOWED_PREFIXES) or cleaned in ALLOWED_EXACT_PATHS:
    return cleaned
  if is_allowed_worktual_meta_path(cleaned):
    return cleaned
  if "/" not in cleaned and cleaned.endswith(ROOT_STANDALONE_CODE_EXTENSIONS + ROOT_DOCUMENT_EXTENSIONS) and ROOT_STANDALONE_CODE_FILENAME_RE.match(cleaned):
    return cleaned
  raise ArtifactValidationError(f"Generated file path is outside the allowed project surface: {path}")
