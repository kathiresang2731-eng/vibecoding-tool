from __future__ import annotations

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
  "same issue",
  "not fixed",
  "didn't work",
  "did not work",
  "as i said",
  "like i said",
  "landing",
  "directly",
)

UPDATE_CONTINUITY_BLOCK_MARKERS = (
  "Conversation continuity",
  "earlier requirements in this chat session",
  "CONVERSATION CONTINUITY",
)

MAX_PRIOR_USER_MESSAGE_CHARS = 900
MAX_PRIOR_ASSISTANT_MESSAGE_CHARS = 450


def is_follow_up_update_prompt(prompt: str) -> bool:
  lowered = str(prompt or "").strip().lower()
  if not lowered:
    return False
  if any(marker in lowered for marker in FOLLOW_UP_UPDATE_MARKERS):
    return True
  return len(re.findall(r"\w+", lowered)) < 12


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
    {"role": str(item.get("role") or ""), "content": str(item.get("content") or "").strip()}
    for item in (messages or [])
    if isinstance(item, dict)
    and item.get("role") in {"user", "model"}
    and str(item.get("content") or "").strip()
  ]


def merge_update_prompt_with_chat_context(
  prompt: str,
  messages: list[dict[str, Any]] | None,
  *,
  max_prior_user_messages: int = 3,
  max_prior_assistant_messages: int = 1,
) -> str:
  """Attach recent chat requirements so every update turn inherits prior session intent."""
  cleaned = str(prompt or "").strip()
  if not cleaned or prompt_already_has_update_continuity(cleaned):
    return cleaned

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
  """Merge session chat into any website modification request when history exists."""
  return merge_update_prompt_with_chat_context(prompt, messages)


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
