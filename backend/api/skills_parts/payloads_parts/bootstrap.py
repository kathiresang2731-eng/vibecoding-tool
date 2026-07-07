from __future__ import annotations

from typing import Any

try:
  from ...local_workspace.io import write_local_project_files
except ImportError:
  from local_workspace.io import write_local_project_files

from ..helpers import (
  _resolved_system_name,
  _summaries,
  _workspace_root,
  build_project_skill_materialize_files,
  build_user_home_skill_materialize_files,
  ensure_user_skills_home,
  write_project_skills_index_content,
  write_skills_index,
)


def bootstrap_skills_payload(
    workspace_root: str | None = None,
    *,
    system_name: str | None = None,
) -> dict[str, Any]:
  root = _workspace_root(workspace_root)
  resolved_name = _resolved_system_name(system_name=system_name, workspace_root=root, local_path=workspace_root)
  home, created = ensure_user_skills_home(workspace_root=root, system_name=resolved_name)
  write_skills_index(home, workspace_root=root, system_name=resolved_name)
  skills = _summaries(root, system_name=resolved_name)
  materialize_files = build_project_skill_materialize_files(workspace_root=root, system_name=resolved_name)
  user_home_files = build_user_home_skill_materialize_files(workspace_root=root, system_name=resolved_name)
  return {
    "system_name": resolved_name,
    "home": str(home),
    "index": str(home / "skills.md"),
    "created_defaults": created.get("created_defaults", []),
    "synced_from_repo": created.get("synced_from_repo", []),
    "skills": [skill.model_dump() for skill in skills],
    "count": len(skills),
    "materialize_files": materialize_files,
    "user_home_files": user_home_files,
  }


def _safe_add_project_event(store: Any, project_id: str, user_id: str, event_type: str, payload: dict[str, Any]) -> None:
  try:
    store.add_event(project_id, user_id, event_type, payload)
  except Exception:
    pass


def bootstrap_project_skills_payload(
    project_id: str,
    store: Any,
    user: Any,
    *,
    workspace_root: str | None = None,
    system_name: str | None = None,
) -> dict[str, Any]:
  project = store.get_project(project_id, user)
  if not project:
    raise ValueError("Project not found.")

  linked_root = _workspace_root(str(project.get("local_path") or "").strip() or None)
  requested_root = _workspace_root(workspace_root)
  root = linked_root or requested_root
  resolved_name = _resolved_system_name(
    system_name=system_name,
    workspace_root=root,
    local_path=str(project.get("local_path") or "").strip() or workspace_root,
  )

  payload = bootstrap_skills_payload(
    str(root) if root else None,
    system_name=resolved_name,
  )
  materialize_files = payload.get("materialize_files") or []
  imported_paths: list[str] = []
  for file_item in materialize_files:
    path = str(file_item.get("path") or "").strip()
    content = file_item.get("content")
    if not path or not isinstance(content, str):
      continue
    store.upsert_file(project_id, user, path=path, content=content, emit_event=False)
    imported_paths.append(path)

  if linked_root and materialize_files:
    try:
      write_local_project_files(linked_root, materialize_files)
    except Exception:
      pass

  if imported_paths:
    _safe_add_project_event(
      store,
      project_id,
      user.id,
      "skills.bootstrapped",
      {
        "count": len(imported_paths),
        "paths": imported_paths[:50],
        "system_name": resolved_name,
      },
    )

  project_files = store.list_files(project_id, user)
  payload["project_id"] = project_id
  payload["imported_count"] = len(imported_paths)
  payload["imported_paths"] = imported_paths
  payload["skills"] = [
    skill.model_dump()
    for skill in _summaries(root, project_files=project_files, system_name=resolved_name)
  ]
  payload["count"] = len(payload["skills"])
  return payload

