from __future__ import annotations

import hashlib
from typing import Any

from .constants import (
  BEARER_RE,
  CODE_KEYS,
  CONTENT_KEYS,
  DEFAULT_CONTENT_MAX_CHARS,
  FILE_COLLECTION_KEYS,
  SECRET_KEY_RE,
  SECRET_VALUE_RE,
  TOKEN_METRIC_KEYS,
)


def strip_candidate_body(value: Any) -> Any:
  if isinstance(value, list):
    return [strip_candidate_body(item) for item in value]
  if not isinstance(value, dict):
    return value
  sanitized = {key: strip_candidate_body(item) for key, item in value.items() if str(key).lower() not in CODE_KEYS | {"content"}}
  body = next(
    (
      value.get(key)
      for key in ("content", "code", "patch", "diff")
      if isinstance(value.get(key), str)
    ),
    None,
  )
  if isinstance(body, str):
    sanitized["char_count"] = len(body)
    sanitized["sha256"] = sha256_text(body)
    sanitized["code_redacted"] = True
  return sanitized


def sanitize_audit_value(value: Any, *, content_max_chars: int = DEFAULT_CONTENT_MAX_CHARS, key: str = "") -> Any:
  if value is None or isinstance(value, (bool, int, float)):
    return value
  if isinstance(value, bytes):
    return content_summary(value.decode("utf-8", errors="replace"), max_chars=content_max_chars)
  if isinstance(value, str):
    redacted = redact_text(value)
    if key.lower() in CODE_KEYS:
      return code_summary(redacted)
    if key.lower() in CONTENT_KEYS or len(redacted) > content_max_chars:
      return content_summary(redacted, max_chars=content_max_chars)
    return redacted
  if isinstance(value, dict):
    sanitized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
      normalized_key = str(raw_key)
      lowered_key = normalized_key.lower()
      if lowered_key in TOKEN_METRIC_KEYS:
        sanitized[normalized_key] = sanitize_audit_value(
          raw_value,
          content_max_chars=content_max_chars,
          key=normalized_key,
        )
      elif SECRET_KEY_RE.search(lowered_key):
        sanitized[normalized_key] = "[REDACTED]"
      elif lowered_key in FILE_COLLECTION_KEYS and isinstance(raw_value, list):
        sanitized[normalized_key] = summarize_file_collection(raw_value)
      else:
        sanitized[normalized_key] = sanitize_audit_value(
          raw_value,
          content_max_chars=content_max_chars,
          key=normalized_key,
        )
    return sanitized
  if isinstance(value, (list, tuple, set)):
    return [sanitize_audit_value(item, content_max_chars=content_max_chars, key=key) for item in value]
  if hasattr(value, "to_dict") and callable(value.to_dict):
    return sanitize_audit_value(value.to_dict(), content_max_chars=content_max_chars, key=key)
  return sanitize_audit_value(str(value), content_max_chars=content_max_chars, key=key)


def summarize_file_collection(files: list[Any]) -> list[dict[str, Any]]:
  summaries: list[dict[str, Any]] = []
  for item in files:
    if not isinstance(item, dict):
      summaries.append({"value_type": type(item).__name__})
      continue
    path = str(item.get("path") or "")
    body = item.get("content")
    if not isinstance(body, str):
      body = item.get("code")
    if not isinstance(body, str):
      body = item.get("patch")
    summary = {
      "path": path,
      "purpose": redact_text(str(item.get("purpose") or ""))[:240] or None,
      "status": item.get("status"),
      "validation_status": item.get("validation_status"),
      "char_count": len(body) if isinstance(body, str) else None,
      "sha256": sha256_text(body) if isinstance(body, str) else None,
    }
    summaries.append({key: value for key, value in summary.items() if value not in (None, "")})
  return summaries


def content_summary(value: str, *, max_chars: int = DEFAULT_CONTENT_MAX_CHARS) -> dict[str, Any]:
  redacted = redact_text(value)
  return {
    "preview": redacted[:max_chars],
    "sha256": sha256_text(redacted),
    "char_count": len(redacted),
    "truncated": len(redacted) > max_chars,
  }


def code_summary(value: str) -> dict[str, Any]:
  return {
    "code_redacted": True,
    "sha256": sha256_text(value),
    "char_count": len(value),
  }


def redact_text(value: str) -> str:
  redacted = BEARER_RE.sub("Bearer [REDACTED]", str(value))
  return SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)


def sha256_text(value: str) -> str:
  return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
