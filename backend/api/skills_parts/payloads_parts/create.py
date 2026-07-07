from __future__ import annotations

from typing import Any

from ..helpers import (
  PROJECT_SKILL_PREFIX,
  _resolved_system_name,
  _summaries,
  _workspace_root,
  build_user_home_skill_materialize_files,
  ensure_user_skills_home,
  llm_skill_markdown,
  skill_description_from_prompt,
  skill_markdown,
  skill_name_from_prompt,
  write_project_skills_index_content,
  write_skills_index,
)


def create_skill_payload(
    prompt: str,
    *,
    workspace_root: str | None = None,
    system_name: str | None = None,
    model_provider: Any | None = None,
    project_id: str | None = None,
    store: Any | None = None,
    user: Any | None = None,
) -> dict[str, Any]:
  root = _workspace_root(workspace_root)
  resolved_name = _resolved_system_name(system_name=system_name, workspace_root=root, local_path=workspace_root)
  home, _created = ensure_user_skills_home(workspace_root=root, system_name=resolved_name)
  name = skill_name_from_prompt(prompt)
  description = skill_description_from_prompt(prompt, name)
  model_authored = model_provider is not None
  gap_analysis = ""
  if model_provider is not None:
    name, description, content, gap_analysis = llm_skill_markdown(name, description, prompt, model_provider)
  else:
    content = skill_markdown(name, description, prompt)
  skill_dir = home / name
  skill_dir.mkdir(parents=True, exist_ok=True)
  skill_md = skill_dir / "SKILL.md"
  skill_md.write_text(content, encoding="utf-8")
  index = write_skills_index(home, workspace_root=root, system_name=resolved_name)
  project_file = {
    "path": f"{PROJECT_SKILL_PREFIX}/{name}/SKILL.md",
    "content": content,
  }
  project_saved = False
  saved_project_file = None
  saved_project_index = None
  project_index_file = None
  if project_id and store is not None and user is not None:
    saved_project_file = store.upsert_file(project_id, user, path=project_file["path"], content=project_file["content"])
    project_saved = True
    if hasattr(store, "list_files"):
      project_files_for_discovery = store.list_files(project_id, user)
    else:
      project_files_for_discovery = [saved_project_file]
    discovered = _summaries(root, project_files=project_files_for_discovery, system_name=resolved_name)
    project_index_file = {
      "path": f"{PROJECT_SKILL_PREFIX}/skills.md",
      "content": write_project_skills_index_content(discovered),
    }
    saved_project_index = store.upsert_file(
      project_id,
      user,
      path=project_index_file["path"],
      content=project_index_file["content"],
    )
  user_home_files = build_user_home_skill_materialize_files(workspace_root=root, system_name=resolved_name)
  return {
    "system_name": resolved_name,
    "name": name,
    "description": description,
    "gap_analysis": gap_analysis,
    "path": str(skill_md),
    "index": str(index),
    "home": str(home),
    "project_file": project_file,
    "project_index_file": project_index_file,
    "project_saved": project_saved,
    "saved_project_file": saved_project_file,
    "saved_project_index": saved_project_index,
    "user_home_files": user_home_files,
    "model_authored": model_authored,
    "message": f"Created skill /{name} at {skill_md}",
  }

