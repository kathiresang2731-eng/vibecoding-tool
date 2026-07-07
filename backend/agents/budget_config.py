from __future__ import annotations

import os
from dataclasses import dataclass


def _positive_int(name: str, fallback: int, *, maximum: int | None = None) -> int:
  try:
    value = int(str(os.getenv(name) or "").strip())
  except ValueError:
    value = fallback
  if value <= 0:
    value = fallback
  return min(value, maximum) if maximum is not None else value


@dataclass(frozen=True)
class AgentBudgetSettings:
  scoped_update_output_tokens: int
  scoped_update_retry_output_tokens: int
  routing_output_tokens: int
  memory_output_tokens: int
  specialist_output_tokens: int
  local_model_output_tokens: int
  targeted_update_files: int
  targeted_update_chars: int
  feature_update_files: int
  feature_update_chars: int
  ui_update_files: int
  ui_update_chars: int
  chat_context_chars: int
  recent_message_chars: int
  project_context_files: int
  project_context_chars_per_file: int
  project_context_total_chars: int
  attachment_text_chars: int
  streaming_context_chars: int
  streaming_update_context_chars: int
  streaming_inline_file_chars: int
  streaming_update_inline_file_chars: int
  streaming_update_priority_file_chars: int
  streaming_tool_read_chars: int
  worker_inline_chars: int
  update_worker_inline_chars: int


def load_agent_budget_settings() -> AgentBudgetSettings:
  return AgentBudgetSettings(
    scoped_update_output_tokens=_positive_int(
      "SCOPED_UPDATE_MAX_OUTPUT_TOKENS",
      32_768,
      maximum=65_536,
    ),
    scoped_update_retry_output_tokens=_positive_int(
      "SCOPED_UPDATE_RETRY_MAX_OUTPUT_TOKENS",
      16_384,
      maximum=65_536,
    ),
    routing_output_tokens=_positive_int("ROUTING_MAX_OUTPUT_TOKENS", 1_024, maximum=8_192),
    memory_output_tokens=_positive_int("MEMORY_MAX_OUTPUT_TOKENS", 2_048, maximum=16_384),
    specialist_output_tokens=_positive_int("SPECIALIST_MAX_OUTPUT_TOKENS", 4_096, maximum=32_768),
    local_model_output_tokens=_positive_int("LOCAL_MODEL_MAX_OUTPUT_TOKENS", 32_768, maximum=65_536),
    targeted_update_files=_positive_int("TARGETED_UPDATE_CONTEXT_MAX_FILES", 4, maximum=20),
    targeted_update_chars=_positive_int("TARGETED_UPDATE_CONTEXT_MAX_CHARS", 12_000, maximum=200_000),
    feature_update_files=_positive_int("FEATURE_UPDATE_CONTEXT_MAX_FILES", 8, maximum=30),
    feature_update_chars=_positive_int("FEATURE_UPDATE_CONTEXT_MAX_CHARS", 24_000, maximum=300_000),
    ui_update_files=_positive_int("UI_UPDATE_CONTEXT_MAX_FILES", 6, maximum=24),
    ui_update_chars=_positive_int("UI_UPDATE_CONTEXT_MAX_CHARS", 18_000, maximum=240_000),
    chat_context_chars=_positive_int("CHAT_CONTEXT_MAX_CHARS", 24_000, maximum=400_000),
    recent_message_chars=_positive_int("CHAT_RECENT_MESSAGE_MAX_CHARS", 8_000, maximum=100_000),
    project_context_files=_positive_int("PROJECT_CONTEXT_MAX_FILES", 12, maximum=50),
    project_context_chars_per_file=_positive_int(
      "PROJECT_CONTEXT_MAX_CHARS_PER_FILE",
      4_000,
      maximum=50_000,
    ),
    project_context_total_chars=_positive_int(
      "PROJECT_CONTEXT_MAX_TOTAL_CHARS",
      32_000,
      maximum=300_000,
    ),
    attachment_text_chars=_positive_int("ATTACHMENT_TEXT_MAX_CHARS", 32_000, maximum=200_000),
    streaming_context_chars=_positive_int("STREAMING_CONTEXT_MAX_CHARS", 96_000, maximum=400_000),
    streaming_update_context_chars=_positive_int(
      "STREAMING_UPDATE_CONTEXT_MAX_CHARS",
      18_000,
      maximum=300_000,
    ),
    streaming_inline_file_chars=_positive_int(
      "STREAMING_INLINE_FILE_MAX_CHARS",
      24_000,
      maximum=150_000,
    ),
    streaming_update_inline_file_chars=_positive_int(
      "STREAMING_UPDATE_INLINE_FILE_MAX_CHARS",
      6_000,
      maximum=150_000,
    ),
    streaming_update_priority_file_chars=_positive_int(
      "STREAMING_UPDATE_PRIORITY_FILE_MAX_CHARS",
      12_000,
      maximum=250_000,
    ),
    streaming_tool_read_chars=_positive_int(
      "STREAMING_TOOL_READ_MAX_CHARS",
      12_000,
      maximum=200_000,
    ),
    worker_inline_chars=_positive_int("PARALLEL_WORKER_INLINE_CHARS", 12_000, maximum=100_000),
    update_worker_inline_chars=_positive_int(
      "PARALLEL_UPDATE_WORKER_INLINE_CHARS",
      32_000,
      maximum=150_000,
    ),
  )


AGENT_BUDGETS = load_agent_budget_settings()
