"""Unified memory context for prompts — session, episodic, platform learning."""

from __future__ import annotations

from typing import Any

from .dedup import dedupe_memory_blocks
from .episodic import build_episodic_context_block, select_episodic_memories_for_prompt
from .platform_learning import (
  platform_pattern_injection_allowed,
  platform_pattern_min_source_count,
  platform_pattern_promotion_status,
  select_platform_patterns_for_prompt,
)
from .session_monitor import infer_domain, infer_modules
from .project_knowledge import (
  build_project_ui_knowledge_context,
  select_project_ui_knowledge,
)

try:
  from ..project_workspace import meaningful_project_source_files
except ImportError:
  from agents.project_workspace import meaningful_project_source_files


def build_session_memory_context_block(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str | None,
  chat_topic_id: str | None = None,
) -> str:
  if chat_topic_id and store and hasattr(store, "get_memory_chat_topic"):
    topic = store.get_memory_chat_topic(user, chat_topic_id=chat_topic_id)
    if topic and not (
      str(topic.get("project_id") or "") == str(project_id)
      and str(topic.get("chat_session_id") or "") == str(chat_session_id or "")
      and str(topic.get("user_id") or "") == str(getattr(user, "id", ""))
    ):
      return ""
    if (
      topic
      and str(topic.get("project_id") or "") == str(project_id)
      and str(topic.get("chat_session_id") or "") == str(chat_session_id or "")
      and str(topic.get("user_id") or "") == str(getattr(user, "id", ""))
    ):
      lines = [
        "Chat topic continuity memory (same chat session, selected topic only):",
        f"- Topic: {topic.get('label') or 'Current task'}",
        f"- Intent family: {topic.get('intent_family') or 'general'}",
      ]
      paths = topic.get("last_changed_paths_json") if isinstance(topic.get("last_changed_paths_json"), list) else []
      if paths:
        lines.append(f"- Recently changed in this topic: {', '.join(str(p) for p in paths[:12])}")
      summary = str(topic.get("rolling_summary") or "").strip()
      if summary:
        lines.extend(["", summary[-2600:]])
      return "\n".join(lines)[:3600]
  if not store or not chat_session_id or not hasattr(store, "get_memory_chat_session_state"):
    return ""
  if chat_topic_id:
    try:
      state = store.get_memory_chat_session_state(
        user,
        project_id=project_id,
        chat_session_id=chat_session_id,
        chat_topic_id=chat_topic_id,
      )
    except TypeError:
      state = store.get_memory_chat_session_state(
        user,
        chat_session_id=chat_session_id,
        chat_topic_id=chat_topic_id,
      )
  else:
    try:
      state = store.get_memory_chat_session_state(
        user,
        project_id=project_id,
        chat_session_id=chat_session_id,
      )
    except TypeError:
      state = store.get_memory_chat_session_state(user, chat_session_id=chat_session_id)
  if not state:
    return ""
  lines = [
    "Chat session continuity memory (this chat session only — not other chats or users):",
    f"- Updates in this session: {state.get('update_count', 0)}",
  ]
  preview = state.get("last_preview_status")
  if preview:
    lines.append(f"- Last preview: {preview}")
  error = state.get("last_error_category")
  if error:
    lines.append(f"- Last error category: {error}")
  paths = state.get("last_changed_paths_json") or []
  if isinstance(paths, list) and paths:
    lines.append(f"- Recently changed: {', '.join(str(p) for p in paths[:12])}")
  summary = str(state.get("rolling_summary") or "").strip()
  if summary:
    lines.extend(["", summary[-2200:]])
  return "\n".join(lines)[:3200]


def build_platform_learning_context_block(
  store: Any,
  *,
  prompt: str,
  domain: str | None = None,
  modules: list[str] | None = None,
  limit: int = 3,
  ideology_only: bool = False,
) -> str:
  patterns = select_platform_patterns_for_prompt(
    store,
    prompt=prompt,
    domain=domain,
    modules=modules,
    limit=limit,
    prefer_successful=ideology_only,
  )
  if not patterns:
    return ""
  header = (
    "Platform build patterns (ideology only — no code, folders, or chat from other projects):"
    if ideology_only
    else "Cross-project platform learning (anonymized site update/error patterns only — no chat or user conversations):"
  )
  lines = [header]
  min_source_count = platform_pattern_min_source_count()
  for item in patterns:
    if not isinstance(item, dict):
      continue
    source_count = int(item.get("source_count") or 0)
    if not platform_pattern_injection_allowed(item, min_source_count=min_source_count):
      continue
    tier = platform_pattern_promotion_status(item).replace("_", " ")
    title = str(item.get("title") or "")
    situation = str(item.get("situation") or "").strip()
    improved = str(item.get("improved_behavior") or "").strip()
    avoid = str(item.get("avoid") or "").strip()
    lines.append(
      f"[{item.get('domain')}/{item.get('module')}/{item.get('pattern_type')}] "
      f"{title} ({tier}; seen {source_count}x)"
    )
    if situation and not ideology_only:
      lines.append(situation[:400])
    if improved:
      lines.append(f"Do: {improved[:400]}")
    if avoid:
      lines.append(f"Avoid: {avoid[:400]}")
  return "\n\n".join(lines)[:2800] if len(lines) > 1 else ""


MIN_PREFERENCE_CONFIDENCE = 0.6
_SKIPPED_PREFERENCE_DURABILITY = {"ephemeral", "temporary", "session"}


def build_user_preferences_context_block(
  store: Any,
  user: Any,
  *,
  prompt: str = "",
  limit: int = 8,
) -> str:
  if not store or user is None or not hasattr(store, "list_memory_preferences"):
    return ""
  preferences = store.list_memory_preferences(user, limit=max(1, min(limit, 20)))
  if not preferences:
    return ""
  try:
    from .correction_learning import correction_preference_applies
  except ImportError:
    from agents.memory.correction_learning import correction_preference_applies

  lines = [
    "Learned user requirements (apply across chats and projects for this user):",
    "Use only relevant lessons. Explicit requirements in the current request always override memory.",
  ]
  for item in preferences:
    if not isinstance(item, dict):
      continue
    confidence = float(item.get("confidence") or 0)
    if confidence < MIN_PREFERENCE_CONFIDENCE:
      continue
    durability = str(item.get("durability") or "long_term").strip().lower()
    if durability in _SKIPPED_PREFERENCE_DURABILITY:
      continue
    category = str(item.get("category") or "general").strip()
    preference = str(item.get("preference") or "").strip()
    if not preference:
      continue
    if not correction_preference_applies(item, prompt):
      continue
    polarity = str(item.get("polarity") or "positive").strip().lower()
    prefix = "Prefer" if polarity != "negative" else "Avoid"
    lines.append(f"- [{category}] {prefix}: {preference[:240]}")
  return "\n".join(lines)[:1400] if len(lines) > 2 else ""


def build_unified_memory_context_block(
  store: Any,
  user: Any,
  *,
  project_id: str,
  prompt: str,
  chat_session_id: str | None = None,
  project_name: str = "",
  files: list[dict[str, Any]] | None = None,
  episodic_limit: int = 4,
  ideology_only: bool = False,
  include_session_state: bool = True,
  include_episodic: bool = True,
  chat_topic_id: str | None = None,
) -> str:
  blocks: list[str] = []
  source_files = meaningful_project_source_files(files) if ideology_only else (files or [])
  domain = infer_domain(prompt=prompt, project_name=project_name, files=source_files)
  modules = infer_modules(prompt=prompt)

  if ideology_only:
    preferences_block = build_user_preferences_context_block(store, user, prompt=prompt)
    if preferences_block:
      blocks.append(preferences_block)
    try:
      from .correction_learning import build_platform_correction_context_block
    except ImportError:
      from agents.memory.correction_learning import build_platform_correction_context_block
    correction_block = build_platform_correction_context_block(
      store,
      prompt=prompt,
      min_source_count=1,
      limit=3,
    )
    if correction_block:
      blocks.append(correction_block)
    platform_block = build_platform_learning_context_block(
      store,
      prompt=prompt,
      domain=domain,
      modules=modules,
      limit=3,
      ideology_only=True,
    )
    if platform_block:
      blocks.append(platform_block)
    if not blocks:
      blocks.append(
        "Greenfield project: no existing code in this workspace. "
        "Do not assume src/pages, src/components, or files from other projects exist. "
        "Scaffold a fresh Vite + React project from the user request."
      )
    return "\n\n".join(blocks)[:7200]

  project_ui_matches = select_project_ui_knowledge(
    prompt=prompt,
    files=source_files,
    store=store,
    user=user,
    project_id=project_id,
    limit=6,
  )
  project_ui_block = build_project_ui_knowledge_context(
    project_ui_matches,
    max_chars=3200,
  )
  if project_ui_block:
    blocks.append(project_ui_block)

  if not chat_session_id:
    return "\n\n".join(blocks)[:7200]

  if include_session_state:
    session_block = build_session_memory_context_block(
      store,
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
    )
    if session_block:
      blocks.append(session_block)

  preferences_block = build_user_preferences_context_block(store, user, prompt=prompt)
  if preferences_block:
    blocks.append(preferences_block)

  if include_episodic:
    episodic = select_episodic_memories_for_prompt(
      store,
      user,
      project_id=project_id,
      prompt=prompt,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      limit=episodic_limit,
    )
    episodic_block = build_episodic_context_block(
      episodic,
      prompt=prompt,
      already_ranked=True,
    )
    if episodic_block:
      blocks.append(episodic_block)

  platform_block = build_platform_learning_context_block(
    store,
    prompt=prompt,
    domain=domain,
    modules=modules,
    limit=3,
  )
  if platform_block:
    blocks.append(platform_block)

  try:
    from .correction_learning import build_platform_correction_context_block
  except ImportError:
    from agents.memory.correction_learning import build_platform_correction_context_block
  correction_block = build_platform_correction_context_block(
    store,
    prompt=prompt,
    min_source_count=1,
    limit=3,
  )
  if correction_block:
    blocks.append(correction_block)

  if not blocks:
    return ""
  return "\n\n".join(dedupe_memory_blocks(blocks))[:7200]


def build_scope_memory_context_block(
  store: Any,
  user: Any,
  *,
  project_id: str,
  prompt: str,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  files: list[dict[str, Any]] | None = None,
  episodic_limit: int = 4,
  ideology_only: bool = False,
) -> str:
  """Unified memory for ScopeEngine — retrieval keyed on the latest user turn only."""
  try:
    from ..chat_history import primary_update_prompt, should_include_session_memory_for_prompt
  except ImportError:
    from agents.chat_history import primary_update_prompt, should_include_session_memory_for_prompt
  scope_prompt = primary_update_prompt(prompt)
  include_session_memory = should_include_session_memory_for_prompt(scope_prompt)
  return build_unified_memory_context_block(
    store,
    user,
    project_id=project_id,
    prompt=scope_prompt,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
    project_name=project_name,
    files=files,
    episodic_limit=episodic_limit,
    ideology_only=ideology_only,
    include_session_state=include_session_memory,
    include_episodic=include_session_memory,
  )


def _load_project_chat_messages(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str | None,
  chat_topic_id: str | None = None,
  limit: int = 80,
) -> list[dict[str, Any]]:
  if not store or user is None or not chat_session_id or not hasattr(store, "list_project_chat_messages"):
    return []
  try:
    return list(
      store.list_project_chat_messages(
        project_id,
        user,
        limit=limit,
        chat_session_id=chat_session_id,
        chat_topic_id=chat_topic_id,
      )
      or []
    )
  except TypeError as exc:
    if "chat_topic_id" not in str(exc) and "chat_session_id" not in str(exc):
      return []
    try:
      try:
        rows = list(
          store.list_project_chat_messages(
            project_id,
            user,
            limit=limit,
            chat_session_id=chat_session_id,
          )
          or []
        )
      except TypeError:
        rows = list(store.list_project_chat_messages(project_id, user, limit=limit) or [])
      try:
        from .topic_clustering import filter_chat_messages_for_topic
      except ImportError:
        from agents.memory.topic_clustering import filter_chat_messages_for_topic
      return filter_chat_messages_for_topic(rows, chat_topic_id=chat_topic_id, prompt="")
    except Exception:
      return []
  except Exception:
    return []


def build_agent_flow_memory_block(
  store: Any,
  user: Any,
  *,
  project_id: str,
  prompt: str,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  files: list[dict[str, Any]] | None = None,
  chat_messages: list[dict[str, Any]] | None = None,
  enhancement_context: str = "",
  error_context: str = "",
  episodic_limit: int = 4,
  ideology_only: bool = False,
) -> str:
  """Unified agent-flow memory: session/episodic + chat continuity + error/enhancement signals."""
  try:
    from ..chat_history import (
      build_compact_chat_continuity_block,
      primary_update_prompt,
      should_include_chat_continuity_for_prompt,
      should_include_error_context_for_prompt,
      should_include_session_memory_for_prompt,
    )
  except ImportError:
    from agents.chat_history import (
      build_compact_chat_continuity_block,
      primary_update_prompt,
      should_include_chat_continuity_for_prompt,
      should_include_error_context_for_prompt,
      should_include_session_memory_for_prompt,
    )

  scope_prompt = primary_update_prompt(prompt)
  include_session_state = should_include_session_memory_for_prompt(scope_prompt)
  include_chat_continuity = should_include_chat_continuity_for_prompt(scope_prompt)
  include_error_context = should_include_error_context_for_prompt(scope_prompt)
  unified = build_unified_memory_context_block(
    store,
    user,
    project_id=project_id,
    prompt=scope_prompt,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
    project_name=project_name,
    files=files,
    episodic_limit=episodic_limit,
    ideology_only=ideology_only,
    include_session_state=include_session_state,
    include_episodic=include_session_state,
  )
  messages = list(chat_messages or []) if include_chat_continuity else []
  if include_chat_continuity and not messages:
    messages = _load_project_chat_messages(
      store,
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
    )
  chat_block = ""
  if include_chat_continuity or include_error_context:
    chat_block = build_compact_chat_continuity_block(
      messages,
      enhancement_context=enhancement_context if include_chat_continuity else "",
      error_context=error_context if include_error_context else "",
    )
  blocks = [block for block in (unified, chat_block) if block and block.strip()]
  if not blocks:
    return ""
  return "\n\n".join(dedupe_memory_blocks(blocks))[:9600]
