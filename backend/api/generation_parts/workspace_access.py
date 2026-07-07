from __future__ import annotations

import os
import re
from typing import Any

from fastapi import HTTPException

from backend.local_workspace import LocalWorkspaceError, resolve_local_project_path


UPDATE_WORKSPACE_ERROR = (
  "Website/code updates require a connected writable local folder. "
  "Reconnect the original browser folder or link a server-local project path, then retry."
)

_UPDATE_MARKERS = re.compile(
  r"\b(update|change|fix|repair|debug|resolve|edit|modify|replace|remove|rename|refactor|"
  r"add|implement|patch|correct|create\s+(?:a\s+)?(?:new\s+)?(?:file|page|component|feature|route|api|landing\s+page))\b",
  re.IGNORECASE,
)
_ERROR_MARKERS = re.compile(
  r"\b(error|exception|traceback|failed|failure|not\s+defined|cannot\s+find|could\s+not\s+resolve|"
  r"module\s+not\s+found|syntaxerror|referenceerror|typeerror)\b",
  re.IGNORECASE,
)
_NEW_PROJECT_MARKERS = re.compile(
  r"\b(generate|build|create)\b[\s\S]{0,80}\b(new\s+)?(website|web\s+app|app|project|landing\s+page)\b",
  re.IGNORECASE,
)


def prompt_requires_writable_workspace(
  prompt: str,
  *,
  project_files: list[dict[str, Any]] | None = None,
) -> bool:
  """Conservative pre-route mutation check used before model/tool execution."""
  text = str(prompt or "").strip()
  if not text:
    return False
  has_existing_files = any(
    isinstance(item, dict) and str(item.get("path") or "").strip()
    for item in (project_files or [])
  )
  if not has_existing_files:
    return False
  if _NEW_PROJECT_MARKERS.search(text) and not _UPDATE_MARKERS.search(text):
    return False
  return bool(_UPDATE_MARKERS.search(text) or _ERROR_MARKERS.search(text))


def inspect_server_workspace(project: dict[str, Any], settings: Any) -> dict[str, Any]:
  raw_path = str(project.get("local_path") or "").strip()
  if not raw_path:
    return {
      "required": True,
      "connected": False,
      "writable": False,
      "mode": "browser_or_missing",
      "reason": "server_local_path_missing",
    }
  try:
    root = resolve_local_project_path(settings, raw_path)
  except LocalWorkspaceError as exc:
    return {
      "required": True,
      "connected": False,
      "writable": False,
      "mode": "local_path",
      "path": raw_path,
      "reason": str(exc),
    }
  connected = root.exists() and root.is_dir()
  writable = connected and os.access(root, os.R_OK | os.W_OK | os.X_OK)
  return {
    "required": True,
    "connected": connected,
    "writable": writable,
    "mode": "local_path",
    "path": str(root),
    "name": root.name,
    "reason": "" if connected and writable else "Linked local folder is missing or not writable.",
  }


def normalize_client_workspace_access(access: dict[str, Any] | None) -> dict[str, Any]:
  payload = access if isinstance(access, dict) else {}
  mode = str(payload.get("mode") or "missing").strip().lower()
  return {
    "mode": mode,
    "connected": bool(payload.get("connected")),
    "writable": bool(payload.get("writable")),
    "name": str(payload.get("name") or "").strip()[:240],
  }


def ensure_update_workspace_ready(
  *,
  prompt: str,
  project: dict[str, Any],
  project_files: list[dict[str, Any]],
  settings: Any,
  client_workspace_access: dict[str, Any] | None = None,
) -> dict[str, Any]:
  if not prompt_requires_writable_workspace(prompt, project_files=project_files):
    return {
      "required": False,
      "connected": True,
      "writable": True,
      "mode": "not_required",
    }

  server_access = inspect_server_workspace(project, settings)
  if server_access.get("connected") and server_access.get("writable"):
    return server_access

  client_access = normalize_client_workspace_access(client_workspace_access)
  if (
    client_access["mode"] == "browser_directory"
    and client_access["connected"]
    and client_access["writable"]
  ):
    return {"required": True, **client_access}

  reason = (
    "The selected browser folder is read-only."
    if client_access["mode"] == "browser_upload"
    else "Writable local-folder access is not connected in this browser tab."
  )
  raise HTTPException(
    status_code=409,
    detail={
      "category": "workspace_access",
      "code": "writable_workspace_required",
      "user_message": UPDATE_WORKSPACE_ERROR,
      "reason": reason,
      "workspace_access": client_access,
      "suggested_actions": [
        "Reconnect the same browser folder with read/write permission.",
        "Or link a server-local folder path and retry the update.",
      ],
    },
  )


def local_workspace_readiness(project: dict[str, Any], settings: Any) -> dict[str, Any]:
  access = inspect_server_workspace(project, settings)
  if access.get("mode") == "local_path":
    return access
  description = str(project.get("description") or "").lower()
  if "browser-selected local workspace" in description:
    return {
      **access,
      "mode": "browser_directory",
      "reason": "Browser permission must be verified by the current tab.",
    }
  if "browser-uploaded project folder" in description:
    return {
      **access,
      "mode": "browser_upload",
      "reason": "Uploaded folders are read-only; reconnect with the writable folder picker.",
    }
  return access
