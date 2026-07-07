"""Unified memory injection for LangGraph / legacy agent runtime loops."""

from __future__ import annotations

from typing import Any, Callable

try:
  from .context import build_unified_memory_context_block
except ImportError:
  from agents.memory.context import build_unified_memory_context_block

ProgressCallback = Callable[..., None]


def augment_memory_result_with_unified_context(
  memory_result: dict[str, Any],
  *,
  store: Any,
  user: Any,
  project_id: str,
  prompt: str,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  files: list[dict[str, Any]] | None = None,
  progress: ProgressCallback | None = None,
) -> dict[str, Any]:
  if not chat_session_id or store is None:
    return memory_result

  unified_block = build_unified_memory_context_block(
    store,
    user,
    project_id=project_id,
    prompt=prompt,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
    project_name=project_name,
    files=files,
  )
  if not unified_block:
    return memory_result

  memories = list(memory_result.get("memories") or [])
  memories.insert(
    0,
    {
      "namespace": "session",
      "kind": "unified_context",
      "key": f"session-{chat_session_id[:24]}",
      "content": unified_block,
      "metadata": {
        "source": "unified_memory_context",
        "chat_session_id": chat_session_id,
        "chat_topic_id": chat_topic_id,
      },
    },
  )
  enriched = {
    **memory_result,
    "memories": memories,
    "memory_count": len(memories),
    "unified_context": unified_block,
  }
  if progress:
    progress(
      "memory.context.injected",
      "Injected unified session, preference, and episodic memory into agent runtime",
      status="completed",
      detail={
        "chat_session_id": chat_session_id,
        "chat_topic_id": chat_topic_id,
        "context_chars": len(unified_block),
        "memory_count": len(memories),
      },
    )
  return enriched
