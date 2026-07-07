from __future__ import annotations

import os
import re
from typing import Any

from .budget_config import AGENT_BUDGETS


STATEFUL_CODE_CONTEXT_INSTRUCTION = (
  "You are a stateful assistant. Look back at the conversation history to "
  "understand the user's evolution of thought. However, always apply your "
  "brand rules and code changes strictly to the CURRENT live version of the "
  "code provided in the latest context."
)

RECENT_FULL_TURNS = 16
MAX_STORED_HISTORY_MESSAGES = 120
MAX_OLDER_SUMMARY_CHARS = 8_000
MAX_RECENT_MESSAGE_CHARS = AGENT_BUDGETS.recent_message_chars
MAX_PROJECT_CONTEXT_FILES = AGENT_BUDGETS.project_context_files
MAX_PROJECT_CONTEXT_CHARS_PER_FILE = AGENT_BUDGETS.project_context_chars_per_file
MAX_PROJECT_CONTEXT_TOTAL_CHARS = AGENT_BUDGETS.project_context_total_chars
MAX_ENHANCEMENT_CONTEXT_CHARS = 12_000
MAX_ERROR_CONTEXT_CHARS = 12_000
MAX_CHAT_CONTEXT_BUDGET_CHARS = AGENT_BUDGETS.chat_context_chars
WORKER_RECENT_TURNS = 10
MAX_WORKER_CHAT_CONTINUITY_CHARS = 16_000
MAX_WORKER_MESSAGE_CHARS = 4_000


def estimate_messages_chars(messages: list[dict[str, Any]]) -> int:
  return sum(len(str(item.get("content") or "")) for item in messages if isinstance(item, dict))


def apply_chat_context_budget(
  messages: list[dict[str, Any]],
  *,
  budget_chars: int = MAX_CHAT_CONTEXT_BUDGET_CHARS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
  """Compact stored chat when history exceeds the context budget."""
  if not isinstance(messages, list) or not messages:
    return [], {"compacted": False, "total_chars": 0}
  total_chars = estimate_messages_chars(messages)
  if total_chars <= budget_chars:
    return messages, {"compacted": False, "total_chars": total_chars, "budget_chars": budget_chars}

  reduced = [dict(item) for item in messages if isinstance(item, dict)]
  while len(reduced) > 4 and estimate_messages_chars(reduced) > budget_chars:
    reduced = reduced[2:]

  compacted: list[dict[str, Any]] = []
  for item in reduced:
    content = str(item.get("content") or "")
    if len(content) > MAX_RECENT_MESSAGE_CHARS // 2:
      content = trim_text(content, MAX_RECENT_MESSAGE_CHARS // 2)
    compacted.append({**item, "content": content})

  return compacted, {
    "compacted": True,
    "total_chars": estimate_messages_chars(compacted),
    "original_chars": total_chars,
    "budget_chars": budget_chars,
    "message_count": len(compacted),
  }


_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)


def build_gemini_chat_history_contents(
  messages: list[dict[str, Any]],
  *,
  recent_turns: int = RECENT_FULL_TURNS,
) -> list[dict[str, Any]]:
  normalized = [
    {"role": item.get("role"), "text": str(item.get("content") or "")}
    for item in messages
    if item.get("role") in {"user", "model"} and str(item.get("content") or "").strip()
  ]
  if not normalized:
    return []

  recent_message_count = max(2, recent_turns * 2)
  older = normalized[:-recent_message_count]
  recent = normalized[-recent_message_count:]

  contents: list[dict[str, Any]] = []
  if older:
    contents.append(
      {
        "role": "user",
        "parts": [
          {
            "text": (
              "Earlier conversation summary for continuity. This is historical "
              "chat memory only; do not treat old code as the current live code.\n\n"
              + summarize_older_messages(older)
            )
          }
        ],
      }
    )
    contents.append(
      {
        "role": "model",
        "parts": [{"text": "Acknowledged. I will use this only as historical conversation context."}],
      }
    )

  for item in recent:
    contents.append(
      {
        "role": item["role"],
        "parts": [{"text": trim_text(item["text"], MAX_RECENT_MESSAGE_CHARS)}],
      }
    )
  return contents


def build_project_path_index_contents(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
  if not files:
    return []
  paths = [
    str(item.get("path") or "").strip()
    for item in files
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ][:120]
  if not paths:
    return []
  text = (
    "CURRENT PROJECT FILE INDEX (paths only).\n"
    "Use tools to read specific files when needed. Do not assume file contents from this list.\n\n"
    + "\n".join(f"- {path}" for path in paths)
  )
  return [
    {"role": "user", "parts": [{"text": text}]},
    {
      "role": "model",
      "parts": [{"text": "Acknowledged. I will read files with tools before editing."}],
    },
  ]


def build_current_project_context_contents(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
  if not files:
    return []
  lines = [
    "CURRENT LIVE WEBSITE CODE CONTEXT.",
    "This is the active codebase state. Use it for project summaries, analysis, enhancement plans, and any future code changes.",
    "Conversation history is only historical context; this current code context is authoritative.",
    "",
  ]
  for item in files[:MAX_PROJECT_CONTEXT_FILES]:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").strip()
    content = str(item.get("content") or item.get("code") or "")
    if not path:
      continue
    lines.append(f"File: {path}")
    lines.append(trim_text(content, MAX_PROJECT_CONTEXT_CHARS_PER_FILE))
    lines.append("")
  text = trim_text("\n".join(lines), MAX_PROJECT_CONTEXT_TOTAL_CHARS)
  return [
    {"role": "user", "parts": [{"text": text}]},
    {
      "role": "model",
      "parts": [
        {
          "text": (
            "Acknowledged. I will treat this as the current live website code and "
            "use conversation history only for understanding user intent."
          )
        }
      ],
    },
  ]


def latest_enhancement_context(messages: list[dict[str, Any]]) -> str:
  for item in reversed(messages):
    if item.get("role") != "model":
      continue
    text = str(item.get("content") or "")
    lower = text.lower()
    if "enhancement" not in lower and "improvement" not in lower and "suggest" not in lower:
      continue
    return trim_text(strip_redundant_code_blocks(text), MAX_ENHANCEMENT_CONTEXT_CHARS)
  return ""


def latest_error_context(messages: list[dict[str, Any]]) -> str:
  signal_terms = (
    "uncaught",
    "typeerror",
    "referenceerror",
    "syntaxerror",
    "traceback",
    "exception",
    "failed to load resource",
    "module not found",
    "cannot find module",
    "compile error",
    "build failed",
    "local environment error",
    "local skills helper",
    "local helper is not reachable",
    "terminal handling",
    "terminal action",
    "system folder write failed",
    "browser folder write failed",
    "home worktual-skills folder was not created",
    "workspace is outside allowed roots",
    "cannot read properties",
    "reading '",
    'reading "',
  )
  for item in reversed(messages):
    if item.get("role") not in {"user", "model"}:
      continue
    text = str(item.get("content") or "")
    lower = text.lower()
    if not any(term in lower for term in signal_terms):
      continue
    if "generation failed:" in lower and "scoped update" in lower and "cannot read properties" not in lower:
      continue
    return trim_text(strip_redundant_code_blocks(text), MAX_ERROR_CONTEXT_CHARS)
  return ""


def summarize_older_messages(messages: list[dict[str, str]]) -> str:
  lines: list[str] = []
  for index, item in enumerate(messages, start=1):
    role = item["role"]
    text = strip_redundant_code_blocks(item["text"])
    lines.append(f"{index}. {role}: {trim_text(text, 500)}")
  return trim_text("\n".join(lines), MAX_OLDER_SUMMARY_CHARS)


def strip_redundant_code_blocks(text: str) -> str:
  stripped = _FENCED_CODE_RE.sub("[code block omitted from older chat memory]", text)
  return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def trim_text(text: str, max_chars: int) -> str:
  if len(text) <= max_chars:
    return text
  return text[: max_chars - 120].rstrip() + "\n...[truncated for chat context window management]..."


def build_compact_chat_continuity_block(
  messages: list[dict[str, Any]],
  *,
  enhancement_context: str = "",
  error_context: str = "",
  recent_turns: int = WORKER_RECENT_TURNS,
  max_chars: int = MAX_WORKER_CHAT_CONTINUITY_CHARS,
) -> str:
  """Compact chat continuity for parallel workers and streaming file agents."""
  if not messages and not enhancement_context.strip() and not error_context.strip():
    return ""

  normalized = [
    {"role": str(item.get("role") or ""), "text": str(item.get("content") or "")}
    for item in messages
    if isinstance(item, dict)
    and item.get("role") in {"user", "model"}
    and str(item.get("content") or "").strip()
  ]
  lines = [
    STATEFUL_CODE_CONTEXT_INSTRUCTION,
    "",
    "CONVERSATION CONTINUITY (historical intent only — live code in project snapshot is authoritative):",
  ]
  if error_context.strip():
    lines.extend(["", "Latest error context from chat:", trim_text(strip_redundant_code_blocks(error_context), MAX_ERROR_CONTEXT_CHARS)])
  if enhancement_context.strip():
    lines.extend(["", "Latest enhancement context from chat:", trim_text(strip_redundant_code_blocks(enhancement_context), MAX_ENHANCEMENT_CONTEXT_CHARS)])

  recent_message_count = max(2, recent_turns * 2)
  older = normalized[:-recent_message_count]
  recent = normalized[-recent_message_count:]
  if older:
    lines.extend(["", "Earlier turns (summary):", summarize_older_messages(older)])
  if recent:
    lines.append("")
    lines.append("Recent turns:")
    for item in recent:
      role = "User" if item["role"] == "user" else "Assistant"
      text = trim_text(strip_redundant_code_blocks(item["text"]), MAX_WORKER_MESSAGE_CHARS)
      lines.append(f"- {role}: {text}")

  return trim_text("\n".join(lines), max_chars)


FOLLOW_UP_UPDATE_MARKERS = (
  "still",
  "again",
  "also",
  "continue",
  "try again",
  "same issue",
  "not fixed",
  "didn't work",
  "did not work",
  "as i said",
  "like i said",
  "previous",
  "do the next",
  "next update",
  "remaining",
  "go ahead",
  "yes do",
  "landing",
  "directly",
)

REFERENTIAL_FOLLOW_UP_PHRASES = (
  "about him",
  "about her",
  "about it",
  "about them",
  "about this",
  "about that",
  "more about him",
  "more about her",
  "more about it",
  "more about this",
  "more about that",
  "this detailed",
  "that detailed",
  "give me this as pdf",
  "give me that as pdf",
  "as pdf",
  "in pdf",
  "as a pdf",
)

REFERENTIAL_FOLLOW_UP_TOKENS = {
  "he",
  "him",
  "his",
  "she",
  "her",
  "hers",
  "it",
  "its",
  "they",
  "them",
  "their",
  "this",
  "that",
  "these",
  "those",
}

ERROR_FOLLOW_UP_UPDATE_MARKERS = (
  "fix this error",
  "fix the error",
  "same issue",
  "try again",
  "still",
  "not fixed",
  "didn't work",
  "did not work",
  "uncaught",
  "syntaxerror",
  "typeerror",
  "referenceerror",
  "traceback",
  "exception",
  "failed to resolve",
  "does not provide an export",
  "module not found",
  "cannot find module",
  "cannot access",
  "build failed",
  "plugin:vite",
)

UPDATE_CONTINUITY_BLOCK_MARKERS = (
  "Conversation continuity",
  "earlier requirements in this chat session",
  "CONVERSATION CONTINUITY",
)

MAX_PRIOR_USER_MESSAGE_CHARS = 900
MAX_PRIOR_ASSISTANT_MESSAGE_CHARS = 450
SEPARATE_REQUEST_PREFIXES = (
  "what ",
  "which ",
  "why ",
  "how ",
  "show ",
  "give ",
  "explain ",
  "summarize ",
  "tell me ",
)
ACK_ONLY_REPLIES = {"yes", "yes update", "update", "ok", "okay", "proceed", "continue"}
RESUME_NAME_QUESTION_PREFIX = "what new name should i use"
RESTART_SUGGESTION_PREFIX = "previously you mentioned "


def legacy_update_chat_continuity_enabled() -> bool:
  raw = str(os.getenv("ENABLE_LEGACY_UPDATE_CHAT_CONTINUITY") or "").strip().lower()
  return raw in {"1", "true", "yes", "on"}


def is_error_follow_up_update_prompt(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  return bool(lowered and any(marker in lowered for marker in ERROR_FOLLOW_UP_UPDATE_MARKERS))


def is_vague_follow_up_update_prompt(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  if not lowered:
    return False
  if any(marker in lowered for marker in FOLLOW_UP_UPDATE_MARKERS):
    return True
  word_count = len(re.findall(r"\w+", lowered))
  if word_count <= 4 and any(token in lowered for token in ("it", "this", "that", "same", "again", "continue", "next")):
    return True
  return False


def is_follow_up_update_prompt(prompt: str) -> bool:
  return is_vague_follow_up_update_prompt(prompt) or is_error_follow_up_update_prompt(prompt)


def is_referential_followup_prompt(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  if not lowered:
    return False
  if any(phrase in lowered for phrase in REFERENTIAL_FOLLOW_UP_PHRASES):
    return True
  words = re.findall(r"\b[a-z]+\b", lowered)
  if not words:
    return False
  referential_hits = [word for word in words if word in REFERENTIAL_FOLLOW_UP_TOKENS]
  if not referential_hits:
    return False
  if len(words) <= 12:
    return True
  return any(word in {"this", "that", "him", "her", "them"} for word in referential_hits)


def should_include_chat_continuity_for_prompt(prompt: str) -> bool:
  if legacy_update_chat_continuity_enabled():
    return True
  primary = primary_update_prompt(prompt)
  return is_vague_follow_up_update_prompt(primary) or is_referential_followup_prompt(primary)


def should_include_error_context_for_prompt(prompt: str) -> bool:
  if legacy_update_chat_continuity_enabled():
    return True
  return is_error_follow_up_update_prompt(primary_update_prompt(prompt))


def should_include_session_memory_for_prompt(prompt: str) -> bool:
  if legacy_update_chat_continuity_enabled():
    return True
  primary = primary_update_prompt(prompt)
  return (
    is_vague_follow_up_update_prompt(primary)
    or is_error_follow_up_update_prompt(primary)
    or is_referential_followup_prompt(primary)
  )


def model_chat_history_messages_for_prompt(
  prompt: str,
  messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
  """Return raw provider chat history only when legacy continuity is explicitly enabled."""
  if not legacy_update_chat_continuity_enabled():
    return []
  return list(messages or [])


def clean_update_prompt(prompt: str) -> str:
  return primary_update_prompt(str(prompt or "").strip())


def prompt_already_has_update_continuity(prompt: str) -> bool:
  text = str(prompt or "")
  return any(marker in text for marker in UPDATE_CONTINUITY_BLOCK_MARKERS)


def primary_update_prompt(prompt: str) -> str:
  """Return only the latest user turn, without merged session continuity."""
  cleaned = str(prompt or "").strip()
  if not cleaned:
    return ""
  for marker in UPDATE_CONTINUITY_BLOCK_MARKERS:
    idx = cleaned.find(marker)
    if idx > 0:
      return cleaned[:idx].strip()
  return cleaned


def has_prior_chat_messages(messages: list[dict[str, Any]] | None, *, min_messages: int = 1) -> bool:
  count = sum(
    1
    for item in (messages or [])
    if isinstance(item, dict)
    and item.get("role") in {"user", "model"}
    and str(item.get("content") or "").strip()
  )
  return count >= min_messages


def _normalize_chat_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, str]]:
  return [
    {
      "role": str(item.get("role") or ""),
      "content": str(
        (
          item.get("metadata_json")
          if isinstance(item.get("metadata_json"), dict)
          else item.get("metadata")
          if isinstance(item.get("metadata"), dict)
          else {}
        ).get("display_content")
        or item.get("content")
        or ""
      ).strip(),
    }
    for item in (messages or [])
    if isinstance(item, dict)
    and item.get("role") in {"user", "model"}
    and str(
      (
        item.get("metadata_json")
        if isinstance(item.get("metadata_json"), dict)
        else item.get("metadata")
        if isinstance(item.get("metadata"), dict)
        else {}
      ).get("display_content")
      or item.get("content")
      or ""
    ).strip()
  ]


def _looks_like_separate_request(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  if not lowered:
    return False
  if lowered in ACK_ONLY_REPLIES:
    return False
  if lowered.endswith("?"):
    return True
  return any(lowered.startswith(prefix) for prefix in SEPARATE_REQUEST_PREFIXES)


def _merge_clarification_reply(previous_prompt: str, reply: str, missing_fields: list[str]) -> str:
  if "new_name_or_brand_title" in missing_fields:
    rename_target = _extract_rename_target_candidate(reply) or reply.strip()
    if re.search(r"\b(?:website|site|app|project)\b", previous_prompt.lower()):
      return f"{previous_prompt.rstrip()} to {rename_target}"
    return f"change the website name to {rename_target}"
  return f"{previous_prompt.rstrip()}\n\nRequested update details:\n{reply.strip()}"


def _extract_restart_suggested_name(message: str) -> str:
  text = str(message or "").strip()
  if not text:
    return ""
  lowered = text.lower()
  if not lowered.startswith(RESTART_SUGGESTION_PREFIX):
    return ""
  match = re.search(r'Previously you mentioned "([^"]+)"', text)
  if not match:
    return ""
  candidate = _extract_rename_target_candidate(match.group(1))
  return candidate[:120] if candidate else ""


def recover_update_clarification_prompt(
  prompt: str,
  messages: list[dict[str, Any]] | None,
) -> str:
  cleaned = clean_update_prompt(prompt)
  if not cleaned:
    return cleaned
  if _looks_like_separate_request(cleaned):
    return cleaned

  normalized = _normalize_chat_messages(messages)
  if not normalized:
    return cleaned

  while normalized and normalized[-1]["role"] == "user" and normalized[-1]["content"] == cleaned:
    normalized.pop()

  if len(normalized) < 2:
    return cleaned

  assistant_index = next(
    (index for index in range(len(normalized) - 1, -1, -1) if normalized[index]["role"] == "model"),
    -1,
  )
  if assistant_index <= 0:
    return cleaned

  prior_user = next(
    (normalized[index]["content"] for index in range(assistant_index - 1, -1, -1) if normalized[index]["role"] == "user"),
    "",
  )
  if not prior_user:
    return cleaned

  try:
    from .request_understanding import assess_request_understanding
  except ImportError:
    return cleaned

  understanding = assess_request_understanding(prior_user, intent="website_update")
  if understanding.get("clarification_required") is not True:
    suggested_name = _extract_restart_suggested_name(normalized[assistant_index]["content"])
    if suggested_name and cleaned.lower() in ACK_ONLY_REPLIES:
      return f"change the website name to {suggested_name}"
    return cleaned

  missing_fields = [
    str(item).strip()
    for item in understanding.get("missing_fields") or []
    if str(item).strip()
  ]
  if not missing_fields:
    suggested_name = _extract_restart_suggested_name(normalized[assistant_index]["content"])
    if suggested_name and cleaned.lower() in ACK_ONLY_REPLIES:
      return f"change the website name to {suggested_name}"
    return cleaned
  if cleaned.lower() in ACK_ONLY_REPLIES:
    suggested_name = _extract_restart_suggested_name(normalized[assistant_index]["content"])
    if suggested_name:
      return f"change the website name to {suggested_name}"
    return cleaned

  return _merge_clarification_reply(clean_update_prompt(prior_user), cleaned, missing_fields)


def prior_rename_target_suggestion(
  prompt: str,
  messages: list[dict[str, Any]] | None,
) -> str:
  cleaned = clean_update_prompt(prompt)
  if not cleaned:
    return ""
  normalized = _normalize_chat_messages(messages)
  if not normalized:
    return ""

  while normalized and normalized[-1]["role"] == "user" and normalized[-1]["content"] == cleaned:
    normalized.pop()

  try:
    from .request_understanding import assess_request_understanding
  except ImportError:
    return ""

  understanding = assess_request_understanding(cleaned, intent="website_update")
  missing_fields = {
    str(item).strip()
    for item in understanding.get("missing_fields") or []
    if str(item).strip()
  }
  if "new_name_or_brand_title" not in missing_fields:
    return ""

  for index in range(len(normalized) - 1, 1, -1):
    current = normalized[index]
    previous = normalized[index - 1]
    earlier = normalized[index - 2]
    if current["role"] != "user" or previous["role"] != "model" or earlier["role"] != "user":
      continue
    if RESUME_NAME_QUESTION_PREFIX not in previous["content"].strip().lower():
      continue
    prior_understanding = assess_request_understanding(earlier["content"], intent="website_update")
    prior_missing = {
      str(item).strip()
      for item in prior_understanding.get("missing_fields") or []
      if str(item).strip()
    }
    if "new_name_or_brand_title" not in prior_missing:
      continue
    candidate = _extract_rename_target_candidate(current["content"])
    if not candidate:
      continue
    return candidate[:120]
  return ""


def _episodic_user_request(memory: dict[str, Any]) -> str:
  if not isinstance(memory, dict):
    return ""
  metadata = memory.get("metadata")
  if not isinstance(metadata, dict):
    metadata = memory.get("metadata_json")
  if isinstance(metadata, dict):
    for key in ("user_request", "prompt", "request"):
      value = str(metadata.get(key) or "").strip()
      if value:
        return value
  content = str(memory.get("content") or "").strip()
  match = re.search(r"^User request:\s*(.+)$", content, flags=re.IGNORECASE | re.MULTILINE)
  if match:
    return match.group(1).strip()
  return ""


def _extract_rename_target_candidate(candidate: str) -> str:
  text = str(candidate or "").strip()
  if not text:
    return ""
  normalized = re.sub(r"\s+", " ", text).strip()
  lowered = normalized.lower()
  if lowered in ACK_ONLY_REPLIES or _looks_like_separate_request(normalized):
    return ""

  extracted = ""
  patterns = (
    r"(?:website|site|app|project)?\s*(?:name|title|brand)\s+is\s+(.+)$",
    r"(?:change|update|rename|rebrand).{0,80}?(?:website|site|app|project)?\s*(?:name|title|brand).{0,20}?(?:to|as)\s+(.+)$",
  )
  for pattern in patterns:
    match = re.search(pattern, lowered, flags=re.IGNORECASE)
    if match:
      start = match.start(1)
      extracted = normalized[start:].strip()
      break

  value = extracted or normalized
  value = re.sub(r"^[\"'`]+|[\"'`]+$", "", value).strip(" .,:;!?\n\t")
  value = re.sub(r"\s+", " ", value).strip()
  lowered_value = value.lower()
  if not value:
    return ""
  if any(token in lowered_value for token in ("change the website name", "change my website name", "update the website name", "rename the website", "website name", "brand title")) and extracted == "":
    return ""
  if len(value.split()) > 8 and extracted == "":
    return ""
  return value[:120]


def prior_rename_target_suggestion_from_memories(
  prompt: str,
  memories: list[dict[str, Any]] | None,
) -> str:
  cleaned = clean_update_prompt(prompt)
  if not cleaned:
    return ""
  try:
    from .request_understanding import assess_request_understanding
  except ImportError:
    return ""

  understanding = assess_request_understanding(cleaned, intent="website_update")
  missing_fields = {
    str(item).strip()
    for item in understanding.get("missing_fields") or []
    if str(item).strip()
  }
  if "new_name_or_brand_title" not in missing_fields:
    return ""

  for item in memories or []:
    candidate = _episodic_user_request(item)
    if not candidate:
      continue
    candidate = _extract_rename_target_candidate(candidate)
    if not candidate or candidate == cleaned:
      continue
    candidate_understanding = assess_request_understanding(candidate, intent="website_update")
    if candidate_understanding.get("clarification_required") is True:
      continue
    return candidate[:120]
  return ""


def merge_update_prompt_with_chat_context(
  prompt: str,
  messages: list[dict[str, Any]] | None,
  *,
  max_prior_user_messages: int = 3,
  max_prior_assistant_messages: int = 1,
) -> str:
  """Attach recent chat requirements so every update turn inherits prior session intent."""
  raw_prompt = str(prompt or "").strip()
  cleaned = clean_update_prompt(raw_prompt)
  if not cleaned:
    return cleaned
  if not legacy_update_chat_continuity_enabled():
    return cleaned
  if prompt_already_has_update_continuity(raw_prompt):
    return raw_prompt

  normalized = _normalize_chat_messages(messages)
  prior_users = [
    item["content"]
    for item in normalized
    if item["role"] == "user" and item["content"] != cleaned
  ][-max_prior_user_messages:]
  prior_assistants = [
    trim_text(strip_redundant_code_blocks(item["content"]), MAX_PRIOR_ASSISTANT_MESSAGE_CHARS)
    for item in normalized
    if item["role"] == "model"
  ][-max_prior_assistant_messages:]

  if not prior_users and not prior_assistants:
    return cleaned

  lines = [
    "Conversation continuity — earlier chat in this session still applies unless the latest message explicitly replaces it:",
  ]
  if prior_users:
    lines.append("")
    lines.append("Earlier user requirements:")
    lines.extend(f"- {trim_text(item, MAX_PRIOR_USER_MESSAGE_CHARS)}" for item in prior_users)
  if prior_assistants:
    lines.append("")
    lines.append("Recent assistant context:")
    lines.extend(f"- {item}" for item in prior_assistants)

  return f"{cleaned}\n\n" + "\n".join(lines)


def enrich_website_modification_prompt(
  prompt: str,
  messages: list[dict[str, Any]] | None,
) -> str:
  """Return the latest user prompt by default; legacy flag restores raw chat merging."""
  return merge_update_prompt_with_chat_context(prompt, messages)


def enrich_same_topic_referential_prompt(
  prompt: str,
  messages: list[dict[str, Any]] | None,
  *,
  max_recent_turns: int = 3,
) -> str:
  cleaned = str(prompt or "").strip()
  if not cleaned or prompt_already_has_update_continuity(cleaned):
    return cleaned
  if not is_referential_followup_prompt(cleaned):
    return cleaned

  normalized = _normalize_chat_messages(messages)
  if not normalized:
    return cleaned

  while normalized and normalized[-1]["role"] == "user" and normalized[-1]["content"] == cleaned:
    normalized.pop()
  if not normalized:
    return cleaned

  selected = normalized[-(max_recent_turns * 2):]
  lines = [
    cleaned,
    "",
    "Conversation continuity — resolve referential phrases like him, her, it, this, or that from the same-topic turns below unless the latest message explicitly changes the subject:",
    "",
    "Recent same-topic turns:",
  ]
  for item in selected:
    role = "User" if item["role"] == "user" else "Assistant"
    lines.append(f"- {role}: {trim_text(strip_redundant_code_blocks(item['content']), 800)}")
  return "\n".join(lines)


def build_model_chat_memory_text(generation: dict[str, Any], *, local_sync: Any = None, local_sync_error: str | None = None) -> str:
  multi_agent = generation.get("multi_agent_system") if isinstance(generation, dict) else {}
  orchestration = generation.get("orchestration_flow") if isinstance(generation, dict) else {}
  generated = orchestration.get("generated_website") if isinstance(orchestration, dict) else {}
  intent = multi_agent.get("intent") if isinstance(multi_agent, dict) else None
  conversation = multi_agent.get("conversation_response") if isinstance(multi_agent, dict) else {}
  runtime = multi_agent.get("agentic_runtime") if isinstance(multi_agent, dict) else {}

  if isinstance(conversation, dict) and conversation.get("message") and intent not in {"website_generation", "website_update"}:
    guidance = conversation.get("next_prompt_guidance") or []
    return trim_text(
      "Assistant response:\n"
      + str(conversation.get("message"))
      + ("\nNext guidance:\n- " + "\n- ".join(str(item) for item in guidance) if guidance else ""),
      6000,
    )

  files = generated.get("files") if isinstance(generated, dict) else []
  paths = [
    str(item.get("path") or "")
    for item in files
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  completion = runtime.get("completion_status") if isinstance(runtime, dict) else {}
  summary_lines = [
    f"Assistant completed intent: {intent or 'unknown'}.",
    f"Website title: {generated.get('title') if isinstance(generated, dict) else 'unknown'}.",
    f"Headline: {generated.get('headline') if isinstance(generated, dict) else ''}",
    f"Changed/generated files: {', '.join(paths[:30]) if paths else 'none reported'}.",
    f"Completion status: {completion if completion else 'not reported'}.",
  ]
  if local_sync:
    summary_lines.append(f"Local sync: {local_sync}.")
  if local_sync_error:
    summary_lines.append(f"Local sync error: {local_sync_error}.")
  summary_lines.append(
    "Code bodies are intentionally omitted from chat history. The backend will provide the CURRENT live code separately on future turns."
  )
  return trim_text("\n".join(summary_lines), 6000)
