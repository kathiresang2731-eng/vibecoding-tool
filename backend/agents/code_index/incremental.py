from __future__ import annotations

from typing import Any

try:
  from ..runtime_config import code_index_enabled
except ImportError:
  from agents.runtime_config import code_index_enabled

from .retriever import index_files
from .store import set_project_chunks


def reindex_project_paths(
  project_id: str,
  files: list[dict[str, Any]],
  *,
  changed_paths: list[str] | None = None,
) -> dict[str, Any]:
  if not code_index_enabled() or not project_id:
    return {"indexed": 0, "skipped": True}
  tool_files = [
    {"path": str(item.get("path") or ""), "content": str(item.get("content") or "")}
    for item in files
    if isinstance(item, dict) and item.get("path")
  ]
  if changed_paths:
    count = index_files(project_id, tool_files, paths=changed_paths)
  else:
    set_project_chunks(project_id, [])
    count = index_files(project_id, tool_files)
  return {"indexed": count, "skipped": False, "paths": changed_paths or []}


def maybe_reindex_after_persist(
  project_id: str,
  files: list[dict[str, Any]],
  *,
  changed_paths: list[str] | None = None,
) -> dict[str, Any]:
  """Best-effort incremental index refresh after file writes."""
  try:
    return reindex_project_paths(project_id, files, changed_paths=changed_paths)
  except Exception as exc:
    return {"indexed": 0, "skipped": False, "error": str(exc)[:500]}
