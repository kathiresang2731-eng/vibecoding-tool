from __future__ import annotations


def should_use_deterministic_artifact_fallback(error: Exception) -> bool:
  return False


def should_abort_runtime_without_repair(error: Exception) -> bool:
  lowered = str(error).lower()
  if "skipped gemini repair because less than" in lowered:
    return True
  if "code artifact validation failed" not in lowered:
    return False
  return is_artifact_json_invalid_error(error) or is_model_connection_error(error)


def is_retriable_scoped_update_guard_error(error: Exception) -> bool:
  """Allow one stricter scoped retry for patch-shape failures, not safety violations."""
  lowered = str(error).lower()
  retriable_markers = (
    "blocked before project modification",
    "no safe patch",
    "no scoped edits",
    "no usable edit",
    "changed files for the approved files",
    "new file without modifying",
    "rewrite too much",
    "returned no effective file changes",
    "invalid scoped patch json",
    "expected ",
    "exact match",
    "empty search snippet",
    "invalid replacement snippet",
    "invalid replacement count",
    "replacement count",
    "exceeded the twenty-edit safety limit",
    "unapproved file",
  )
  unsafe_markers = (
    "invalid path",
    "duplicate changes",
    "four-file change limit",
    "existing-file change limit",
    "new-file change limit",
    "too large for a safe model patch",
    "full regeneration",
  )
  if any(marker in lowered for marker in unsafe_markers):
    return False
  return any(marker in lowered for marker in retriable_markers)


def deterministic_artifact_strategy_for_error(error: Exception) -> str:
  if is_artifact_json_invalid_error(error):
    return "deterministic_artifact_json_fallback"
  return "deterministic_artifact_connection_fallback"


def is_artifact_json_invalid_error(error: Exception) -> bool:
  lowered = str(error).lower()
  return (
    "gemini returned invalid json" in lowered
    or "artifact_json_invalid" in lowered
    or "artifact model returned a non-json object response" in lowered
    or "code agent response must be a json object" in lowered
  )


def is_model_connection_error(error: Exception) -> bool:
  lowered = str(error).lower()
  return any(
    marker in lowered
    for marker in (
      "connection error",
      "connection refused",
      "connection reset",
      "connection reset by peer",
      "model connection failed",
      "network error",
      "gemini network error",
      "configured model endpoints",
      "temporarily unavailable",
      "timeout",
      "timed out",
    )
  )
