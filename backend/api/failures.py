from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException

try:
  from ..agents.artifacts import ArtifactValidationError
  from ..local_workspace import LocalWorkspaceError
  from ..storage import StorageError
  from .run_locks import ProjectGenerationAlreadyRunningError, ProjectGenerationCancelledError
except ImportError:
  from agents.artifacts import ArtifactValidationError
  from local_workspace import LocalWorkspaceError
  from storage import StorageError
  from api.run_locks import ProjectGenerationAlreadyRunningError, ProjectGenerationCancelledError

from .constants import SUPPORTED_GENERATION_MODELS
from .progress import compact_terminal_text

def generation_failure_payload(exc: Exception, *, default_status: int = 502) -> dict[str, Any]:
  status = exc.status_code if isinstance(exc, HTTPException) else failure_status_code(exc, default_status)
  raw_error = exception_detail_text(exc)
  category, code, user_message = classify_generation_failure(raw_error, exc)
  repair_reason = extract_failure_repair_reason(raw_error)
  runtime_timeout = extract_runtime_timeout_seconds(raw_error)
  try:
    from ..platform.repair_routing import failure_repair_route
  except ImportError:
    from backend.platform.repair_routing import failure_repair_route
  repair_route = failure_repair_route(category=category, code=code, raw_error=raw_error)
  return {
    "status": status,
    "category": category,
    "code": code,
    "error": user_message,
    "user_message": user_message,
    "repair_route": repair_route,
    "detail": {
      "raw_error": raw_error[:2400],
      "exception_type": exc.__class__.__name__,
      "rollback_completed": "restored previous project files" in raw_error.lower(),
      "provider": provider_from_failure_category(category),
      "repair_reason": repair_reason,
      "runtime_timeout_seconds": runtime_timeout,
      "last_runtime_step": extract_last_runtime_step(raw_error),
    },
  }


def failure_status_code(exc: Exception, default_status: int) -> int:
  if isinstance(exc, ProjectGenerationAlreadyRunningError):
    return 409
  if isinstance(exc, ProjectGenerationCancelledError):
    return 499
  return default_status


def exception_detail_text(exc: Exception) -> str:
  if isinstance(exc, HTTPException):
    detail = exc.detail
    if isinstance(detail, str):
      return detail
    if isinstance(detail, dict):
      for key in ("user_message", "error", "message", "detail"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
          return value.strip()
      return json.dumps(detail, ensure_ascii=False, default=str)
    return str(detail)
  return str(exc)


def classify_generation_failure(raw_error: str, exc: Exception) -> tuple[str, str, str]:
  lowered = raw_error.lower()
  rollback_completed = "restored previous project files" in lowered
  cause_category, cause_code = detect_generation_failure_cause(lowered, exc)
  if rollback_completed:
    cause_message = failure_cause_label(cause_category)
    return (
      "rollback",
      "rollback_completed",
      f"Generation failed after repair attempts. Previous project files were restored. Last issue: {cause_message}.",
    )

  if cause_category == "local_control_model":
    if cause_code == "local_control_model_unavailable":
      return (
        cause_category,
        cause_code,
        "Local GPT control model is unavailable. Configure local_model.py or LOCAL_MODEL_JSON_ENDPOINT and retry.",
      )
    return (
      cause_category,
      cause_code,
      "Local GPT control model connection failed. Check LOCAL_MODEL_ENDPOINT/LOCAL_MODEL_JSON_ENDPOINT and retry.",
    )
  if cause_category == "usage_limit":
    return (
      cause_category,
      cause_code,
      raw_error or "You have completed your user limit.",
    )
  if cause_category == "gemini_generation":
    if cause_code == "gemini_connection_failed":
      return (
        cause_category,
        cause_code,
        "Gemini artifact generation failed due to a network or timeout error after earlier steps consumed model budget. Check backend internet access and GEMINI_TIMEOUT_SECONDS, then retry.",
      )
    return (
      cause_category,
      cause_code,
      "Gemini artifact generation failed. No generated files were committed.",
    )
  if cause_category == "artifact_validation":
    return (
      cause_category,
      cause_code,
      "Gemini returned a website artifact that failed validation. No generated files were committed.",
    )
  if cause_category == "artifact_scaffold_missing":
    return (
      cause_category,
      cause_code,
      "Generated files were missing the required Vite scaffold. The backend attempted deterministic scaffold repair before failing.",
    )
  if cause_category == "artifact_json_invalid":
    return (
      cause_category,
      cause_code,
      "Gemini returned invalid artifact JSON. The existing website was preserved and no fallback website was generated.",
    )
  if cause_category == "preview_build":
    return (
      cause_category,
      cause_code,
      "Generated files failed the staged Vite preview build. No generated files were committed.",
    )
  if cause_category == "visual_qa":
    return (
      cause_category,
      cause_code,
      "Staged preview visual QA failed. No generated files were committed.",
    )
  if cause_category == "storage":
    return (
      cause_category,
      cause_code,
      "Project storage failed while running the generation pipeline. Check the database/runtime connection.",
    )
  if cause_category == "local_sync":
    return (
      cause_category,
      cause_code,
      "Generated files were prepared, but local workspace sync failed. Check the linked folder path and permissions.",
    )
  if cause_category == "model_connection":
    return (
      cause_category,
      cause_code,
      "A model connection failed during generation. Check the configured model endpoints and retry.",
    )
  if cause_category == "routing":
    if any(marker in lowered for marker in ("gemini network error", "name resolution", "network error")):
      return (
        cause_category,
        cause_code,
        "Intent routing failed because the backend could not reach the Gemini API. Check DNS, outbound HTTPS, and GEMINI_API_KEY on the backend host, then retry.",
      )
    return (
      cause_category,
      cause_code,
      "Intent routing failed before generation started. Existing project files were preserved.",
    )
  if cause_category == "agent_runtime_timeout":
    return (
      cause_category,
      cause_code,
      "Generation exceeded the backend runtime budget before files could be committed. Check the runtime details and retry.",
    )
  if cause_category == "concurrency":
    return (
      cause_category,
      cause_code,
      "Another generation or update is already running for this project. Wait for it to finish or cancel it before starting a new update.",
    )
  if cause_category == "cancellation":
    return (
      cause_category,
      cause_code,
      "Generation was cancelled before files were committed. The existing website was preserved.",
    )
  if cause_category == "needs_user_input":
    return (
      cause_category,
      cause_code,
      raw_error,
    )
  if cause_category == "policy_denied":
    return (
      cause_category,
      cause_code,
      "The requested change was blocked because a file path is outside the allowed project surface.",
    )
  if cause_category == "model_blocked":
    return (
      cause_category,
      cause_code,
      "Gemini blocked generation due to a safety filter. Rephrase the request or switch model tier.",
    )
  if cause_category == "runtime_bug":
    return (
      cause_category,
      cause_code,
      "An internal runtime error occurred. Retry after the backend state is stabilized.",
    )
  if cause_category == "scoped_update_guard":
    return (
      cause_category,
      cause_code,
      scoped_update_guard_user_message(lowered, raw_error),
    )
  return (
    "backend_generation",
    "backend_generation_failed",
    "Backend generation failed before completion. Check the runtime details and retry.",
  )


def detect_generation_failure_cause(lowered_error: str, exc: Exception) -> tuple[str, str]:
  if isinstance(exc, ProjectGenerationAlreadyRunningError) or "already running for this project" in lowered_error:
    return "concurrency", "project_generation_already_running"
  if "completed your user limit" in lowered_error or "ai_credit_limit_exceeded" in lowered_error:
    return "usage_limit", "ai_credit_limit_exceeded"
  if "credit limit" in lowered_error or "monthly credit" in lowered_error:
    return "usage_limit", "ai_credit_limit_exceeded"
  if isinstance(exc, ProjectGenerationCancelledError) or "generation was cancelled" in lowered_error:
    return "cancellation", "generation_cancelled"
  if isinstance(exc, StorageError) or "storage" in lowered_error or "database" in lowered_error:
    return "storage", "storage_failed"
  if isinstance(exc, LocalWorkspaceError) or "local sync" in lowered_error or "linked local folder" in lowered_error:
    return "local_sync", "local_sync_failed"
  if "agent runtime exceeded timeout budget" in lowered_error or "agent runtime timed out" in lowered_error:
    return "agent_runtime_timeout", "agent_runtime_timeout"
  if "routing model failed during route_generation_action" in lowered_error or "routing repair failed during route_generation_action" in lowered_error:
    return "routing", "routing_model_failed"
  if "update request needs clarification before editing files" in lowered_error:
    return "needs_user_input", "update_needs_clarification"
  if "outside the allowed project surface" in lowered_error or "path is not allowed" in lowered_error:
    return "policy_denied", "path_policy_denied"
  if "recitation" in lowered_error:
    return "model_blocked", "gemini_recitation_filter"
  if "dictionary changed size during iteration" in lowered_error:
    return "runtime_bug", "runtime_state_mutation"
  if "scoped update" in lowered_error or "targeted update could not be applied safely" in lowered_error:
    return "scoped_update_guard", scoped_update_guard_code(lowered_error)
  if "could not resolve entry module \"index.html\"" in lowered_error or "could not resolve entry module 'index.html'" in lowered_error:
    return "artifact_scaffold_missing", "artifact_scaffold_missing"
  if "gemini returned invalid json" in lowered_error or "artifact_json_invalid" in lowered_error:
    return "artifact_json_invalid", "artifact_json_invalid"
  if "preview visual qa" in lowered_error or "run_preview_visual_qa" in lowered_error or "visual qa" in lowered_error:
    return "visual_qa", "visual_qa_failed"
  if "build_staged_project_preview" in lowered_error or "vite" in lowered_error or "preview build" in lowered_error or "staged preview" in lowered_error:
    return "preview_build", "preview_build_failed"
  if "code artifact validation failed" in lowered_error and local_control_failure_marker(lowered_error):
    return "artifact_validation", "artifact_validation_failed"
  if gemini_artifact_failure_marker(lowered_error):
    return "gemini_generation", "gemini_connection_failed"
  if "gemini" in lowered_error:
    return "gemini_generation", "gemini_generation_failed"
  if isinstance(exc, ArtifactValidationError) or "validate_project_artifact" in lowered_error or "artifact validation" in lowered_error or "generated website" in lowered_error:
    return "artifact_validation", "artifact_validation_failed"
  if local_control_failure_marker(lowered_error):
    if any(marker in lowered_error for marker in ("required but unavailable", "not configured", "requires local_model.py", "provider missing")):
      return "local_control_model", "local_control_model_unavailable"
    return "local_control_model", "local_control_model_connection_failed"
  if "connection error" in lowered_error or "model connection failed" in lowered_error or "network error" in lowered_error or "timeout" in lowered_error or "timed out" in lowered_error:
    return "model_connection", "model_connection_failed"
  return "backend_generation", "backend_generation_failed"


def scoped_update_guard_code(lowered_error: str) -> str:
  if (
    "no scoped edits" in lowered_error
    or "no safe patch" in lowered_error
    or "no usable edit" in lowered_error
    or "no effective file changes" in lowered_error
    or "changed files for the approved files" in lowered_error
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


def local_control_failure_marker(lowered_error: str) -> bool:
  return any(
    marker in lowered_error
    for marker in (
      "local control model",
      "local gpt",
      "local model provider",
      "local model endpoint",
    )
  )


def gemini_artifact_failure_marker(lowered_error: str) -> bool:
  artifact_markers = (
    "code artifact validation failed",
    "generate_website_artifact",
    "update_website_artifact",
    "repair_website_artifact",
    "artifact model call",
    "gemini network error",
  )
  connection_markers = ("connection", "network", "timeout", "timed out")
  return any(marker in lowered_error for marker in artifact_markers) and any(marker in lowered_error for marker in connection_markers)


def failure_cause_label(category: str) -> str:
  return {
    "local_control_model": "local GPT control model unavailable",
    "gemini_generation": "Gemini generation provider failed",
    "artifact_validation": "artifact validation failed",
    "preview_build": "staged preview build failed",
    "visual_qa": "visual QA failed",
    "storage": "project storage failed",
    "local_sync": "local workspace sync failed",
    "model_connection": "model connection failed",
    "routing": "intent routing failed before generation started",
    "agent_runtime_timeout": "agent runtime timed out",
    "update_clarification": "the update request needs clarification",
    "scoped_update_guard": "the scoped update was blocked to preserve the existing website",
  }.get(category, "backend generation failed")


def provider_from_failure_category(category: str) -> str | None:
  if category == "local_control_model":
    return "local-gpt"
  if category == "gemini_generation":
    return "gemini"
  if category == "model_connection":
    return "unknown-model"
  if category == "routing":
    return "control-model"
  return None


def extract_runtime_timeout_seconds(raw_error: str) -> int | None:
  match = re.search(r"agent runtime exceeded timeout budget of\s+(\d+)s", raw_error, flags=re.IGNORECASE)
  if not match:
    return None
  try:
    return int(match.group(1))
  except ValueError:
    return None


def extract_failure_repair_reason(raw_error: str) -> str | None:
  patterns = (
    r"Repair Agent repairing generated files because:\s*(?P<reason>.+)",
    r"Preview runtime scan failed:\s*(?P<reason>.+)",
    r"Previous build error:\s*(?P<reason>.+)",
  )
  for pattern in patterns:
    match = re.search(pattern, raw_error, flags=re.IGNORECASE | re.DOTALL)
    if match:
      return compact_terminal_text(match.group("reason"), max_chars=900)
  return None


def extract_last_runtime_step(raw_error: str) -> str | None:
  lowered = raw_error.lower()
  known_steps = (
    "build_staged_project_preview",
    "run_preview_visual_qa",
    "validate_project_artifact",
    "repair_website_artifact",
    "generate_website_artifact",
    "update_website_artifact",
    "write_project_files",
  )
  for step in known_steps:
    if step in lowered:
      return step
  tool_match = re.search(r"tool\s+([A-Z_]+)\s+failed", raw_error)
  if tool_match:
    return tool_match.group(1).lower()
  return None
def normalize_generation_model(model: str | None) -> str | None:
  if not model:
    return None
  cleaned = model.strip()
  if not cleaned or cleaned == "server-default":
    return None
  if cleaned not in SUPPORTED_GENERATION_MODELS:
    raise HTTPException(status_code=400, detail=f"Unsupported generation model: {cleaned}")
  return cleaned
