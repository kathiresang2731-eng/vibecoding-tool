from __future__ import annotations

import re
from typing import Any

try:
  from ..chat_history import primary_update_prompt
except ImportError:
  from agents.chat_history import primary_update_prompt


PATH_RE = re.compile(
  r"\b((?:src|public|backend|api|components|pages|styles|data|utils|hooks|lib)/[A-Za-z0-9_./@() -]+\.(?:jsx|tsx|js|ts|css|json|html|md)|"
  r"(?:index\.html|package\.json|vite\.config\.[jt]s|tailwind\.config\.[jt]s|postcss\.config\.[jt]s))\b"
)

SUCCESS_PREVIEW_STATUSES = {"ready", "built", "passed", "skipped", "completed", "prepared", ""}


def _string_list(value: Any) -> list[str]:
  if not isinstance(value, list):
    return []
  items: list[str] = []
  for item in value:
    text = str(item or "").replace("\\", "/").strip()
    if text and text not in items:
      items.append(text)
  return items


def _object_value(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {}


def _required_new_files(scope: dict[str, Any], candidate_new_files: list[str]) -> list[str]:
  required = _string_list(scope.get("required_new_files"))
  requirements = _object_value(scope.get("new_file_requirements"))
  if requirements.get("needed") is True:
    for item in list(requirements.get("planned_files") or []):
      plan = _object_value(item)
      path = str(plan.get("path") or "").replace("\\", "/").strip()
      if path and path not in required:
        required.append(path)
  candidate_set = set(candidate_new_files)
  return [path for path in required if path in candidate_set]


def explicit_path_mentions(prompt: str) -> list[str]:
  text = primary_update_prompt(prompt)
  mentions: list[str] = []
  for match in PATH_RE.finditer(text):
    path = match.group(1).replace("\\", "/").strip().rstrip(".,;:)")
    if path and path not in mentions:
      mentions.append(path)
  return mentions


def validate_update_requirement(
  *,
  prompt: str,
  files_before_map: dict[str, str],
  files_after_map: dict[str, str],
  changed_paths: list[str],
  update_scope: dict[str, Any] | None = None,
  preview_status: str = "skipped",
) -> dict[str, Any]:
  """Backend-side sanity check that an update actually touched the requested scope.

  This is intentionally deterministic and conservative. It does not try to prove
  visual perfection; it prevents false success when an update produced no patch,
  ignored approved new files, or never reached a usable preview/build state.
  """

  scope = _object_value(update_scope)
  changed = _string_list(changed_paths)
  changed_set = set(changed)
  target_files = _string_list(scope.get("target_files"))
  candidate_files = _string_list(scope.get("candidate_files"))
  candidate_new_files = _string_list(scope.get("candidate_new_files"))
  required_new_files = _required_new_files(scope, candidate_new_files)
  mentioned_paths = explicit_path_mentions(prompt)
  issues: list[dict[str, Any]] = []

  if not changed:
    issues.append(
      {
        "code": "no_code_changes",
        "message": "The update did not save any file changes.",
      }
    )

  for path in required_new_files:
    if not str(files_after_map.get(path) or "").strip():
      issues.append(
        {
          "code": "missing_new_file",
          "path": path,
          "message": f"Required new file {path} was not created.",
        }
      )

  existing_targets = [path for path in target_files if path in files_before_map]
  if existing_targets and not (changed_set & set(existing_targets)):
    issues.append(
      {
        "code": "target_scope_not_changed",
        "target_files": existing_targets,
        "message": "None of the scoped target files were changed.",
      }
    )

  for path in mentioned_paths:
    if path in files_before_map and path not in changed_set and not candidate_new_files:
      issues.append(
        {
          "code": "mentioned_file_not_changed",
          "path": path,
          "message": f"The user-mentioned file {path} was not changed.",
        }
      )
    elif path not in files_before_map and path not in files_after_map:
      issues.append(
        {
          "code": "mentioned_file_missing",
          "path": path,
          "message": f"The user-mentioned file {path} does not exist after the update.",
        }
      )

  normalized_preview = str(preview_status or "").strip().lower()
  if normalized_preview not in SUCCESS_PREVIEW_STATUSES:
    issues.append(
      {
        "code": "preview_not_ready",
        "preview_status": preview_status,
        "message": "Preview/build validation did not reach a ready state.",
      }
    )

  status = "failed" if issues else "satisfied"
  return {
    "status": status,
    "issues": issues,
    "evidence": {
      "changed_paths": changed,
      "target_files": target_files,
      "candidate_files": candidate_files,
      "candidate_new_files": candidate_new_files,
      "required_new_files": required_new_files,
      "mentioned_paths": mentioned_paths,
      "preview_status": preview_status,
    },
  }
