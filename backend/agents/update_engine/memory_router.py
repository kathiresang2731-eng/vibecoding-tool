from __future__ import annotations

from typing import Any

try:
  from ..chat_history import primary_update_prompt
  from ..memory.context import build_scope_memory_context_block
  from ..memory.episodic import episode_to_memory_row, select_episodic_memories_for_prompt
  from ..memory.context import build_session_memory_context_block
except ImportError:
  from agents.chat_history import primary_update_prompt
  from agents.memory.context import build_scope_memory_context_block, build_session_memory_context_block
  from agents.memory.episodic import episode_to_memory_row, select_episodic_memories_for_prompt


def build_scope_memory_payload(
  *,
  store: Any,
  user: Any,
  project_id: str,
  prompt: str,
  chat_session_id: str | None,
  project_name: str = "",
  project_files: list[dict[str, Any]] | None = None,
  episodic_limit: int = 4,
) -> dict[str, Any]:
  """Single memory load for ScopeEngine — session, episodic, preferences, corrections."""
  scope_prompt = primary_update_prompt(prompt)
  memories: list[dict[str, Any]] = []

  context_block = build_scope_memory_context_block(
    store,
    user,
    project_id=project_id,
    prompt=scope_prompt,
    chat_session_id=chat_session_id,
    project_name=project_name,
    files=project_files,
    episodic_limit=episodic_limit,
  )
  if context_block.strip():
    memories.append(
      {
        "namespace": "scope",
        "kind": "unified_context",
        "key": f"scope-{str(chat_session_id or project_id)[:24]}",
        "content": context_block,
        "metadata_json": {"source": "scope_memory_router"},
      }
    )

  if store is not None and user is not None and chat_session_id:
    session_block = build_session_memory_context_block(store, user, chat_session_id=chat_session_id)
    if session_block.strip():
      memories.append(
        {
          "namespace": "session",
          "kind": "session_state",
          "key": f"session-{str(chat_session_id)[:24]}",
          "content": session_block,
          "metadata_json": {"source": "scope_session_memory"},
        }
      )
    try:
      episodes = select_episodic_memories_for_prompt(
        store,
        user,
        project_id=project_id,
        prompt=scope_prompt,
        chat_session_id=chat_session_id,
        limit=episodic_limit,
      )
    except Exception:
      episodes = []
    for episode in episodes:
      if not isinstance(episode, dict):
        continue
      row = episode_to_memory_row(episode) if "content" not in episode else episode
      if isinstance(row, dict) and str(row.get("content") or "").strip():
        metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
        memories.append({**row, "metadata_json": {**metadata, "source": "scope_episodic_memory"}})

  return {"memories": memories, "memory_count": len(memories), "scope_prompt": scope_prompt}
