from __future__ import annotations

from typing import Any

try:
  from backend.agents.artifacts import ArtifactValidationError
  from backend.local_workspace import LocalWorkspaceError
  from backend.storage import StorageError
  from backend.api.run_locks import ProjectGenerationAlreadyRunningError, ProjectGenerationCancelledError
except ImportError:
  from backend.agents.artifacts import ArtifactValidationError
  from backend.local_workspace import LocalWorkspaceError
  from backend.storage import StorageError
  from backend.api.run_locks import ProjectGenerationAlreadyRunningError, ProjectGenerationCancelledError

from ..scoped import scoped_update_guard_code, scoped_update_guard_user_message
from .markers import gemini_artifact_failure_marker, local_control_failure_marker
from .messages import failure_cause_label


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
