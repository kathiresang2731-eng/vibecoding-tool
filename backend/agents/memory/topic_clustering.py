"""Topic clustering inside a single chat session.

This layer does not decide the final Worktual route by itself. It narrows
memory/history retrieval so unrelated tasks in one chat session do not bleed
into each other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

try:
  from ..prompt_context import current_user_prompt
  from .session_monitor import infer_modules
except ImportError:
  from agents.prompt_context import current_user_prompt
  from agents.memory.session_monitor import infer_modules

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.IGNORECASE)
TOPIC_REUSE_THRESHOLD = 0.34
CONTINUATION_REUSE_THRESHOLD = 0.12
SUPPORTED_INTENT_FAMILIES = {
  "feature_update",
  "general",
  "large_project",
  "read_only",
  "simple_code",
  "website_generation",
  "website_update",
  "web_search",
}


@dataclass(frozen=True)
class TopicSeed:
  label: str
  intent_family: str
  memory_scope: str
  tags: list[str]
  related_paths: list[str]
  related_modules: list[str]


def _text(value: Any) -> str:
  return str(value or "").strip()


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(row, dict):
    return {}
  for key in ("metadata_json", "metadata"):
    value = row.get(key)
    if isinstance(value, dict):
      return value
  return {}


def tokens_for_topic(text: str) -> set[str]:
  tokens = {
    token.strip("_-").lower()
    for token in TOKEN_RE.findall(_text(text).lower())
    if len(token.strip("_-")) >= 2
  }
  return {token for token in tokens if token}


def _jaccard(left: set[str], right: set[str]) -> float:
  if not left or not right:
    return 0.0
  return len(left & right) / max(len(left | right), 1)


def _looks_like_continuation(prompt: str) -> bool:
  """Fallback-only minimal reply detector; LLM resolution owns normal continuation."""
  words = TOKEN_RE.findall(_text(prompt).lower())
  if 0 < len(words) <= 3:
    return True
  try:
    from ..chat_history import is_referential_followup_prompt
  except ImportError:
    from agents.chat_history import is_referential_followup_prompt
  return is_referential_followup_prompt(prompt)


def _intent_family_from_route(adaptive_route: dict[str, Any] | None, routing_result: dict[str, Any] | None, prompt: str) -> str:
  route = _text((adaptive_route or {}).get("route")).lower()
  intent = _text((routing_result or {}).get("intent")).lower()
  if route == "small_code" or intent == "simple_code":
    return "simple_code"
  if intent == "web_search":
    return "web_search"
  if intent in {"question", "general_query", "project_info"} or route == "conversation":
    return "read_only"
  if intent == "website_generation" or route == "full_generation":
    return "website_generation"
  if route in {"feature_update", "large_project"}:
    return route
  if intent == "website_update" or route == "targeted_update":
    return "website_update"
  if prompt.strip().endswith("?"):
    return "read_only"
  return intent or route or "general"


def _path_tokens(path: str) -> set[str]:
  normalized = _text(path).lower().replace("\\", "/")
  base = normalized.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  parts = set(TOKEN_RE.findall(normalized)) | set(TOKEN_RE.findall(base))
  expanded: set[str] = set()
  for item in parts:
    expanded.add(item)
    expanded.update(part for part in re.split(r"[-_]+", item) if len(part) >= 2)
  return {item for item in expanded if item}


def _related_paths_for_prompt(prompt: str, project_files: list[dict[str, Any]] | None) -> list[str]:
  prompt_tokens = tokens_for_topic(prompt)
  prompt_lower = _text(prompt).lower()
  scored: list[tuple[float, str]] = []
  for item in project_files or []:
    if not isinstance(item, dict):
      continue
    path = _text(item.get("path")).replace("\\", "/")
    if not path:
      continue
    lowered = path.lower()
    if any(part in lowered.split("/") for part in {"node_modules", "dist", "build", ".git"}):
      continue
    path_token_set = _path_tokens(path)
    overlap = _jaccard(prompt_tokens, path_token_set)
    base = lowered.rsplit("/", 1)[-1]
    exact = 0.35 if lowered in prompt_lower or base in prompt_lower else 0.0
    if overlap or exact:
      scored.append((overlap + exact, path))
  scored.sort(key=lambda item: item[0], reverse=True)
  return [path for _score, path in scored[:12]]


def build_topic_seed(
  *,
  prompt: str,
  project_files: list[dict[str, Any]] | None = None,
  adaptive_route: dict[str, Any] | None = None,
  routing_result: dict[str, Any] | None = None,
) -> TopicSeed:
  clean_prompt = current_user_prompt(prompt).strip() or _text(prompt)
  prompt_tokens = sorted(tokens_for_topic(clean_prompt))
  intent_family = _intent_family_from_route(adaptive_route, routing_result, clean_prompt)
  related_paths = _related_paths_for_prompt(clean_prompt, project_files)
  modules = infer_modules(prompt=clean_prompt, changed_paths=related_paths)
  label_tokens = [token for token in prompt_tokens if token not in {"will", "should", "like"}][:5]
  if modules:
    label = " / ".join(modules[:2])
  elif label_tokens:
    label = " ".join(label_tokens[:4]).replace("_", " ").title()
  else:
    label = intent_family.replace("_", " ").title()
  return TopicSeed(
    label=label[:160],
    intent_family=intent_family,
    memory_scope="topic",
    tags=prompt_tokens[:24],
    related_paths=related_paths,
    related_modules=modules[:12],
  )


def _topic_text(topic: dict[str, Any]) -> str:
  metadata = _metadata(topic)
  paths = topic.get("related_paths_json") if isinstance(topic.get("related_paths_json"), list) else []
  modules = topic.get("related_modules_json") if isinstance(topic.get("related_modules_json"), list) else []
  return " ".join(
    [
      _text(topic.get("label")),
      _text(topic.get("intent_family")),
      _text(topic.get("topic_tags")),
      _text(topic.get("rolling_summary")),
      _text(topic.get("last_prompt")),
      " ".join(str(item) for item in paths[:12]),
      " ".join(str(item) for item in modules[:12]),
      _text(metadata.get("last_resolution_reason")),
    ]
  )


def score_topic_relevance(topic: dict[str, Any], seed: TopicSeed, prompt: str) -> float:
  prompt_tokens = tokens_for_topic(prompt) | set(seed.tags)
  topic_tokens = tokens_for_topic(_topic_text(topic))
  semantic = _jaccard(prompt_tokens, topic_tokens)
  intent_bonus = 0.16 if _text(topic.get("intent_family")).lower() == seed.intent_family else 0.0
  topic_paths = {
    str(path)
    for path in (topic.get("related_paths_json") if isinstance(topic.get("related_paths_json"), list) else [])
  }
  path_overlap = len(topic_paths & set(seed.related_paths)) / max(len(set(seed.related_paths) or topic_paths), 1) if (topic_paths or seed.related_paths) else 0.0
  module_overlap = 0.0
  topic_modules = {
    str(module).lower()
    for module in (topic.get("related_modules_json") if isinstance(topic.get("related_modules_json"), list) else [])
  }
  if topic_modules or seed.related_modules:
    module_overlap = len(topic_modules & {module.lower() for module in seed.related_modules}) / max(len(topic_modules | {module.lower() for module in seed.related_modules}), 1)
  return min(1.0, semantic * 0.58 + intent_bonus + path_overlap * 0.18 + module_overlap * 0.18)


def _confidence(value: Any, *, default: float = 0.62) -> float:
  try:
    parsed = float(value)
  except (TypeError, ValueError):
    parsed = default
  return max(0.0, min(0.99, parsed))


def _safe_list(value: Any, *, limit: int = 24) -> list[str]:
  if not isinstance(value, list):
    return []
  result: list[str] = []
  for item in value:
    text = _text(item)
    if not text or text in result:
      continue
    result.append(text[:240])
    if len(result) >= limit:
      break
  return result


def _topic_candidates_for_llm(topics: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
  candidates: list[dict[str, Any]] = []
  for topic in topics[:limit]:
    if not isinstance(topic, dict):
      continue
    candidates.append(
      {
        "id": topic.get("id"),
        "label": topic.get("label"),
        "intent_family": topic.get("intent_family"),
        "rolling_summary": _text(topic.get("rolling_summary"))[-1200:],
        "last_prompt": _text(topic.get("last_prompt"))[-500:],
        "related_paths": topic.get("related_paths_json") if isinstance(topic.get("related_paths_json"), list) else [],
        "related_modules": topic.get("related_modules_json") if isinstance(topic.get("related_modules_json"), list) else [],
        "updated_at": _text(topic.get("updated_at")),
      }
    )
  return candidates


def _project_paths_for_llm(project_files: list[dict[str, Any]] | None, *, limit: int = 120) -> list[str]:
  paths: list[str] = []
  for item in project_files or []:
    if not isinstance(item, dict):
      continue
    path = _text(item.get("path")).replace("\\", "/")
    if not path or path in paths:
      continue
    if any(part in path.lower().split("/") for part in {"node_modules", "dist", "build", ".git"}):
      continue
    paths.append(path)
    if len(paths) >= limit:
      break
  return paths


def _llm_topic_resolution(
  *,
  llm_provider: Any,
  prompt: str,
  seed: TopicSeed,
  topics: list[dict[str, Any]],
  project_files: list[dict[str, Any]] | None,
  adaptive_route: dict[str, Any] | None,
  routing_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
  if llm_provider is None or not hasattr(llm_provider, "generate_json"):
    return None
  topic_candidates = _topic_candidates_for_llm(topics)
  available_paths = _project_paths_for_llm(project_files)
  system_instruction = (
    "You are Worktual's chat topic memory resolver. Decide whether the current user turn continues "
    "one existing topic in this same chat session or starts a new topic. Use the full meaning of the "
    "request, prior topic summaries, related files/modules, and route signals. Do not classify by "
    "isolated keywords. If the current prompt is a short confirmation, reuse the most likely active "
    "topic only when the prior topic context makes that safe. Return strict JSON only."
  )
  user_prompt = (
    "Current user prompt:\n"
    f"{current_user_prompt(prompt).strip() or _text(prompt)}\n\n"
    f"Route signal: {adaptive_route or {}}\n"
    f"Routing result signal: {routing_result or {}}\n"
    f"Fallback seed (only for reference, not a rule): {seed.__dict__}\n\n"
    f"Existing active topics:\n{topic_candidates}\n\n"
    f"Current project file paths:\n{available_paths}\n\n"
    "Return JSON with keys: topic_action ('reuse' or 'new'), chat_topic_id (existing id when reusing), "
    "label, intent_family, memory_scope, confidence, reason, related_paths, related_modules, topic_tags."
  )
  try:
    payload = llm_provider.generate_json(
      user_prompt,
      system_instruction=system_instruction,
      trace_label="memory_topic_resolver",
      max_output_tokens=1200,
    )
  except Exception:
    return None
  if not isinstance(payload, dict):
    return None
  action = _text(payload.get("topic_action")).lower()
  if action not in {"reuse", "new"}:
    return None
  topic_ids = {str(topic.get("id") or "") for topic in topics if isinstance(topic, dict)}
  selected_topic_id = _text(payload.get("chat_topic_id"))
  if action == "reuse" and selected_topic_id not in topic_ids:
    return None
  raw_intent = _text(payload.get("intent_family")).lower().replace("-", "_")
  intent_family = raw_intent if raw_intent in SUPPORTED_INTENT_FAMILIES else seed.intent_family
  available_path_set = set(available_paths)
  related_paths = [path for path in _safe_list(payload.get("related_paths"), limit=40) if not available_path_set or path in available_path_set]
  return {
    "topic_action": action,
    "chat_topic_id": selected_topic_id if action == "reuse" else None,
    "label": _text(payload.get("label"))[:160] or seed.label,
    "intent_family": intent_family,
    "memory_scope": _text(payload.get("memory_scope"))[:80] or seed.memory_scope,
    "confidence": _confidence(payload.get("confidence")),
    "reason": _text(payload.get("reason"))[:600] or "LLM selected topic memory scope",
    "related_paths": related_paths or seed.related_paths,
    "related_modules": _safe_list(payload.get("related_modules"), limit=24) or seed.related_modules,
    "topic_tags": " ".join(_safe_list(payload.get("topic_tags"), limit=32)) or " ".join(seed.tags),
    "source": "llm_topic_resolver",
  }


def _merge_unique(left: list[Any] | None, right: list[Any] | None, *, limit: int = 40) -> list[str]:
  seen: set[str] = set()
  merged: list[str] = []
  for value in list(left or []) + list(right or []):
    text = _text(value)
    if not text or text in seen:
      continue
    seen.add(text)
    merged.append(text)
    if len(merged) >= limit:
      break
  return merged


def _topic_summary_for_prompt(topic: dict[str, Any], prompt: str, outcome: str = "selected", changed_paths: list[str] | None = None) -> str:
  prior = _text(topic.get("rolling_summary"))
  lines = [prior] if prior else []
  request = current_user_prompt(prompt).strip() or _text(prompt)
  if request:
    lines.append(f"Latest request ({outcome}): {request[:420]}")
  if changed_paths:
    lines.append(f"Changed paths: {', '.join(changed_paths[:12])}")
  return "\n".join(lines)[-6000:]


def resolve_chat_topic(
  *,
  store: Any,
  user: Any,
  project_id: str,
  chat_session_id: str | None,
  prompt: str,
  project_files: list[dict[str, Any]] | None = None,
  adaptive_route: dict[str, Any] | None = None,
  routing_result: dict[str, Any] | None = None,
  llm_provider: Any | None = None,
  emit_progress: Any | None = None,
) -> dict[str, Any]:
  if not chat_session_id or store is None or user is None:
    return {"status": "skipped", "reason": "missing_session", "chat_topic_id": None}
  if not hasattr(store, "list_memory_chat_topics") or not hasattr(store, "create_memory_chat_topic"):
    return {"status": "skipped", "reason": "topic_store_unavailable", "chat_topic_id": None}

  seed = build_topic_seed(
    prompt=prompt,
    project_files=project_files,
    adaptive_route=adaptive_route,
    routing_result=routing_result,
  )
  try:
    topics = store.list_memory_chat_topics(
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      limit=16,
      status="active",
    )
  except Exception as exc:
    return {"status": "skipped", "reason": "topic_list_failed", "error": str(exc)[:240], "chat_topic_id": None}

  llm_decision = _llm_topic_resolution(
    llm_provider=llm_provider,
    prompt=prompt,
    seed=seed,
    topics=topics,
    project_files=project_files,
    adaptive_route=adaptive_route,
    routing_result=routing_result,
  )
  scored = [(score_topic_relevance(topic, seed, prompt), topic) for topic in topics if isinstance(topic, dict)]
  scored.sort(key=lambda item: (item[0], _text(item[1].get("updated_at"))), reverse=True)
  best_score, best_topic = scored[0] if scored else (0.0, None)
  if llm_decision:
    action = str(llm_decision.get("topic_action") or "new")
    selected_topic_id = str(llm_decision.get("chat_topic_id") or "")
    best_topic = next((topic for topic in topics if str(topic.get("id") or "") == selected_topic_id), None) if action == "reuse" else None
    reason = str(llm_decision.get("reason") or "LLM selected topic memory scope")
  else:
    continuation = _looks_like_continuation(prompt)
    threshold = CONTINUATION_REUSE_THRESHOLD if continuation else TOPIC_REUSE_THRESHOLD
    action = "reuse" if best_topic and (continuation or best_score >= threshold) else "new"
    reason = (
      "fallback minimal reply reused most recent matching active topic"
      if action == "reuse" and continuation
      else "fallback semantic/metadata match reused existing topic"
      if action == "reuse"
      else "fallback found no matching active topic"
    )

  try:
    if action == "reuse" and best_topic:
      llm_values = llm_decision or {}
      existing_tags = str(best_topic.get("topic_tags") or "").split()
      topic = store.update_memory_chat_topic(
        user,
        chat_topic_id=str(best_topic.get("id") or ""),
        label=str(llm_values.get("label") or best_topic.get("label") or seed.label),
        intent_family=str(llm_values.get("intent_family") or best_topic.get("intent_family") or seed.intent_family),
        memory_scope=str(llm_values.get("memory_scope") or best_topic.get("memory_scope") or seed.memory_scope),
        topic_tags=str(llm_values.get("topic_tags") or " ".join(_merge_unique(existing_tags, seed.tags, limit=32))),
        rolling_summary=_topic_summary_for_prompt(best_topic, prompt, outcome="selected"),
        related_paths=_merge_unique(best_topic.get("related_paths_json") if isinstance(best_topic.get("related_paths_json"), list) else [], llm_values.get("related_paths") or seed.related_paths, limit=40),
        related_modules=_merge_unique(best_topic.get("related_modules_json") if isinstance(best_topic.get("related_modules_json"), list) else [], llm_values.get("related_modules") or seed.related_modules, limit=24),
        last_prompt=current_user_prompt(prompt).strip()[:1200],
        confidence=max(float(best_topic.get("confidence") or 0.0), _confidence(llm_values.get("confidence"), default=best_score), best_score),
        metadata={"last_resolution_reason": reason, "last_resolution_score": round(best_score, 4), "topic_resolution_source": "llm" if llm_decision else "fallback"},
      ) or best_topic
    else:
      llm_values = llm_decision or {}
      topic = store.create_memory_chat_topic(
        user,
        project_id=project_id,
        chat_session_id=chat_session_id,
        label=str(llm_values.get("label") or seed.label),
        intent_family=str(llm_values.get("intent_family") or seed.intent_family),
        memory_scope=str(llm_values.get("memory_scope") or seed.memory_scope),
        topic_tags=str(llm_values.get("topic_tags") or " ".join(seed.tags)),
        rolling_summary=f"Topic started from request: {(current_user_prompt(prompt).strip() or _text(prompt))[:420]}",
        related_paths=llm_values.get("related_paths") or seed.related_paths,
        related_modules=llm_values.get("related_modules") or seed.related_modules,
        last_prompt=current_user_prompt(prompt).strip()[:1200],
        confidence=max(best_score, _confidence(llm_values.get("confidence"), default=0.62)),
        metadata={"last_resolution_reason": reason, "last_resolution_score": round(best_score, 4), "topic_resolution_source": "llm" if llm_decision else "fallback"},
      )
  except Exception as exc:
    return {"status": "skipped", "reason": "topic_write_failed", "error": str(exc)[:240], "chat_topic_id": None}

  result = {
    "status": "selected",
    "chat_topic_id": topic.get("id"),
    "topic_action": action,
    "label": topic.get("label") or seed.label,
    "intent_family": topic.get("intent_family") or seed.intent_family,
    "memory_scope": topic.get("memory_scope") or seed.memory_scope,
    "confidence": float(topic.get("confidence") or max(best_score, 0.62)),
    "reason": reason,
    "score": round(best_score, 4),
    "resolution_source": "llm" if llm_decision else "fallback",
    "related_paths": topic.get("related_paths_json") if isinstance(topic.get("related_paths_json"), list) else seed.related_paths,
    "related_modules": topic.get("related_modules_json") if isinstance(topic.get("related_modules_json"), list) else seed.related_modules,
  }
  if emit_progress is not None:
    try:
      emit_progress(
        "memory.topic.selected",
        f"Selected chat topic: {result['label']}",
        status="completed",
        detail=result,
      )
    except Exception:
      pass
  return result


def chat_topic_id_from_message(message: dict[str, Any]) -> str:
  if not isinstance(message, dict):
    return ""
  direct = _text(message.get("chat_topic_id"))
  if direct:
    return direct
  return _text(_metadata(message).get("chat_topic_id"))


def filter_chat_messages_for_topic(
  messages: list[dict[str, Any]] | None,
  *,
  chat_topic_id: str | None,
  prompt: str = "",
  topic: dict[str, Any] | None = None,
  max_messages: int = 80,
) -> list[dict[str, Any]]:
  rows = [item for item in (messages or []) if isinstance(item, dict)]
  topic_id = _text(chat_topic_id)
  if not topic_id:
    return rows[-max_messages:]
  matched = [item for item in rows if chat_topic_id_from_message(item) == topic_id]
  if matched:
    return matched[-max_messages:]
  if any(chat_topic_id_from_message(item) for item in rows):
    return []

  # Legacy rows did not have chat_topic_id. Keep only semantically related rows
  # instead of injecting the entire old session into the new task.
  anchor = " ".join([prompt, _topic_text(topic or {})])
  anchor_tokens = tokens_for_topic(anchor)
  if not anchor_tokens:
    return rows[-6:] if _looks_like_continuation(prompt) else []
  relevant: list[dict[str, Any]] = []
  for item in rows:
    metadata = _metadata(item)
    content = _text(metadata.get("display_content") or item.get("content"))
    if not content:
      continue
    if _jaccard(anchor_tokens, tokens_for_topic(content)) >= 0.08:
      relevant.append(item)
  if relevant:
    return relevant[-max_messages:]
  return rows[-6:] if _looks_like_continuation(prompt) else []


def update_chat_topic_after_run(
  *,
  store: Any,
  user: Any,
  chat_topic_id: str | None,
  prompt: str,
  outcome: str,
  changed_paths: list[str] | None = None,
  metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
  if not chat_topic_id or store is None or user is None or not hasattr(store, "get_memory_chat_topic"):
    return None
  topic = store.get_memory_chat_topic(user, chat_topic_id=chat_topic_id)
  if not topic or not hasattr(store, "update_memory_chat_topic"):
    return topic
  existing_paths = topic.get("related_paths_json") if isinstance(topic.get("related_paths_json"), list) else []
  return store.update_memory_chat_topic(
    user,
    chat_topic_id=chat_topic_id,
    rolling_summary=_topic_summary_for_prompt(topic, prompt, outcome=outcome, changed_paths=changed_paths),
    related_paths=_merge_unique(existing_paths, changed_paths or [], limit=40),
    last_prompt=current_user_prompt(prompt).strip()[:1200],
    last_changed_paths=[str(path)[:240] for path in (changed_paths or [])[:40]],
    metadata=metadata or {},
  )
