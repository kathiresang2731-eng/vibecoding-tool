from __future__ import annotations

from typing import Any, Callable


ProgressCallback = Callable[..., None]


def _visible_project_files(files: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
  visible: list[dict[str, Any]] = []
  for item in files or []:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "")
    if not path:
      continue
    if any(segment.startswith(".") for segment in path.replace("\\", "/").split("/") if segment):
      continue
    visible.append(item)
  return visible


def _load_scaffold_helpers() -> tuple[Any, Any, Any]:
  try:
    from ..agent_runtime.scaffolding import ensure_vite_scaffold_files
    from ..project_workspace import needs_vite_scaffold_repair
    from ...agentic.tools.handlers import upsert_project_files_tool
  except ImportError:
    from backend.agents.agent_runtime.scaffolding import ensure_vite_scaffold_files
    from backend.agents.project_workspace import needs_vite_scaffold_repair
    from backend.agentic.tools.handlers import upsert_project_files_tool
  return ensure_vite_scaffold_files, needs_vite_scaffold_repair, upsert_project_files_tool


def ensure_visible_scaffold_in_store(
  *,
  project_id: str,
  user: Any,
  tool_context: Any,
  project_name: str = "",
  emit_progress: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
  """Persist platform Vite scaffold files to the project store so they appear in the file tree."""
  emit = emit_progress or (lambda *_args, **_kwargs: None)
  store = getattr(tool_context, "store", None)
  if store is None or not hasattr(store, "list_files"):
    return []

  ensure_vite_scaffold_files, needs_vite_scaffold_repair, upsert_project_files_tool = _load_scaffold_helpers()
  current_files = store.list_files(project_id, user)
  if not needs_vite_scaffold_repair(current_files):
    return _visible_project_files(current_files)

  scaffolded, touched_paths = ensure_vite_scaffold_files(
    current_files,
    title=project_name or "Generated Website",
  )
  if not touched_paths:
    return _visible_project_files(scaffolded)

  write_payload = [
    {"path": path, "content": str(next(item["content"] for item in scaffolded if item["path"] == path))}
    for path in touched_paths
  ]
  try:
    upsert_project_files_tool(
      tool_context,
      user,
      {"project_id": project_id, "files": write_payload, "reason": "platform_vite_scaffold"},
    )
    emit(
      "scaffold.injected",
      f"Saved {len(write_payload)} platform scaffold file(s) to the visible project",
      status="completed",
      detail={"paths": [item["path"] for item in write_payload], "visible": True},
    )
    return _visible_project_files(store.list_files(project_id, user))
  except Exception as exc:
    emit(
      "scaffold.inject.failed",
      f"Could not persist visible scaffold files: {exc}",
      status="failed",
      detail={"error": str(exc), "paths": [item["path"] for item in write_payload]},
    )
    return _visible_project_files(scaffolded)


def visible_project_files_from_store(
  *,
  project_id: str,
  user: Any,
  tool_context: Any,
) -> list[dict[str, Any]]:
  store = getattr(tool_context, "store", None)
  if store is None or not hasattr(store, "list_files"):
    return []
  return _visible_project_files(store.list_files(project_id, user))
