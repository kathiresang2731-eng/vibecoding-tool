from __future__ import annotations

import re
from typing import Any

from ..budget_config import AGENT_BUDGETS
from .extractors import EPISODE_EXTRACTOR_PROMPT, SESSION_CLOSE_EPISODE_EXTRACTOR_PROMPT, USER_PREFERENCE_EXTRACTOR_PROMPT

ALLOWED_SESSION_EPISODE_TYPES = frozenset(
  {"fix_pattern", "workflow", "tool_pattern", "conversation_improvement", "update_checkpoint"}
)

_PREFERENCE_MARKERS = (
  ("testing", r"\b(jest|vitest|playwright|unit test|integration test)\b"),
  ("style", r"\b(tailwind|typescript|jsx|functional component|minimal ui)\b"),
  ("workflow", r"\b(explain|concise|detailed|step by step|no comments)\b"),
)

_NEGATIVE_MARKERS = ("don't", "do not", "never", "avoid", "without", "no ")


def _session_already_extracted(store: Any, user: Any, chat_session_id: str) -> bool:
  if not hasattr(store, "get_memory_chat_session_state"):
    return False
  state = store.get_memory_chat_session_state(user, chat_session_id=chat_session_id)
  if not isinstance(state, dict):
    return False
  metadata = state.get("metadata_json") if isinstance(state.get("metadata_json"), dict) else {}
  if not metadata and isinstance(state.get("metadata"), dict):
    metadata = state["metadata"]
  return bool(metadata.get("extraction_completed_at"))


def _mark_session_extracted(store: Any, user: Any, *, project_id: str, chat_session_id: str) -> None:
  if not hasattr(store, "upsert_memory_chat_session_state"):
    return
  prior = store.get_memory_chat_session_state(user, chat_session_id=chat_session_id) if hasattr(store, "get_memory_chat_session_state") else None
  rolling_summary = str((prior or {}).get("rolling_summary") or "Session closed — memories extracted.")
  metadata = {}
  if isinstance(prior, dict):
    metadata = prior.get("metadata_json") if isinstance(prior.get("metadata_json"), dict) else {}
    if not metadata and isinstance(prior.get("metadata"), dict):
      metadata = dict(prior["metadata"])
  from datetime import datetime, timezone

  metadata["extraction_completed_at"] = datetime.now(timezone.utc).isoformat()
  store.upsert_memory_chat_session_state(
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    rolling_summary=rolling_summary,
    changed_paths=(prior or {}).get("last_changed_paths_json") or [],
    preview_status=(prior or {}).get("last_preview_status"),
    error_category=(prior or {}).get("last_error_category"),
    file_count=int((prior or {}).get("file_count") or 0),
    generation_run_id=(prior or {}).get("last_generation_run_id"),
    metadata=metadata,
  )


def _load_session_messages(store: Any, user: Any, *, project_id: str, chat_session_id: str, limit: int = 40) -> list[dict[str, Any]]:
  if not hasattr(store, "list_project_chat_messages"):
    return []
  rows = store.list_project_chat_messages(project_id, user, limit=limit, chat_session_id=chat_session_id)
  messages: list[dict[str, Any]] = []
  for row in rows:
    if not isinstance(row, dict):
      continue
    role = str(row.get("role") or "user").strip().lower()
    content = str(row.get("content") or "").strip()
    if content:
      messages.append({"role": role, "content": content[:1200]})
  return messages


def _heuristic_preferences(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
  user_text = "\n".join(item["content"] for item in messages if item.get("role") == "user").lower()
  if not user_text.strip():
    return []
  extracted: list[dict[str, Any]] = []
  for category, pattern in _PREFERENCE_MARKERS:
    if not re.search(pattern, user_text, re.IGNORECASE):
      continue
    match = re.search(pattern, user_text, re.IGNORECASE)
    if not match:
      continue
    window_start = max(0, match.start() - 40)
    window_end = min(len(user_text), match.end() + 80)
    snippet = user_text[window_start:window_end].strip()
    polarity = "negative" if any(marker in snippet for marker in _NEGATIVE_MARKERS) else "positive"
    extracted.append(
      {
        "category": category,
        "preference": snippet[:180],
        "polarity": polarity,
        "confidence": 0.72,
        "durability": "long_term",
        "reason": "Heuristic extraction from closed chat session",
      }
    )
  try:
    from .correction_learning import extract_correction_preferences
  except ImportError:
    from agents.memory.correction_learning import extract_correction_preferences
  correction_preferences = extract_correction_preferences(messages)
  seen = {
    (str(item.get("category") or ""), str(item.get("preference") or ""))
    for item in extracted
  }
  for item in correction_preferences:
    key = (str(item.get("category") or ""), str(item.get("preference") or ""))
    if key not in seen:
      extracted.append(item)
      seen.add(key)
  return extracted[:6]


def _normalize_session_episode(
  episode: dict[str, Any] | None,
  *,
  project_id: str,
  chat_session_id: str,
) -> dict[str, Any] | None:
  if not isinstance(episode, dict):
    return None
  memory_type = str(episode.get("memory_type") or "conversation_improvement").strip()
  if memory_type not in ALLOWED_SESSION_EPISODE_TYPES:
    memory_type = "conversation_improvement"
  title = str(episode.get("title") or "Closed session summary").strip()[:240]
  searchable_summary = str(episode.get("searchable_summary") or episode.get("summary") or "").strip()[:4000]
  if not searchable_summary:
    return None
  metadata = episode.get("metadata") if isinstance(episode.get("metadata"), dict) else {}
  return {
    "memory_type": memory_type,
    "title": title,
    "searchable_summary": searchable_summary,
    "situation": str(episode.get("situation") or "")[:2000],
    "improved_behavior": str(episode.get("improved_behavior") or "")[:2000],
    "avoid": str(episode.get("avoid") or "")[:1200],
    "outcome": str(episode.get("outcome") or "completed")[:64] or "completed",
    "metadata": {
      **metadata,
      "source": metadata.get("source") or "session_close_extraction",
      "chat_session_id": chat_session_id,
      "project_id": project_id,
    },
  }


def _llm_extract_episode(messages: list[dict[str, Any]], *, settings: Any) -> dict[str, Any] | None:
  api_key = str(getattr(settings, "gemini_api_key", "") or "").strip()
  if not api_key or len(messages) < 2:
    return None
  try:
    from ..gemini_client import GeminiClient
  except ImportError:
    from agents.gemini_client import GeminiClient

  transcript = "\n".join(f"{item['role']}: {item['content']}" for item in messages[-24:])
  schema = {
    "type": "object",
    "properties": {
      "episode": {
        "type": "object",
        "properties": {
          "memory_type": {"type": "string"},
          "title": {"type": "string"},
          "searchable_summary": {"type": "string"},
          "situation": {"type": "string"},
          "improved_behavior": {"type": "string"},
          "avoid": {"type": "string"},
          "outcome": {"type": "string"},
        },
        "required": ["searchable_summary"],
      }
    },
    "required": ["episode"],
  }
  client = GeminiClient(api_key=api_key, model=str(getattr(settings, "gemini_model", "") or "gemini-3.5-flash"))
  payload = client.generate_json(
    f"{SESSION_CLOSE_EPISODE_EXTRACTOR_PROMPT}\n{EPISODE_EXTRACTOR_PROMPT}\n\nTranscript:\n{transcript}",
    trace_label="session_close_episode_extraction",
    response_schema=schema,
    max_output_tokens=AGENT_BUDGETS.memory_output_tokens,
  )
  episode = payload.get("episode") if isinstance(payload, dict) else None
  if not isinstance(episode, dict):
    return None
  episode["metadata"] = {"source": "session_close_llm_extraction"}
  return episode


def _extract_session_episode(
  messages: list[dict[str, Any]],
  *,
  project_id: str,
  chat_session_id: str,
  settings: Any | None = None,
  use_llm: bool = True,
) -> tuple[dict[str, Any] | None, str]:
  if use_llm and settings is not None:
    try:
      llm_episode = _llm_extract_episode(messages, settings=settings)
      normalized = _normalize_session_episode(
        llm_episode,
        project_id=project_id,
        chat_session_id=chat_session_id,
      )
      if normalized:
        normalized["metadata"]["source"] = "session_close_llm_extraction"
        return normalized, "llm"
    except Exception:
      pass
  heuristic = _heuristic_episode(messages, project_id=project_id, chat_session_id=chat_session_id)
  normalized = _normalize_session_episode(
    heuristic,
    project_id=project_id,
    chat_session_id=chat_session_id,
  )
  if normalized:
    return normalized, "heuristic"
  return None, "none"


def _heuristic_episode(messages: list[dict[str, Any]], *, project_id: str, chat_session_id: str) -> dict[str, Any] | None:
  if len(messages) < 2:
    return None
  user_lines = [item["content"] for item in messages if item.get("role") == "user"]
  if not user_lines:
    return None
  summary = f"Session covered {len(user_lines)} user request(s). Last request: {user_lines[-1][:240]}"
  return {
    "memory_type": "conversation_improvement",
    "title": "Closed session summary",
    "searchable_summary": summary,
    "situation": user_lines[0][:400],
    "improved_behavior": "Reuse successful patterns from this session when the user returns to similar tasks.",
    "avoid": "",
    "outcome": "completed",
    "metadata": {"source": "session_close_extraction", "chat_session_id": chat_session_id, "project_id": project_id},
  }


def _llm_extract_preferences(messages: list[dict[str, Any]], *, settings: Any) -> list[dict[str, Any]]:
  api_key = str(getattr(settings, "gemini_api_key", "") or "").strip()
  if not api_key or len(messages) < 2:
    return []
  try:
    from ..gemini_client import GeminiClient
  except ImportError:
    from agents.gemini_client import GeminiClient

  transcript = "\n".join(f"{item['role']}: {item['content']}" for item in messages[-24:])
  schema = {
    "type": "object",
    "properties": {
      "preferences": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "category": {"type": "string"},
            "preference": {"type": "string"},
            "polarity": {"type": "string"},
            "confidence": {"type": "number"},
            "durability": {"type": "string"},
            "reason": {"type": "string"},
          },
          "required": ["category", "preference"],
        },
      }
    },
    "required": ["preferences"],
  }
  client = GeminiClient(api_key=api_key, model=str(getattr(settings, "gemini_model", "") or "gemini-3.5-flash"))
  payload = client.generate_json(
    f"{USER_PREFERENCE_EXTRACTOR_PROMPT}\n\nTranscript:\n{transcript}",
    trace_label="session_close_preference_extraction",
    response_schema=schema,
    max_output_tokens=AGENT_BUDGETS.memory_output_tokens,
  )
  preferences = payload.get("preferences") if isinstance(payload, dict) else []
  return [item for item in preferences if isinstance(item, dict)]


def _persist_preferences(store: Any, user: Any, preferences: list[dict[str, Any]]) -> int:
  if not hasattr(store, "upsert_memory_preference"):
    return 0
  saved = 0
  for item in preferences:
    category = str(item.get("category") or "").strip()
    preference = str(item.get("preference") or "").strip()
    if not category or not preference:
      continue
    store.upsert_memory_preference(
      user,
      category=category,
      preference=preference,
      polarity=str(item.get("polarity") or "positive"),
      confidence=float(item.get("confidence") or 0.75),
      durability=str(item.get("durability") or "long_term"),
      reason=str(item.get("reason") or "Extracted when chat session closed"),
      metadata={
        "source": "session_close_extraction",
        **(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
      },
    )
    saved += 1
  return saved


def _persist_episode(store: Any, user: Any, *, project_id: str, chat_session_id: str, episode: dict[str, Any]) -> bool:
  if not hasattr(store, "insert_memory_episode"):
    return False
  row = store.insert_memory_episode(
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    generation_run_id=None,
    scope="personal",
    memory_type=str(episode.get("memory_type") or "conversation_improvement"),
    title=str(episode.get("title") or "Session lesson")[:240],
    searchable_summary=str(episode.get("searchable_summary") or "")[:4000],
    situation=str(episode.get("situation") or "")[:2000],
    improved_behavior=str(episode.get("improved_behavior") or "")[:2000],
    avoid=str(episode.get("avoid") or "")[:1200],
    outcome=str(episode.get("outcome") or "completed"),
    metadata=episode.get("metadata") if isinstance(episode.get("metadata"), dict) else {},
  )
  if isinstance(row, dict):
    try:
      from .episode_vector_sync import sync_episode_vector_from_row

      sync_episode_vector_from_row(
        row,
        user_id=str(user.id),
        project_id=project_id,
        chat_session_id=chat_session_id,
      )
    except Exception:
      pass
  return True


def extract_closed_session_memories(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str,
  settings: Any | None = None,
  use_llm: bool = True,
) -> dict[str, Any]:
  if not store or not chat_session_id:
    return {"status": "skipped", "reason": "missing_session"}
  if _session_already_extracted(store, user, chat_session_id):
    return {"status": "skipped", "reason": "already_extracted"}

  messages = _load_session_messages(store, user, project_id=project_id, chat_session_id=chat_session_id)
  if len(messages) < 2:
    return {"status": "skipped", "reason": "insufficient_messages", "message_count": len(messages)}

  preferences = _heuristic_preferences(messages)
  if use_llm and settings is not None:
    try:
      llm_preferences = _llm_extract_preferences(messages, settings=settings)
      if llm_preferences:
        preferences = llm_preferences
    except Exception:
      pass

  episode, episode_source = _extract_session_episode(
    messages,
    project_id=project_id,
    chat_session_id=chat_session_id,
    settings=settings,
    use_llm=use_llm,
  )
  preference_count = _persist_preferences(store, user, preferences)
  episode_saved = bool(episode and _persist_episode(store, user, project_id=project_id, chat_session_id=chat_session_id, episode=episode))
  _mark_session_extracted(store, user, project_id=project_id, chat_session_id=chat_session_id)

  return {
    "status": "completed",
    "chat_session_id": chat_session_id,
    "preference_count": preference_count,
    "episode_saved": episode_saved,
    "episode_source": episode_source,
    "message_count": len(messages),
  }
