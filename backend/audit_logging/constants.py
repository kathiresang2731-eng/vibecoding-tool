from __future__ import annotations

import re


QUERY_LOG_NAME = "query_model_tool.jsonl"
DYNAMIC_AGENT_LOG_NAME = "dynamic_agents.jsonl"
DEFAULT_CONTENT_MAX_CHARS = 1000

SECRET_KEY_RE = re.compile(
  r"(?:api[_-]?key|authorization|password|secret|token|cookie|credential|private[_-]?key)",
  flags=re.IGNORECASE,
)
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", flags=re.IGNORECASE)
SECRET_VALUE_RE = re.compile(
  r"(?i)\b(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*([^\s,;]+)"
)

CONTENT_KEYS = {
  "prompt",
  "message",
  "content",
  "output",
  "output_text",
  "response",
  "raw_output",
  "raw_response",
  "system_instruction",
  "error",
  "raw_error",
  "reason",
}
FILE_COLLECTION_KEYS = {"files", "candidate_files", "candidate_changes", "patches", "file_changes"}
CODE_KEYS = {"code", "file_content", "patch", "diff"}
TOKEN_METRIC_KEYS = {
  "input_tokens",
  "output_tokens",
  "total_tokens",
  "thought_tokens",
  "prompt_tokens",
  "completion_tokens",
  "cached_tokens",
}
