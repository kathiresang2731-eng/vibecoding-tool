from __future__ import annotations

from typing import Any


def search_codebase_matches(
  *,
  query: str,
  project_files: list[dict[str, str]],
  limit: int = 8,
) -> list[dict[str, Any]]:
  """Hybrid codebase search for the streaming agent search_codebase tool."""
  try:
    from ..runtime_config import code_index_enabled
  except ImportError:
    from agents.runtime_config import code_index_enabled

  if code_index_enabled():
    try:
      from ..code_index.retriever import retrieve_code_context
    except ImportError:
      from agents.code_index.retriever import retrieve_code_context
    return retrieve_code_context(query, project_files, limit=limit)

  try:
    from ..agent_runtime.update_analysis import build_update_code_search_matches
  except ImportError:
    from agents.agent_runtime.update_analysis import build_update_code_search_matches
  return build_update_code_search_matches(query, project_files)[:limit]
