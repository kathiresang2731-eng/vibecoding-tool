from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

EPISODIC_NAMESPACE = "project"
EPISODIC_KIND = "episodic"
MAX_EPISODIC_ITEMS = 5
MAX_STORED_EPISODIC_ROWS = 20
MAX_EPISODIC_CONTENT_CHARS = 2400
NON_EPISODIC_INTENTS = frozenset(
  {
    "greeting",
    "conversation",
    "requirement_confirmation",
    "needs_more_detail",
    "project_info",
  }
)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}")


def _utc_now() -> str:
  return datetime.now(timezone.utc).isoformat()


def _text(value: Any, default: str = "") -> str:
  return str(value or default).strip() or default


def _normalize_metadata(metadata: Any) -> dict[str, Any]:
  if isinstance(metadata, dict):
    return metadata
  return {}


def metadata_from_memory_row(row: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(row, dict):
    return {}
  if isinstance(row.get("metadata"), dict):
    return row["metadata"]
  return _normalize_metadata(row.get("metadata_json"))


def build_episodic_run_key(*, run_id: str | None, intent: str, chat_session_id: str | None = None) -> str:
  digest = _text(run_id, "latest")
  session_scope = _text(chat_session_id, "no-session")[:24]
  if digest != "latest":
    return f"{session_scope}-run-{digest}"
  return f"{session_scope}-latest-{intent or 'run'}"


def summarize_episodic_run(
  *,
  intent: str,
  prompt: str,
  outcome: str,
  file_count: int = 0,
  changed_paths: list[str] | None = None,
  preview_status: str | None = None,
  error_category: str | None = None,
) -> str:
  lines = [
    f"Intent: {intent or 'unknown'}",
    f"Outcome: {outcome or 'completed'}",
    f"User request: {_text(prompt)[:400]}",
  ]
  if file_count:
    lines.append(f"Files in workspace: {file_count}")
  if changed_paths:
    lines.append(f"Changed paths: {', '.join(changed_paths[:12])}")
  if preview_status:
    lines.append(f"Preview: {preview_status}")
  if error_category:
    lines.append(f"Last error category: {error_category}")
  return "\n".join(lines)[:MAX_EPISODIC_CONTENT_CHARS]


def tokenize_for_relevance(text: str) -> set[str]:
  return set(_TOKEN_PATTERN.findall(_text(text).lower()))


def score_episodic_relevance(memory: dict[str, Any], prompt: str) -> float:
  prompt_tokens = tokenize_for_relevance(prompt)
  if not prompt_tokens:
    return 0.0
  metadata = metadata_from_memory_row(memory)
  haystack = " ".join(
    [
      _text(memory.get("content")),
      _text(metadata.get("intent")),
      _text(metadata.get("outcome")),
      " ".join(str(path) for path in metadata.get("changed_paths") or []),
    ]
  )
  memory_tokens = tokenize_for_relevance(haystack)
  if not memory_tokens:
    return 0.0
  overlap = len(prompt_tokens & memory_tokens)
  return overlap / max(len(prompt_tokens), 1)


def filter_episodic_memories(
  memories: list[dict[str, Any]],
  *,
  chat_session_id: str | None = None,
) -> list[dict[str, Any]]:
  """Strict session isolation — never merge other chats, even for the same user/project."""
  if not memories or not chat_session_id:
    return []
  session_matches: list[dict[str, Any]] = []
  for item in memories:
    metadata = metadata_from_memory_row(item)
    stored_session_id = _text(metadata.get("chat_session_id"))
    if stored_session_id == chat_session_id:
      session_matches.append(item)
  return session_matches


def rank_episodic_memories(
  memories: list[dict[str, Any]],
  *,
  prompt: str = "",
) -> list[dict[str, Any]]:
  if not memories:
    return []
  if not _text(prompt):
    return list(memories)

  try:
    from ..runtime_config import episodic_hybrid_retrieval_enabled
  except ImportError:
    from agents.runtime_config import episodic_hybrid_retrieval_enabled

  if episodic_hybrid_retrieval_enabled():
    try:
      from .episode_retrieval import rank_episodic_memories_hybrid

      return rank_episodic_memories_hybrid(memories, prompt=prompt)
    except ImportError:
      from agents.memory.episode_retrieval import rank_episodic_memories_hybrid

      return rank_episodic_memories_hybrid(memories, prompt=prompt)

  def sort_key(item: dict[str, Any]) -> tuple[float, str]:
    relevance = score_episodic_relevance(item, prompt)
    updated_at = _text(item.get("updated_at"))
    return (relevance, updated_at)

  return sorted(memories, key=sort_key, reverse=True)


def serialize_episodic_memory_for_api(row: dict[str, Any]) -> dict[str, Any]:
  metadata = metadata_from_memory_row(row)
  changed_paths = metadata.get("changed_paths")
  return {
    "id": row.get("id"),
    "key": row.get("key"),
    "content": row.get("content") or "",
    "intent": _text(metadata.get("intent")),
    "outcome": _text(metadata.get("outcome")),
    "run_id": _text(metadata.get("run_id")),
    "chat_session_id": _text(metadata.get("chat_session_id")),
    "changed_paths": changed_paths if isinstance(changed_paths, list) else [],
    "recorded_at": _text(metadata.get("recorded_at")) or row.get("updated_at"),
    "updated_at": row.get("updated_at"),
    "metadata": metadata,
  }


def should_write_episodic_episode(
  *,
  intent: str,
  outcome: str,
  changed_paths: list[str] | None = None,
  error_category: str | None = None,
) -> bool:
  """Skip chat-only turns; keep runs that changed files or hit recoverable errors."""
  normalized_intent = _text(intent, "unknown").lower()
  if normalized_intent in NON_EPISODIC_INTENTS:
    return False
  if error_category or str(outcome or "").strip().lower() == "failed":
    return True
  if changed_paths:
    return True
  return normalized_intent in {"website_generation", "website_update", "simple_code", "scoped_update"}


def prune_episodic_memories(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str | None = None,
) -> int:
  if store is None:
    return 0
  pruned = 0
  if chat_session_id and hasattr(store, "prune_memory_episodes"):
    pruned += int(
      store.prune_memory_episodes(
        user,
        project_id=project_id,
        chat_session_id=chat_session_id,
        keep=MAX_STORED_EPISODIC_ROWS,
      )
      or 0
    )
  if hasattr(store, "prune_memory_items"):
    pruned += int(
      store.prune_memory_items(
        user,
        project_id=project_id,
        namespace=EPISODIC_NAMESPACE,
        kind=EPISODIC_KIND,
        keep=MAX_STORED_EPISODIC_ROWS,
      )
      or 0
    )
  return pruned


def episode_to_memory_row(episode: dict[str, Any]) -> dict[str, Any]:
  """Adapt structured memory_episodes rows to legacy episodic memory_item shape."""
  if not isinstance(episode, dict):
    return {}
  metadata = episode.get("metadata_json") if isinstance(episode.get("metadata_json"), dict) else {}
  if not metadata and isinstance(episode.get("metadata"), dict):
    metadata = episode["metadata"]
  changed_paths = episode.get("changed_paths_json")
  if not isinstance(changed_paths, list):
    changed_paths = metadata.get("changed_paths") if isinstance(metadata.get("changed_paths"), list) else []
  intent = _text(metadata.get("intent") or episode.get("memory_type"))
  outcome = _text(episode.get("outcome") or metadata.get("outcome") or "completed")
  content = _text(episode.get("searchable_summary"))
  if not content:
    content = summarize_episodic_run(
      intent=intent,
      prompt=_text(metadata.get("prompt")),
      outcome=outcome,
      changed_paths=changed_paths,
    )
  episode_id = _text(episode.get("id"), "episode")
  return {
    "id": episode.get("id"),
    "key": f"episode-{episode_id}",
    "content": content,
    "kind": EPISODIC_KIND,
    "metadata_json": {
      "source": "memory_episodes",
      "intent": intent,
      "outcome": outcome,
      "run_id": episode.get("generation_run_id") or metadata.get("run_id"),
      "chat_session_id": episode.get("chat_session_id") or metadata.get("chat_session_id"),
      "changed_paths": list(changed_paths or [])[:12],
      "recorded_at": episode.get("created_at") or metadata.get("recorded_at"),
      **metadata,
    },
    "updated_at": episode.get("updated_at") or episode.get("created_at") or "",
  }


def _list_legacy_episodic_items(
  store: Any,
  user: Any,
  *,
  project_id: str,
  fetch_limit: int,
) -> list[dict[str, Any]]:
  try:
    from .legacy_episodic import list_legacy_episodic_items

    return list_legacy_episodic_items(
      store,
      user,
      project_id=project_id,
      fetch_limit=fetch_limit,
    )
  except ImportError:
    from agents.memory.legacy_episodic import list_legacy_episodic_items

    return list_legacy_episodic_items(
      store,
      user,
      project_id=project_id,
      fetch_limit=fetch_limit,
    )


def _list_structured_episodic_items(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str,
  fetch_limit: int,
) -> list[dict[str, Any]]:
  if not hasattr(store, "list_memory_episodes"):
    return []
  episodes = store.list_memory_episodes(
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    scope="personal",
    limit=fetch_limit,
  )
  return [episode_to_memory_row(item) for item in episodes if isinstance(item, dict)]


def list_episodic_memories(
  store: Any,
  user: Any,
  *,
  project_id: str,
  limit: int = MAX_EPISODIC_ITEMS,
  chat_session_id: str | None = None,
  prompt: str = "",
) -> list[dict[str, Any]]:
  if not chat_session_id:
    return []
  if store is None:
    return []
  fetch_limit = max(limit * 4, MAX_EPISODIC_ITEMS * 2, 12)
  structured = _list_structured_episodic_items(
    store,
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    fetch_limit=fetch_limit,
  )
  if structured:
    filtered = filter_episodic_memories(structured, chat_session_id=chat_session_id)
    ranked = _rank_episodes_for_prompt(
      filtered,
      prompt=prompt,
      user=user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      fetch_limit=fetch_limit,
    )
    return ranked[: max(1, min(limit, MAX_EPISODIC_ITEMS))]

  legacy_items = _list_legacy_episodic_items(store, user, project_id=project_id, fetch_limit=fetch_limit)
  if not legacy_items:
    return []
  filtered = filter_episodic_memories(legacy_items, chat_session_id=chat_session_id)
  ranked = _rank_episodes_for_prompt(
    filtered,
    prompt=prompt,
    user=user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    fetch_limit=fetch_limit,
  )
  return ranked[: max(1, min(limit, MAX_EPISODIC_ITEMS))]


def _rank_episodes_for_prompt(
  memories: list[dict[str, Any]],
  *,
  prompt: str,
  user: Any,
  project_id: str,
  chat_session_id: str,
  fetch_limit: int,
) -> list[dict[str, Any]]:
  vector_scores: dict[str, float] = {}
  if _text(prompt) and user is not None and getattr(user, "id", None):
    try:
      from .episode_retrieval import search_episodes_via_qdrant
      from .episode_vector_store import episodic_vector_search_enabled
    except ImportError:
      from agents.memory.episode_retrieval import search_episodes_via_qdrant
      from agents.memory.episode_vector_store import episodic_vector_search_enabled

    if episodic_vector_search_enabled():
      hits = search_episodes_via_qdrant(
        query=prompt,
        user_id=str(user.id),
        project_id=project_id,
        chat_session_id=chat_session_id,
        limit=max(fetch_limit, MAX_EPISODIC_ITEMS * 2),
      )
      vector_scores = {
        str(item.get("episode_id") or ""): float(item.get("score") or 0.0)
        for item in hits
        if isinstance(item, dict) and item.get("episode_id")
      }

  if vector_scores:
    try:
      from .episode_retrieval import rank_episodic_memories_with_vector
    except ImportError:
      from agents.memory.episode_retrieval import rank_episodic_memories_with_vector

    return rank_episodic_memories_with_vector(memories, prompt=prompt, vector_scores=vector_scores)
  return rank_episodic_memories(memories, prompt=prompt)


def select_episodic_memories_for_prompt(
  store: Any,
  user: Any,
  *,
  project_id: str,
  prompt: str,
  chat_session_id: str | None = None,
  limit: int = MAX_EPISODIC_ITEMS,
) -> list[dict[str, Any]]:
  return list_episodic_memories(
    store,
    user,
    project_id=project_id,
    limit=limit,
    chat_session_id=chat_session_id,
    prompt=prompt,
  )


def build_episodic_context_block(memories: list[dict[str, Any]], *, prompt: str = "") -> str:
  if not memories:
    return ""
  ranked = rank_episodic_memories(memories, prompt=prompt) if _text(prompt) else memories
  lines = ["Relevant episodic memory for this chat session only (not other chats or users):"]
  for item in ranked:
    if not isinstance(item, dict):
      continue
    key = _text(item.get("key"), "run")
    content = _text(item.get("content"))
    if not content:
      continue
    metadata = metadata_from_memory_row(item)
    intent = _text(metadata.get("intent"))
    outcome = _text(metadata.get("outcome"))
    header = f"[{EPISODIC_NAMESPACE}/{EPISODIC_KIND}/{key}]"
    if intent or outcome:
      header = f"{header} ({intent or 'run'} · {outcome or 'completed'})"
    lines.append(f"{header}\n{content}")
  if len(lines) == 1:
    return ""
  return "\n\n".join(lines)[:MAX_EPISODIC_CONTENT_CHARS]
