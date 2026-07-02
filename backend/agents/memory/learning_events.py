from __future__ import annotations

import hashlib
from typing import Any

SUCCESSFUL_OUTCOMES = frozenset({"completed", "ready", "partial"})
FAILED_OUTCOMES = frozenset({"failed", "error"})
PASSED_PREVIEW_STATUSES = frozenset({"passed", "ready", "built", "completed", "success", "skipped"})
GENERATION_OR_UPDATE_INTENTS = frozenset(
  {
    "simple_code",
    "website_generation",
    "website_update",
    "full_generation",
    "targeted_update",
    "feature_update",
    "large_project",
  }
)
def confidence_tier_for_evidence(source_count: int) -> str:
  count = int(source_count or 0)
  if count >= 5:
    return "promoted_platform_pattern"
  if count >= 2:
    return "recommended_platform_pattern"
  if count >= 1:
    return "soft_platform_lesson"
  return "blocked_pattern"


def request_text_hash(text: str) -> str:
  return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def classify_learning_task_type(intent: str, *, prompt: str = "", changed_paths: list[str] | None = None) -> str:
  normalized = str(intent or "").strip().lower()
  if normalized == "simple_code":
    return "simple_code"
  if normalized in {"website_generation", "full_generation"}:
    return "full_generation"
  if normalized in {"website_update", "targeted_update"}:
    path_count = len(changed_paths or [])
    if path_count <= 4:
      return "targeted_update"
    return "feature_update"
  if normalized == "large_project":
    return "large_project"
  lowered = str(prompt or "").lower()
  if any(token in lowered for token in ("generate", "build", "create", "website", "app", "page", "module")):
    return "full_generation" if "generate" in lowered or "build" in lowered else "feature_update"
  return normalized or "general"


def validation_status_for_run(
  *,
  outcome: str,
  preview_status: str | None,
  error_category: str | None,
  changed_paths: list[str] | None,
) -> str:
  normalized_outcome = str(outcome or "").strip().lower()
  normalized_preview = str(preview_status or "").strip().lower()
  if error_category or normalized_outcome in FAILED_OUTCOMES:
    return "failed"
  if normalized_preview and normalized_preview not in PASSED_PREVIEW_STATUSES:
    return "failed"
  if normalized_outcome in SUCCESSFUL_OUTCOMES and changed_paths:
    return "passed"
  if normalized_outcome in SUCCESSFUL_OUTCOMES:
    return "completed_no_changes"
  return "unknown"


def infer_mistake_type(
  *,
  prompt: str,
  intent: str,
  error_category: str | None,
  changed_paths: list[str] | None,
  validation_status: str,
) -> str:
  if error_category:
    return str(error_category).strip()[:160]
  lowered = str(prompt or "").lower()
  if "single static" in lowered or ("directly" in lowered and "dashboard" in lowered):
    return "single_static_page"
  if "import" in lowered and "error" in lowered:
    return "import_error"
  if "syntax" in lowered and "error" in lowered:
    return "syntax_error"
  if "wrong file" in lowered or "unrelated file" in lowered:
    return "wrong_file_update"
  if validation_status == "completed_no_changes" and intent in GENERATION_OR_UPDATE_INTENTS:
    return "no_effective_change"
  if not changed_paths and intent in {"website_update", "targeted_update", "feature_update"}:
    return "empty_patch"
  return ""


def extract_reusable_lesson(
  *,
  prompt: str,
  intent: str,
  domain: str,
  modules: list[str],
  task_type: str,
  mistake_type: str,
  changed_paths: list[str] | None,
  validation_status: str,
) -> str:
  lowered = str(prompt or "").lower()
  normalized_domain = str(domain or "general").strip().lower()
  normalized_intent = str(intent or "").strip().lower()
  if normalized_intent == "simple_code" or task_type == "simple_code":
    return (
      "Standalone code requests should create only the requested source file(s). "
      "Do not create Vite, React, package, theme, page, or dependency scaffold files."
    )
  if mistake_type in {"import_error", "syntax_error"}:
    return (
      "Before saving code updates, validate syntax and imports for only the changed "
      "files and their direct dependencies, then repair once if validation fails."
    )
  if mistake_type in {"wrong_file_update", "empty_patch", "no_effective_change"}:
    return (
      "For updates, select exact target files first, send only those files or excerpts, "
      "return a real patch, and never report success when no changed paths exist."
    )
  if task_type == "targeted_update":
    return (
      "Targeted updates should patch selected files only, preserve unrelated files, "
      "and validate locally before saving."
    )
  if task_type in {"feature_update", "large_project"}:
    module_label = ", ".join(modules[:6]) if modules else "requested modules"
    return (
      f"Feature updates for {normalized_domain or 'the project'} should stage the work "
      f"around {module_label}, keep dependency files coherent, and validate before save."
    )
  if "layout" in lowered or "ui" in lowered:
    return (
      "UI updates should validate responsive layout, text clipping, overflow, and "
      "component alignment before marking the run complete."
    )
  if validation_status == "passed" and changed_paths:
    return "Validated code changes can be reused as soft guidance for matching future requests."
  return ""


def learning_scope_for_event(
  *,
  validation_status: str,
  extracted_lesson: str,
  task_type: str,
  mistake_type: str,
) -> str:
  if validation_status == "failed":
    return "blocked_pattern"
  if not extracted_lesson:
    return "personal"
  if mistake_type == "no_effective_change":
    return "blocked_pattern"
  if validation_status in {"passed", "completed_no_changes"} and task_type in {
    "simple_code",
    "targeted_update",
    "feature_update",
    "large_project",
    "full_generation",
  }:
    return "soft_platform"
  return "project"


def build_learning_event_payload(
  *,
  prompt: str,
  intent: str,
  outcome: str,
  domain: str,
  modules: list[str],
  changed_paths: list[str] | None,
  preview_status: str | None,
  error_category: str | None,
  generation_run_id: str | None,
  extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
  normalized_intent = str(intent or "").strip().lower()
  if normalized_intent not in GENERATION_OR_UPDATE_INTENTS:
    return None
  task_type = classify_learning_task_type(
    normalized_intent,
    prompt=prompt,
    changed_paths=changed_paths,
  )
  validation_status = validation_status_for_run(
    outcome=outcome,
    preview_status=preview_status,
    error_category=error_category,
    changed_paths=changed_paths,
  )
  mistake_type = infer_mistake_type(
    prompt=prompt,
    intent=normalized_intent,
    error_category=error_category,
    changed_paths=changed_paths,
    validation_status=validation_status,
  )
  extracted_lesson = extract_reusable_lesson(
    prompt=prompt,
    intent=normalized_intent,
    domain=domain,
    modules=modules,
    task_type=task_type,
    mistake_type=mistake_type,
    changed_paths=changed_paths,
    validation_status=validation_status,
  )
  scope = learning_scope_for_event(
    validation_status=validation_status,
    extracted_lesson=extracted_lesson,
    task_type=task_type,
    mistake_type=mistake_type,
  )
  confidence = 0.55
  if validation_status == "passed":
    confidence = 0.72 if scope == "soft_platform" else 0.64
  if validation_status == "failed" or scope == "blocked_pattern":
    confidence = 0.35
  metadata = {
    "source": "memory_learning_events",
    "contains_raw_request": False,
    "current_request_overrides": True,
    "modules": modules[:8],
    "preview_status": preview_status or "",
    "outcome": outcome or "",
    "run_id": generation_run_id or "",
    **(extra or {}),
  }
  return {
    "request_text_hash": request_text_hash(prompt),
    "normalized_intent": normalized_intent,
    "domain": "code_generation" if task_type == "simple_code" and domain == "general" else (domain or "general"),
    "task_type": task_type,
    "changed_paths": [str(path)[:240] for path in (changed_paths or [])[:40]],
    "validation_status": validation_status,
    "mistake_type": mistake_type,
    "extracted_lesson": extracted_lesson,
    "scope": scope,
    "confidence": confidence,
    "metadata": metadata,
  }


def persist_learning_event_checkpoint(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str | None,
  generation_run_id: str | None,
  prompt: str,
  intent: str,
  outcome: str,
  domain: str,
  modules: list[str],
  changed_paths: list[str] | None,
  preview_status: str | None,
  error_category: str | None,
  extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
  if store is None or not hasattr(store, "record_memory_learning_event"):
    return {"status": "skipped", "reason": "learning_event_store_unavailable"}
  payload = build_learning_event_payload(
    prompt=prompt,
    intent=intent,
    outcome=outcome,
    domain=domain,
    modules=modules,
    changed_paths=changed_paths,
    preview_status=preview_status,
    error_category=error_category,
    generation_run_id=generation_run_id,
    extra=extra,
  )
  if not payload:
    return {"status": "skipped", "reason": "non_generation_or_update_intent"}

  event = store.record_memory_learning_event(
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    run_id=generation_run_id,
    **payload,
  )
  platform_pattern = None
  if event.get("_created", True):
    platform_pattern = _record_soft_platform_lesson(
      store,
      user,
      event=event,
      modules=modules,
    )
  return {
    "status": "stored" if event.get("_created", True) else "existing",
    "event_id": event.get("id"),
    "scope": event.get("scope"),
    "validation_status": event.get("validation_status"),
    "platform_pattern_id": (platform_pattern or {}).get("id"),
  }


def _record_soft_platform_lesson(
  store: Any,
  user: Any,
  *,
  event: dict[str, Any],
  modules: list[str],
) -> dict[str, Any] | None:
  if not event or not hasattr(store, "upsert_memory_platform_pattern"):
    return None
  scope = str(event.get("scope") or "")
  if scope not in {"soft_platform", "promoted_platform"}:
    return None
  lesson = str(event.get("extracted_lesson") or "").strip()
  if not lesson:
    return None
  validation_status = str(event.get("validation_status") or "").strip().lower()
  if validation_status == "failed":
    return None
  domain = str(event.get("domain") or "general").strip() or "general"
  task_type = str(event.get("task_type") or "general").strip() or "general"
  module = modules[0] if modules else ("program" if domain == "code_generation" else "general")
  pattern_type = "generation_blueprint" if task_type == "full_generation" else f"{task_type}_lesson"
  existing_rows = (
    store.list_memory_platform_patterns(domain=domain, module=module, pattern_type=pattern_type, limit=25)
    if hasattr(store, "list_memory_platform_patterns")
    else []
  )
  title = f"{domain} {task_type} reusable lesson"[:240]
  existing = next((row for row in existing_rows if str(row.get("title") or "") == title), None)
  next_source_count = int((existing or {}).get("source_count") or 0) + 1
  tier = confidence_tier_for_evidence(next_source_count)
  contributor_hash = hashlib.sha256(str(getattr(user, "id", "")).encode("utf-8")).hexdigest()[:16]
  metadata = {
    "source": "memory_learning_event",
    "anonymized": True,
    "contains_chat": False,
    "contains_paths": False,
    "evidence_count": next_source_count,
    "success_count": next_source_count,
    "failure_count": 0,
    "confidence_tier": tier,
    "promotion_status": tier,
    "first_seen_user_hash": contributor_hash,
    "last_evidence_run_id": event.get("run_id") or "",
    "last_learning_event_id": event.get("id") or "",
    "current_request_overrides": True,
  }
  pattern = store.upsert_memory_platform_pattern(
    domain=domain,
    module=module,
    pattern_type=pattern_type,
    memory_type="workflow" if task_type in {"full_generation", "large_project", "feature_update"} else "fix_pattern",
    title=title,
    summary=f"Reusable {task_type} lesson for {domain}.",
    situation=f"Domain={domain}; task_type={task_type}; validation={validation_status}",
    improved_behavior=lesson,
    avoid=_avoid_text_for_event(event),
    stack_tags="vite,react,tailwind" if domain != "code_generation" else "standalone-code",
    metadata=metadata,
  )
  if pattern and hasattr(store, "record_platform_pattern_event"):
    store.record_platform_pattern_event(
      pattern_id=str(pattern.get("id") or ""),
      domain=domain,
      module=module,
      pattern_type=pattern_type,
      outcome="learned",
    )
  return pattern


def _avoid_text_for_event(event: dict[str, Any]) -> str:
  mistake_type = str(event.get("mistake_type") or "").strip()
  task_type = str(event.get("task_type") or "").strip()
  if mistake_type == "single_static_page":
    return "Avoid producing a single static page when the request asks for multiple pages or modules."
  if task_type == "simple_code":
    return "Avoid creating website dependency files for standalone code requests."
  if mistake_type in {"empty_patch", "no_effective_change"}:
    return "Avoid reporting success when no files changed."
  return ""
