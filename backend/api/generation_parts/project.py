from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
  from backend.orchestration_terminal import orchestration_terminal_verbose_enabled
except ImportError:
  from orchestration_terminal import orchestration_terminal_verbose_enabled

try:
  from backend.agents.providers import DUAL_PROVIDER_ROLE
except ImportError:
  from backend.agents.providers import DUAL_PROVIDER_ROLE


def _project_workspace_root(project: dict[str, Any]) -> Any:
  local_path = str(project.get("local_path") or "").strip()
  if not local_path:
    return None
  root = Path(local_path).expanduser()
  return root if root.is_dir() else None


def should_sync_linked_local_folder(project: dict[str, Any], local_sync: Any) -> bool:
  if not project.get("local_path"):
    return False
  if not isinstance(local_sync, dict):
    return True
  return local_sync.get("direction") != "push" or not local_sync.get("path")


def original_files_for_generated_paths(
  original_files: list[dict[str, Any]],
  generated_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  generated_paths = {
    str(file_item.get("path") or "").strip()
    for file_item in generated_files
    if isinstance(file_item, dict) and str(file_item.get("path") or "").strip()
  }
  if not generated_paths:
    return []
  return [
    file_item
    for file_item in original_files
    if isinstance(file_item, dict) and str(file_item.get("path") or "").strip() in generated_paths
  ]


def is_hidden_project_file_path(path: str) -> bool:
  return any(segment.startswith(".") for segment in str(path or "").replace("\\", "/").split("/") if segment)


def visible_project_files(files: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
  return [
    item
    for item in files or []
    if isinstance(item, dict) and not is_hidden_project_file_path(str(item.get("path") or ""))
  ]


def print_project_workspace_snapshot(
  *,
  stage: str,
  project_id: str,
  project: dict[str, Any],
  files: list[dict[str, Any]] | None,
  generated_files: list[dict[str, Any]] | None = None,
  intent: str = "",
) -> dict[str, Any]:
  """Print path-only workspace diagnostics for backend terminal visibility."""
  relative_paths = [
    str(item.get("path") or "").strip()
    for item in (files or [])
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  generated_paths = [
    str(item.get("path") or "").strip()
    for item in (generated_files or [])
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  root = _project_workspace_root(project)
  resolved_root = str(root.resolve()) if root is not None else ""
  description = str(project.get("description") or "").lower()
  if resolved_root:
    workspace_mode = "server_local_folder"
    folder_display = resolved_root
  elif "browser-selected local workspace" in description:
    workspace_mode = "browser_directory"
    folder_display = str(project.get("name") or "browser-selected-folder")
  elif "browser-uploaded project folder" in description:
    workspace_mode = "browser_upload"
    folder_display = str(project.get("name") or "browser-uploaded-folder")
  else:
    workspace_mode = "project_store"
    folder_display = str(project.get("local_path") or "(no linked local folder)")

  absolute_paths = [
    str((root / path).resolve()) if root is not None else path
    for path in relative_paths
  ]
  absolute_generated_paths = [
    str((root / path).resolve()) if root is not None else path
    for path in generated_paths
  ]
  if orchestration_terminal_verbose_enabled():
    print(f"\n[WorktualWorkspace] stage={stage}", flush=True)
    print(
      f"[WorktualWorkspace] project_id={project_id} "
      f"project_name={str(project.get('name') or '')}",
      flush=True,
    )
    print(
      f"[WorktualWorkspace] mode={workspace_mode} folder={folder_display}",
      flush=True,
    )
    print(
      f"[WorktualWorkspace] input_files={len(relative_paths)} intent={intent or 'pending'}",
      flush=True,
    )
    for path in absolute_paths:
      print(f"[WorktualWorkspace]   input: {path}", flush=True)
    if generated_files is not None:
      print(
        f"[WorktualWorkspace] generated_files={len(generated_paths)}",
        flush=True,
      )
      for path in absolute_generated_paths:
        print(f"[WorktualWorkspace]   output: {path}", flush=True)
      if not generated_paths:
        print(
          "[WorktualWorkspace] WARNING: artifact flow returned zero generated file paths",
          flush=True,
        )

  return {
    "stage": stage,
    "project_id": project_id,
    "project_name": str(project.get("name") or ""),
    "workspace_mode": workspace_mode,
    "folder": folder_display,
    "input_file_count": len(relative_paths),
    "input_paths": relative_paths,
    "resolved_input_paths": absolute_paths,
    "generated_file_count": len(generated_paths),
    "generated_paths": generated_paths,
    "resolved_generated_paths": absolute_generated_paths,
    "intent": intent,
  }


def resolve_control_model_for_request(selected_model: str | None) -> str | None:
  configured = str(os.getenv("GEMINI_CONTROL_MODEL") or "").strip()
  if configured:
    return configured
  default_control = str(os.getenv("GEMINI_DEFAULT_CONTROL_MODEL") or "gemini-3.5-flash").strip()
  if selected_model == "gemini-3.1-pro-preview":
    return default_control
  return selected_model or default_control


def build_gemini_provider(
  provider_cls: Any,
  *,
  model: str | None,
  provider_role: str,
  existing_provider: Any | None = None,
) -> Any:
  if existing_provider is not None and getattr(existing_provider, "provider_role", None) == DUAL_PROVIDER_ROLE:
    return existing_provider
  try:
    return provider_cls(model=model, provider_role=provider_role)
  except TypeError:
    return provider_cls(model=model)
