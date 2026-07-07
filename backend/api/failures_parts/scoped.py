from __future__ import annotations

import re

from ..progress import compact_terminal_text


def scoped_update_guard_code(lowered_error: str) -> str:
  if (
    "no scoped edits" in lowered_error
    or "no safe patch" in lowered_error
    or "no usable edit" in lowered_error
    or "no effective file changes" in lowered_error
    or "changed files for the approved files" in lowered_error
    or "without producing any file edits" in lowered_error
    or "did not persist any file edits" in lowered_error
    or "no file changes passed the commit gates" in lowered_error
  ):
    return "scoped_update_no_patch"
  if "invalid scoped patch json" in lowered_error:
    return "scoped_update_invalid_json"
  if "rewrite too much" in lowered_error:
    return "scoped_update_rewrite_too_broad"
  if "expected " in lowered_error and ("exact match" in lowered_error or "match(es)" in lowered_error):
    return "scoped_update_exact_match_failed"
  if "unapproved file" in lowered_error or "outside the approved scope" in lowered_error:
    return "scoped_update_unapproved_file"
  return "scoped_update_guard_failed"


def scoped_update_guard_user_message(lowered_error: str, raw_error: str) -> str:
  code = scoped_update_guard_code(lowered_error)
  if code == "scoped_update_no_patch":
    return "Gemini did not return a usable scoped patch for the approved files. The existing website was preserved."
  if code == "scoped_update_invalid_json":
    return "Gemini returned malformed scoped patch JSON after retry. The existing website was preserved; retrying the update should use the stricter scoped patch path."
  if code == "scoped_update_rewrite_too_broad":
    return "Gemini tried to rewrite too much of an approved file, so the scoped update was blocked and the existing website was preserved."
  if code == "scoped_update_exact_match_failed":
    return "Gemini returned a scoped edit snippet that did not match the current file contents. The existing website was preserved."
  if code == "scoped_update_unapproved_file":
    return "The requested update was blocked because it would modify files outside the approved scope. The existing website was preserved."
  if raw_error:
    reason = scoped_update_guard_reason(raw_error)
    if reason:
      return f"The scoped update was blocked by project safety checks: {reason}. The existing website was preserved."
    return "The scoped update was blocked by project safety checks. The existing website was preserved."
  return "The requested update was blocked. The existing website was preserved."


def scoped_update_guard_reason(raw_error: str) -> str:
  text = raw_error.strip()
  if not text:
    return ""
  prefixes = (
    "Agent loop failed after repair budget; restored previous project files:",
    "Scoped update was blocked before project modification:",
  )
  for prefix in prefixes:
    if text.startswith(prefix):
      text = text[len(prefix):].strip()
  text = re.sub(r"\s*The existing website was preserved\.?\s*", " ", text, flags=re.IGNORECASE)
  text = re.sub(r"\s+", " ", text).strip(" .")
  if not text:
    return ""
  return compact_terminal_text(text, max_chars=220).rstrip(".")
