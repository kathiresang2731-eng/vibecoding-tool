from __future__ import annotations

from typing import Any

from ..helpers import _resolved_system_name, _summaries, _workspace_root, discovery_roots, user_skills_home


def list_skills_payload(
    workspace_root: str | None = None,
    *,
    project_files: list[dict] | None = None,
    system_name: str | None = None,
    local_path: str | None = None,
) -> dict[str, Any]:
  root = _workspace_root(workspace_root)
  resolved_name = _resolved_system_name(
    system_name=system_name,
    workspace_root=root,
    local_path=local_path or workspace_root,
  )
  home = user_skills_home(resolved_name)
  skills = _summaries(root, project_files=project_files, system_name=resolved_name)
  return {
    "system_name": resolved_name,
    "home": str(home),
    "index": str(home / "skills.md"),
    "roots": [{"path": str(path), "scope": scope} for path, scope in discovery_roots(root, system_name=resolved_name)],
    "skills": [skill.model_dump() for skill in skills],
    "count": len(skills),
  }


def list_project_skills_payload(
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
  project_files = store.list_files(project_id, user)
  return list_skills_payload(
    str(root) if root else None,
    project_files=project_files,
    system_name=resolved_name,
    local_path=str(project.get("local_path") or "").strip() or workspace_root,
  )

