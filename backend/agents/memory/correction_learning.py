from __future__ import annotations

import hashlib
import re
from typing import Any

try:
  from .platform_learning import platform_pattern_injection_allowed
  from .learning_events import confidence_tier_for_evidence
except ImportError:
  from agents.memory.platform_learning import platform_pattern_injection_allowed
  from agents.memory.learning_events import confidence_tier_for_evidence


_LANGUAGES = (
  "python",
  "java",
  "javascript",
  "typescript",
  "c++",
  "c#",
  "go",
  "rust",
  "php",
  "ruby",
  "kotlin",
  "swift",
)
_LANGUAGE_PATTERN = re.compile(
  r"\b(" + "|".join(re.escape(item) for item in _LANGUAGES) + r")\b",
  re.IGNORECASE,
)
_SIMPLIFICATION_MARKERS = re.compile(
  r"\b(?:simpl[a-z]*|simplyfied|beginner[- ]?friendly|easy(?:\s+to\s+understand)?|"
  r"less\s+complex|clean(?:er)?|minimal|short(?:er)?)\b",
  re.IGNORECASE,
)
_NO_COMMENTS_MARKERS = re.compile(
  r"\b(?:remove\s+(?:the\s+)?comments?|without comments?|no comments?|comment[- ]?free)\b",
  re.IGNORECASE,
)
_INPUT_VALIDATION_MARKERS = re.compile(
  r"\b(?:input validation|validate (?:the )?input|invalid (?:number|input|value)|"
  r"error handling|handle invalid input|show a clear invalid|validation)\b",
  re.IGNORECASE,
)
_LOW_SIGNAL_USER_MESSAGE = re.compile(
  r"^\s*(?:hi|hello|hey|ok|okay|thanks|thank you|yes|no)\s*[.!?]*\s*$",
  re.IGNORECASE,
)
_TOPIC_PATTERNS = (
  re.compile(
    r"\b(?:python|java|javascript|typescript|c\+\+|c#|go|rust|php|ruby|kotlin|swift)\s+"
    r"(?:code|program)\s+(?:for|in|of|about)\s+(.+)$",
    re.IGNORECASE,
  ),
  re.compile(r"\b(?:code|program)\s+(?:for|of|about|to check)\s+(.+)$", re.IGNORECASE),
)
_TOPIC_STOP_PATTERN = re.compile(
  r"\s+(?:in|using|with)\s+(?:python|java|javascript|typescript|c\+\+|c#|go|rust|php|ruby|kotlin|swift)\b.*$",
  re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"[a-z0-9+#]{2,}")


def extract_turn_learning_preferences(
  messages: list[dict[str, Any]],
  *,
  fallback_language: str = "",
  changed_paths: list[str] | None = None,
  outcome: str = "",
  error_category: str | None = None,
) -> list[dict[str, Any]]:
  user_messages = [
    str(item.get("content") or "").strip()
    for item in messages
    if isinstance(item, dict)
    and str(item.get("role") or "").strip().lower() in {"user", "human"}
    and str(item.get("content") or "").strip()
  ]
  if not user_messages:
    return []

  current = user_messages[-1]
  if _LOW_SIGNAL_USER_MESSAGE.match(current):
    return []

  paths = changed_paths or []
  topic = _infer_topic(user_messages) or _infer_topic_from_paths(paths) or "general"
  language = _infer_language(user_messages) or _normalize_language(fallback_language) or _infer_language_from_paths(paths) or "general"
  if not topic and not language:
    return []

  preference = _build_turn_requirement_preference(
    topic=topic,
    language=language,
    latest_user_message=current,
    changed_paths=paths,
    outcome=outcome,
    error_category=error_category,
  )
  return [preference] if preference else []


def extract_correction_preferences(
  messages: list[dict[str, Any]],
  *,
  fallback_language: str = "",
  changed_paths: list[str] | None = None,
  outcome: str = "",
  error_category: str | None = None,
) -> list[dict[str, Any]]:
  """Backward-compatible wrapper for the broader turn-learning extractor."""
  return extract_turn_learning_preferences(
    messages,
    fallback_language=fallback_language,
    changed_paths=changed_paths,
    outcome=outcome,
    error_category=error_category,
  )


def _build_turn_requirement_preference(
  *,
  topic: str,
  language: str,
  latest_user_message: str,
  changed_paths: list[str],
  outcome: str,
  error_category: str | None,
) -> dict[str, Any] | None:
  function_count = _target_function_count(latest_user_message)
  wants_simplified = bool(_SIMPLIFICATION_MARKERS.search(latest_user_message))
  wants_no_comments = bool(_NO_COMMENTS_MARKERS.search(latest_user_message))
  wants_input_validation = bool(_INPUT_VALIDATION_MARKERS.search(latest_user_message))
  topic_label = topic.replace("_", " ")
  category = ""
  correction_kind = ""
  confidence = 0.82
  preference = ""
  requirement_summary = ""
  if function_count is not None:
    category = "code_structure"
    correction_kind = "function_count"
    confidence = 0.92
    requirement_summary = f"preserve a {function_count}-function structure when explicitly requested"
    preference = (
      f"If the current request for {language.title()} {topic_label} code explicitly asks for "
      f"{_number_label(function_count)} functions, preserve that structure instead of returning a different "
      "function count."
    )
  elif wants_simplified:
    category = "code_simplicity"
    correction_kind = "code_simplicity"
    confidence = 0.9
    requirement_summary = "simplify only when the current request explicitly asks for a simpler version"
    preference = (
      f"If the current request for {language.title()} {topic_label} code explicitly asks for a simplified or "
      "beginner-friendly version, keep the logic direct and avoid unnecessary complexity."
    )
  elif wants_no_comments:
    category = "code_style"
    correction_kind = "no_comments"
    confidence = 0.88
    requirement_summary = "remove comments only when the current request explicitly asks for comment-free code"
    preference = (
      f"If the current request for {language.title()} {topic_label} code explicitly asks for no comments, "
      "return comment-free code."
    )
  elif wants_input_validation:
    category = "code_quality"
    correction_kind = "input_validation"
    confidence = 0.87
    requirement_summary = "add input validation only when the current request explicitly asks for validation or invalid-input handling"
    preference = (
      f"If the current request for {language.title()} {topic_label} code explicitly asks for input validation "
      "or invalid-input handling, include validation and a clear failure message."
    )
  else:
    return None

  scope_keywords = sorted(
    {
      *_tokens(topic_label),
      *_tokens(requirement_summary),
      language.lower(),
    }
  )[:18]
  fingerprint = _fingerprint(
    correction_kind=correction_kind,
    topic=topic,
    language=language,
    value=_normalise_requirement_for_fingerprint(requirement_summary),
  )
  metadata = {
    "source": "turn_learning",
    "learning_kind": "turn_requirement",
    "correction_kind": correction_kind,
    "correction_fingerprint": fingerprint,
    "topic": topic,
    "language": language.lower(),
    "requirement_summary": requirement_summary,
    "scope_keywords": scope_keywords,
    "changed_paths": [str(path)[:240] for path in changed_paths[:8]],
    "outcome": str(outcome or "")[:80],
    "error_category": str(error_category or "")[:120],
    "current_request_overrides": True,
  }
  if function_count is not None:
    metadata["function_count"] = function_count
  if wants_simplified:
    metadata["simplicity_level"] = "simplified"
  return {
    "category": category,
    "preference": preference,
    "polarity": "positive",
    "confidence": confidence,
    "durability": "long_term",
    "reason": "Learned from the latest user requirement after a generation or update turn.",
    "metadata": metadata,
  }


def correction_preference_applies(row: dict[str, Any], prompt: str) -> bool:
  metadata = _metadata(row)
  if metadata.get("source") not in {
    "correction_learning",
    "turn_learning",
    "anonymized_requirement_correction",
    "anonymized_turn_learning",
  }:
    return True
  prompt_text = str(prompt or "").strip().lower()
  if not prompt_text:
    return False

  memory_language = str(metadata.get("language") or "").strip().lower()
  prompt_language = _language_from_text(prompt_text)
  if memory_language and prompt_language and memory_language != prompt_language:
    return False

  correction_kind = str(metadata.get("correction_kind") or metadata.get("learning_kind") or "").strip().lower()
  if correction_kind == "turn_requirement":
    return False
  if correction_kind == "function_count":
    expected = int(metadata.get("function_count") or 0)
    return expected > 0 and _target_function_count(prompt_text) == expected and _topic_matches_prompt(metadata, prompt_text)
  if correction_kind == "code_simplicity":
    return bool(_SIMPLIFICATION_MARKERS.search(prompt_text)) and _topic_matches_prompt(metadata, prompt_text)
  if correction_kind == "no_comments":
    return bool(_NO_COMMENTS_MARKERS.search(prompt_text)) and _topic_matches_prompt(metadata, prompt_text)
  if correction_kind == "input_validation":
    return bool(_INPUT_VALIDATION_MARKERS.search(prompt_text)) and _topic_matches_prompt(metadata, prompt_text)

  return _topic_matches_prompt(metadata, prompt_text)


def _topic_matches_prompt(metadata: dict[str, Any], prompt_text: str) -> bool:
  topic = str(metadata.get("topic") or "").replace("_", " ").strip().lower()
  if topic and topic in prompt_text:
    return True
  topic_tokens = _tokens(topic)
  prompt_tokens = _tokens(prompt_text)
  if topic_tokens and len(topic_tokens & prompt_tokens) >= max(1, min(2, len(topic_tokens))):
    return not memory_language or not prompt_language or memory_language == prompt_language

  scope_keywords = {
    str(item).strip().lower()
    for item in metadata.get("scope_keywords") or []
    if str(item).strip()
  }
  return len(scope_keywords & prompt_tokens) >= 3


def persist_turn_learning(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str,
  changed_paths: list[str] | None = None,
  outcome: str = "",
  error_category: str | None = None,
) -> dict[str, Any]:
  if not hasattr(store, "list_project_chat_messages"):
    return {"status": "skipped", "reason": "chat_history_unavailable"}
  messages = list(
    store.list_project_chat_messages(
      project_id,
      user,
      limit=24,
      chat_session_id=chat_session_id,
    )
    or []
  )
  corrections = extract_turn_learning_preferences(
    messages,
    fallback_language=_infer_language_from_paths(changed_paths or []),
    changed_paths=changed_paths,
    outcome=outcome,
    error_category=error_category,
  )
  if not corrections:
    return {"status": "skipped", "reason": "no_turn_learning"}

  saved_preferences = 0
  promoted_patterns = 0
  for correction in corrections:
    if hasattr(store, "upsert_memory_preference"):
      store.upsert_memory_preference(
        user,
        category=correction["category"],
        preference=correction["preference"],
        polarity=correction["polarity"],
        confidence=correction["confidence"],
        durability=correction["durability"],
        reason=correction["reason"],
        metadata=correction["metadata"],
      )
      saved_preferences += 1
    if _record_platform_correction(store, user, correction):
      promoted_patterns += 1

  return {
    "status": "stored",
    "preference_count": saved_preferences,
    "platform_evidence_count": promoted_patterns,
    "correction_fingerprints": [
      str(item["metadata"].get("correction_fingerprint") or "")
      for item in corrections
    ],
  }


def persist_turn_correction_learning(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str,
  changed_paths: list[str] | None = None,
  outcome: str = "",
  error_category: str | None = None,
) -> dict[str, Any]:
  """Backward-compatible wrapper for the broader turn-learning checkpoint."""
  return persist_turn_learning(
    store,
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    changed_paths=changed_paths,
    outcome=outcome,
    error_category=error_category,
  )


def select_platform_corrections_for_prompt(
  store: Any,
  *,
  prompt: str,
  limit: int = 3,
  min_source_count: int = 1,
) -> list[dict[str, Any]]:
  if store is None or not hasattr(store, "list_memory_platform_patterns"):
    return []
  rows = store.list_memory_platform_patterns(
    pattern_type="requirement_correction",
    limit=25,
  )
  selected = [
    row
    for row in rows
    if isinstance(row, dict)
    and platform_pattern_injection_allowed(row, min_source_count=min_source_count)
    and correction_preference_applies(row, prompt)
  ]
  selected.sort(
    key=lambda row: (
      int(row.get("source_count") or 0),
      float(row.get("confidence_score") or 0),
    ),
    reverse=True,
  )
  return selected[: max(1, min(limit, 8))]


def build_platform_correction_context_block(
  store: Any,
  *,
  prompt: str,
  min_source_count: int,
  limit: int = 3,
) -> str:
  rows = select_platform_corrections_for_prompt(
    store,
    prompt=prompt,
    limit=limit,
    min_source_count=min_source_count,
  )
  if not rows:
    return ""
  lines = [
    "Validated platform constraint lessons (anonymized; one source is soft guidance, repeated sources are stronger):",
    "Apply only when relevant; explicit requirements in the current request always override memory.",
  ]
  for row in rows:
    source_count = int(row.get("source_count") or 0)
    tier = confidence_tier_for_evidence(source_count).replace("_", " ")
    improved = _render_platform_correction_guidance(row)
    avoid = str(row.get("avoid") or "").strip()
    if improved:
      lines.append(f"- {tier}: {improved[:320]}")
    if avoid:
      lines.append(f"  Avoid: {avoid[:240]}")
  return "\n".join(lines)[:1600]


def _record_platform_correction(store: Any, user: Any, correction: dict[str, Any]) -> bool:
  if not hasattr(store, "upsert_memory_platform_pattern"):
    return False
  metadata = dict(correction.get("metadata") or {})
  correction_kind = str(metadata.get("correction_kind") or metadata.get("learning_kind") or "turn_requirement")
  if correction_kind == "turn_requirement":
    return False
  fingerprint = str(metadata.get("correction_fingerprint") or "")
  contributor_hash = hashlib.sha256(str(getattr(user, "id", "")).encode("utf-8")).hexdigest()[:16]
  existing_rows = (
    store.list_memory_platform_patterns(pattern_type="requirement_correction", limit=25)
    if hasattr(store, "list_memory_platform_patterns")
    else []
  )
  existing = next(
    (
      row
      for row in existing_rows
      if isinstance(row, dict)
      and str(_metadata(row).get("correction_fingerprint") or "") == fingerprint
    ),
    None,
  )
  existing_contributors = {
    str(item)
    for item in _metadata(existing or {}).get("contributor_hashes") or []
    if str(item)
  }
  if contributor_hash in existing_contributors:
    return False

  contributors = sorted({*existing_contributors, contributor_hash})
  tier = confidence_tier_for_evidence(len(contributors))
  topic = str(metadata.get("topic") or "general")
  language = str(metadata.get("language") or "general")
  requirement_summary = str(metadata.get("requirement_summary") or correction.get("preference") or "").strip()
  improved = _platform_correction_ideology(metadata, topic=topic, language=language)
  title_suffix = correction_kind
  summary = f"Corroborated requirement correction for {language} {topic.replace('_', ' ')} examples."
  situation = f"Language={language}; topic={topic}; correction={correction_kind}"
  avoid = ""
  if correction_kind == "function_count":
    function_count = int(metadata.get("function_count") or 0)
    title_suffix = f"{function_count}_functions"
    summary = (
      f"Corroborated code-structure correction for {language} {topic.replace('_', ' ')} examples."
    )
    situation = f"Language={language}; topic={topic}; constraint=function_count:{function_count}"
    avoid = (
      f"Do not default to a single-function {language.title()} solution for {topic.replace('_', ' ')}."
      if function_count == 2
      else ""
    )
  elif correction_kind == "code_simplicity":
    title_suffix = "simplified"
    summary = (
      f"Corroborated simplicity correction for {language} {topic.replace('_', ' ')} examples."
    )
    situation = f"Language={language}; topic={topic}; constraint=simplified_code"
    avoid = (
      f"Do not return an unnecessarily complex {language.title()} solution for "
      f"{topic.replace('_', ' ')} when the user asks for a simplified version."
    )
  elif correction_kind == "turn_requirement":
    title_suffix = hashlib.sha256(requirement_summary.encode("utf-8")).hexdigest()[:8]
    summary = (
      f"Corroborated turn requirement for {language} {topic.replace('_', ' ')} examples."
    )
    situation = f"Language={language}; topic={topic}; requirement={requirement_summary[:160]}"
  pattern = store.upsert_memory_platform_pattern(
    domain="code_generation",
    module=topic[:120],
    pattern_type="requirement_correction",
    memory_type="conversation_improvement",
    title=f"{correction.get('category') or 'requirement'} · {language}/{topic} · {title_suffix}"[:240],
    summary=summary,
    situation=situation,
    improved_behavior=improved,
    avoid=avoid,
    stack_tags=language,
    metadata={
      "source": "anonymized_requirement_correction",
      "learning_source": "anonymized_turn_learning",
      "anonymized": True,
      "contains_chat": False,
      "contains_paths": False,
      "evidence_count": len(contributors),
      "success_count": len(contributors),
      "failure_count": 0,
      "confidence_tier": tier,
      "promotion_status": tier,
      "correction_fingerprint": fingerprint,
      "correction_kind": metadata.get("correction_kind"),
      "learning_kind": metadata.get("learning_kind"),
      "topic": topic,
      "language": language,
      "function_count": metadata.get("function_count"),
      "simplicity_level": metadata.get("simplicity_level"),
      "requirement_summary": requirement_summary[:240],
      "scope_keywords": metadata.get("scope_keywords") or [],
      "contributor_hashes": contributors,
      "distinct_contributor_count": len(contributors),
      "current_request_overrides": True,
    },
  )
  if pattern and hasattr(store, "record_platform_pattern_event"):
    store.record_platform_pattern_event(
      pattern_id=str(pattern.get("id") or ""),
      domain="code_generation",
      module=topic[:120],
      pattern_type="requirement_correction",
      outcome="corrected",
    )
  return bool(pattern)


def _platform_correction_ideology(metadata: dict[str, Any], *, topic: str, language: str) -> str:
  topic_label = topic.replace("_", " ")
  correction_kind = str(metadata.get("correction_kind") or metadata.get("learning_kind") or "").strip().lower()
  if correction_kind == "function_count":
    function_count = int(metadata.get("function_count") or 0)
    if function_count > 0:
      return (
        f"When the current request for {language.title()} {topic_label} code explicitly asks for "
        f"{_number_label(function_count)} functions, preserve that structure."
      )
  if correction_kind == "code_simplicity":
    return (
      f"When the current request for {language.title()} {topic_label} code explicitly asks for a simplified or "
      "beginner-friendly version, keep the implementation direct and avoid unnecessary complexity."
    )
  if correction_kind == "no_comments":
    return (
      f"When the current request for {language.title()} {topic_label} code explicitly asks for no comments, "
      "return comment-free code."
    )
  if correction_kind == "input_validation":
    return (
      f"When the current request for {language.title()} {topic_label} code explicitly asks for input validation "
      "or invalid-input handling, include validation and a clear failure message."
    )
  return ""


def _render_platform_correction_guidance(row: dict[str, Any]) -> str:
  metadata = _metadata(row)
  topic = str(metadata.get("topic") or "")
  language = str(metadata.get("language") or "general")
  ideology = _platform_correction_ideology(metadata, topic=topic, language=language)
  if ideology:
    return ideology
  return str(row.get("improved_behavior") or "").strip()


def _summarize_latest_requirement(
  text: str,
  *,
  topic_label: str,
  function_count: int | None,
  wants_simplified: bool,
) -> str:
  if function_count is not None:
    return f"use {_number_label(function_count)} functions"
  if wants_simplified:
    return "provide a simplified beginner-friendly version with direct logic and minimal extra complexity"
  cleaned = str(text or "").strip()
  cleaned = re.sub(r"\s+", " ", cleaned)
  cleaned = re.sub(r"\bthis\s+code\b", f"the {topic_label} code", cleaned, flags=re.IGNORECASE)
  cleaned = re.sub(r"\bthis\b", f"the {topic_label}", cleaned, flags=re.IGNORECASE)
  cleaned = cleaned.strip(" .")
  if len(cleaned) > 180:
    cleaned = cleaned[:177].rstrip() + "..."
  return cleaned or "honor the latest user request"


def _normalise_requirement_for_fingerprint(text: str) -> str:
  normalized = str(text or "").strip().lower()
  normalized = re.sub(r"[^a-z0-9+# ]+", " ", normalized)
  normalized = re.sub(r"\s+", " ", normalized).strip()
  return normalized[:160]


def _target_function_count(text: str) -> int | None:
  normalized = str(text or "").lower()
  explicit = re.search(r"\b(\d+)\s+functions?\b", normalized)
  if explicit:
    value = int(explicit.group(1))
    return value if 1 <= value <= 12 else None
  if re.search(r"\b(?:double|two)\s+functions?\b", normalized):
    return 2
  if re.search(r"\b(?:single|one)\s+functions?\b", normalized):
    return 1
  return None


def _infer_topic_from_paths(paths: list[str]) -> str:
  for path in paths:
    base = str(path or "").rsplit("/", 1)[-1].strip().lower()
    if not base:
      continue
    name = base.rsplit(".", 1)[0]
    name = re.sub(r"[^a-z0-9+#]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if name:
      return name[:80]
  return ""


def _infer_topic(user_messages: list[str]) -> str:
  for message in reversed(user_messages):
    for pattern in _TOPIC_PATTERNS:
      match = pattern.search(message)
      if not match:
        continue
      topic = _TOPIC_STOP_PATTERN.sub("", match.group(1))
      topic = re.split(r"\b(?:with|using|from|but|and then|then)\b", topic, maxsplit=1, flags=re.IGNORECASE)[0]
      topic = re.sub(r"[^a-zA-Z0-9+# ]+", " ", topic)
      topic = re.sub(r"\s+", " ", topic).strip().lower()
      words = topic.split()
      if 1 <= len(words) <= 6 and "function" not in words:
        return "_".join(words)
  return ""


def _infer_language(user_messages: list[str]) -> str:
  for message in reversed(user_messages):
    language = _language_from_text(message)
    if language:
      return language
  return ""


def _language_from_text(text: str) -> str:
  match = _LANGUAGE_PATTERN.search(str(text or ""))
  return _normalize_language(match.group(1)) if match else ""


def _normalize_language(value: str) -> str:
  normalized = str(value or "").strip().lower()
  aliases = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "java": "java",
  }
  return aliases.get(normalized, normalized)


def _infer_language_from_paths(paths: list[str]) -> str:
  extension_map = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".swift": "swift",
  }
  for path in paths:
    lowered = str(path or "").strip().lower()
    for extension, language in extension_map.items():
      if lowered.endswith(extension):
        return language
  return ""


def _number_label(value: int) -> str:
  if value == 1:
    return "one"
  if value == 2:
    return "two"
  return str(value)


def _tokens(text: str) -> set[str]:
  return set(_TOKEN_PATTERN.findall(str(text or "").lower()))


def _fingerprint(*, correction_kind: str, topic: str, language: str, value: str) -> str:
  raw = "|".join((correction_kind, topic, language, value))
  return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(row, dict):
    return {}
  if isinstance(row.get("metadata_json"), dict):
    return row["metadata_json"]
  if isinstance(row.get("metadata"), dict):
    return row["metadata"]
  return {}
