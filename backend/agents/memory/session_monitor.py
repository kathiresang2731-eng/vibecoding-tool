"""Session-scoped memory monitoring — reference: MEMORY_FRAMEWORK episodic + session manager."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .episodic import (
  prune_episodic_memories,
  should_write_episodic_episode,
  summarize_episodic_run,
)

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
  "crm": ("crm", "lead", "leads", "deal", "deals", "contact", "contacts", "pipeline"),
  "ecommerce": ("ecommerce", "shop", "cart", "product", "catalog", "store"),
  "dashboard": ("dashboard", "analytics", "kpi", "metrics"),
  "saas": ("saas", "subscription", "onboarding", "tenant"),
  "finance": ("finance", "invoice", "billing", "payment"),
}

_MODULE_FROM_PATH = (
  ("leads", ("leads", "lead")),
  ("contacts", ("contacts", "contact")),
  ("deals", ("deals", "deal")),
  ("auth", ("auth", "login", "onboarding")),
  ("dashboard", ("dashboard",)),
  ("finance", ("finance",)),
  ("copilot", ("copilot",)),
)


def infer_domain(*, prompt: str, project_name: str = "", files: list[dict[str, Any]] | None = None) -> str:
  file_paths = " ".join(
    str(item.get("path") or "")
    for item in (files or [])
    if isinstance(item, dict)
  )
  name = str(project_name or "").strip().lower()
  haystack = " ".join((str(prompt or "").lower(), name, file_paths.lower()))
  domain_scores = {
    domain: sum(1 for keyword in keywords if re.search(rf"\b{re.escape(keyword)}\b", haystack))
    for domain, keywords in _DOMAIN_KEYWORDS.items()
  }
  best_domain, best_score = max(domain_scores.items(), key=lambda item: item[1])
  if best_score:
    return best_domain
  if name and name not in {"untitled", "new project", "worktual project", "worktual ai dev"}:
    slug = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
    if slug:
      return slug[:48]
  return "general"


def infer_modules(*, prompt: str, changed_paths: list[str] | None = None) -> list[str]:
  haystack = prompt.lower()
  modules: list[str] = []
  for module, tokens in _MODULE_FROM_PATH:
    if any(token in haystack for token in tokens):
      modules.append(module)
  for path in changed_paths or []:
    base = path.rsplit("/", 1)[-1].lower()
    name = base.rsplit(".", 1)[0]
    for module, tokens in _MODULE_FROM_PATH:
      if any(token in name for token in tokens) and module not in modules:
        modules.append(module)
  return modules[:6]


def build_file_manifest(files: list[dict[str, Any]], *, limit: int = 40) -> dict[str, Any]:
  manifest: dict[str, Any] = {"paths": [], "counts": {}, "total": 0, "truncated": False}
  total = 0
  for item in files:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").strip()
    if not path:
      continue
    total += 1
    if len(manifest["paths"]) < limit:
      manifest["paths"].append(path)
    prefix = path.split("/", 1)[0] if "/" in path else "root"
    manifest["counts"][prefix] = int(manifest["counts"].get(prefix) or 0) + 1
  manifest["total"] = total
  manifest["truncated"] = total > len(manifest["paths"])
  return manifest


def build_rolling_session_summary(
  *,
  prior_summary: str,
  prompt: str,
  intent: str,
  outcome: str,
  changed_paths: list[str] | None,
  preview_status: str | None,
  error_category: str | None,
  max_chars: int = 5000,
) -> str:
  lines = []
  if prior_summary.strip():
    lines.append("Previous session context:")
    lines.append(prior_summary.strip()[-2400:])
  lines.extend(
    [
      "",
      "Latest update:",
      f"- Intent: {intent or 'unknown'}",
      f"- Outcome: {outcome or 'completed'}",
      f"- Request: {prompt.strip()[:500]}",
    ]
  )
  if changed_paths:
    lines.append(f"- Changed files: {', '.join(changed_paths[:16])}")
  if preview_status:
    lines.append(f"- Preview: {preview_status}")
  if error_category:
    lines.append(f"- Error category: {error_category}")
  return "\n".join(lines).strip()[:max_chars]


def classify_memory_type(
  *,
  intent: str,
  outcome: str,
  error_category: str | None,
  preview_status: str | None,
) -> str:
  if error_category or (preview_status and preview_status not in {"ready", "built", "skipped"}):
    return "fix_pattern"
  if intent == "website_generation":
    return "workflow"
  if "parallel" in str(outcome).lower():
    return "tool_pattern"
  return "update_checkpoint"


def build_episode_from_run(
  *,
  prompt: str,
  intent: str,
  outcome: str,
  changed_paths: list[str] | None,
  preview_status: str | None,
  error_category: str | None,
  domain: str,
  modules: list[str],
  file_count: int = 0,
) -> dict[str, Any]:
  memory_type = classify_memory_type(
    intent=intent,
    outcome=outcome,
    error_category=error_category,
    preview_status=preview_status,
  )
  module_label = ", ".join(modules) if modules else "general"
  title = f"{memory_type} · {module_label} · {intent or 'update'}"
  searchable = summarize_episodic_run(
    intent=intent,
    prompt=prompt,
    outcome=outcome,
    file_count=file_count,
    changed_paths=changed_paths,
    preview_status=preview_status,
    error_category=error_category,
  )
  improved = ""
  avoid = ""
  if memory_type == "fix_pattern":
    improved = "Read only failing files, apply minimal syntax/fix, rerun staged build gate."
    avoid = "Do not re-analyze unrelated pages or regenerate the whole project."
  elif memory_type == "workflow":
    improved = "Use parallel workers for multi-module updates; validate with build gate before completion."
  situation = f"Domain={domain}; modules={module_label}; stack=vite,react,tailwind"
  return {
    "memory_type": memory_type,
    "title": title[:240],
    "searchable_summary": searchable[:4000],
    "situation": situation,
    "stack_tags": "vite,react,tailwind",
    "module_tags": module_label,
    "improved_behavior": improved,
    "avoid": avoid,
    "outcome": outcome,
  }


def _get_session_state_for_topic(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str,
  chat_topic_id: str | None = None,
) -> dict[str, Any] | None:
  if not hasattr(store, "get_memory_chat_session_state"):
    return None
  if chat_topic_id:
    try:
      return store.get_memory_chat_session_state(
        user,
        project_id=project_id,
        chat_session_id=chat_session_id,
        chat_topic_id=chat_topic_id,
      )
    except TypeError:
      return store.get_memory_chat_session_state(
        user,
        chat_session_id=chat_session_id,
        chat_topic_id=chat_topic_id,
      )
  try:
    return store.get_memory_chat_session_state(
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
    )
  except TypeError:
    return store.get_memory_chat_session_state(user, chat_session_id=chat_session_id)


def _sync_episode_vector_after_checkpoint(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str,
  episode: dict[str, Any] | None,
) -> None:
  if not episode:
    return
  try:
    from .episode_vector_sync import sync_episode_vector_from_row
    from .episode_vector_store import episode_vector_health

    vector_health = episode_vector_health()
    vector_ready = False
    if vector_health["enabled"]:
      vector_ready = sync_episode_vector_from_row(
        episode,
        user_id=str(user.id),
        project_id=project_id,
        chat_session_id=chat_session_id,
      )
    if hasattr(store, "set_memory_episode_vector_status"):
      store.set_memory_episode_vector_status(
        episode_id=str(episode.get("id") or ""),
        status=(
          ("ready" if vector_health["durable"] else "volatile")
          if vector_ready
          else "disabled"
          if not vector_health["enabled"]
          else "failed"
        ),
        error="" if vector_ready or not vector_health["enabled"] else "Vector store unavailable.",
      )
    if vector_health["enabled"] and not vector_ready and hasattr(store, "enqueue_consistency_job"):
      store.enqueue_consistency_job(
        user,
        project_id=project_id,
        job_type="episode_vector_upsert",
        target_key=str(episode.get("id") or ""),
        source_hash=str(episode.get("id") or ""),
        payload={"episode_id": episode.get("id"), "chat_session_id": chat_session_id},
      )
  except Exception as exc:
    if hasattr(store, "set_memory_episode_vector_status"):
      store.set_memory_episode_vector_status(
        episode_id=str(episode.get("id") or ""),
        status="failed",
        error=str(exc),
      )
    if hasattr(store, "enqueue_consistency_job"):
      store.enqueue_consistency_job(
        user,
        project_id=project_id,
        job_type="episode_vector_upsert",
        target_key=str(episode.get("id") or ""),
        source_hash=str(episode.get("id") or ""),
        payload={
          "episode_id": episode.get("id"),
          "chat_session_id": chat_session_id,
          "last_error": str(exc)[:500],
        },
      )


def _persist_generation_memory_checkpoint(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str | None,
  generation_run_id: str | None,
  prompt: str,
  intent: str,
  outcome: str,
  project_name: str = "",
  files: list[dict[str, Any]] | None = None,
  changed_paths: list[str] | None = None,
  preview_status: str | None = None,
  error_category: str | None = None,
  chat_topic_id: str | None = None,
  extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
  if store is None or not chat_session_id:
    return {"status": "skipped", "reason": "missing_chat_session"}
  if not hasattr(store, "insert_memory_session_snapshot"):
    return {"status": "skipped", "reason": "memory_framework_unavailable"}
  consistency_jobs = {"seen": 0, "completed": 0, "failed": 0, "skipped": 0}
  if hasattr(store, "list_due_consistency_jobs"):
    try:
      from .consistency_worker import process_due_consistency_jobs

      consistency_jobs = process_due_consistency_jobs(store, user, limit=3)
    except Exception as exc:
      consistency_jobs = {
        "seen": 0,
        "completed": 0,
        "failed": 1,
        "skipped": 0,
        "error": str(exc)[:500],
      }
  if generation_run_id and hasattr(store, "find_memory_session_snapshot_by_run_id"):
    existing_snapshot = store.find_memory_session_snapshot_by_run_id(
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      generation_run_id=generation_run_id,
    )
    if existing_snapshot:
      return {
        "status": "existing",
        "reason": "duplicate_generation_run",
        "snapshot_id": existing_snapshot.get("id"),
        "episode_status": "existing",
        "consistency_jobs": consistency_jobs,
      }
  if generation_run_id and hasattr(store, "claim_memory_checkpoint"):
    claimed = store.claim_memory_checkpoint(
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      generation_run_id=generation_run_id,
      chat_topic_id=chat_topic_id,
    )
    if not claimed:
      commit = (
        store.get_memory_checkpoint_commit(generation_run_id=generation_run_id)
        if hasattr(store, "get_memory_checkpoint_commit")
        else None
      )
      return {
        "status": str((commit or {}).get("status") or "processing"),
        "reason": "generation_run_checkpoint_already_claimed",
        "snapshot_id": (commit or {}).get("snapshot_id"),
        "episode_id": (commit or {}).get("episode_id"),
        "episode_status": "existing",
        "consistency_jobs": consistency_jobs,
      }

  domain = infer_domain(prompt=prompt, project_name=project_name, files=files)
  modules = infer_modules(prompt=prompt, changed_paths=changed_paths)
  prior_state = _get_session_state_for_topic(
    store,
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
  )
  prior_summary = str((prior_state or {}).get("rolling_summary") or "")
  rolling_summary = build_rolling_session_summary(
    prior_summary=prior_summary,
    prompt=prompt,
    intent=intent,
    outcome=outcome,
    changed_paths=changed_paths,
    preview_status=preview_status,
    error_category=error_category,
  )
  authoritative_files = list(files or [])
  if hasattr(store, "list_files"):
    try:
      authoritative_files = list(store.list_files(project_id, user) or [])
    except Exception:
      authoritative_files = list(files or [])
  manifest = build_file_manifest(authoritative_files)
  snapshot_kind = "error_recovery" if error_category else "update_checkpoint"
  episode_payload = build_episode_from_run(
    prompt=prompt,
    intent=intent,
    outcome=outcome,
    changed_paths=changed_paths,
    preview_status=preview_status,
    error_category=error_category,
    domain=domain,
    modules=modules,
    file_count=int(manifest.get("total") or 0),
  )
  episode = None
  episode_status = "skipped"
  episode_skip_reason = "non_episodic_intent"
  should_store_episode = should_write_episodic_episode(
    intent=intent,
    outcome=outcome,
    changed_paths=changed_paths,
    error_category=error_category,
  )
  existing_episode = None
  if should_store_episode and generation_run_id and hasattr(store, "find_memory_episode_by_run_id"):
    existing_episode = store.find_memory_episode_by_run_id(
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      generation_run_id=generation_run_id,
    )
  if existing_episode:
    episode = existing_episode
    episode_status = "existing"
    episode_skip_reason = "duplicate_run"

  recorded_at = datetime.now(timezone.utc).isoformat()
  episode_metadata = {
    "domain": domain,
    "modules": modules,
    "chat_topic_id": chat_topic_id,
    "intent": intent,
    "prompt": prompt.strip()[:600],
    "run_id": generation_run_id,
    "recorded_at": recorded_at,
    **(extra or {}),
  }
  snapshot_metadata = {"chat_topic_id": chat_topic_id, **(extra or {})} if chat_topic_id else (extra or {})
  session_metadata = {"domain": domain, "modules": modules, "chat_topic_id": chat_topic_id, **(extra or {})}
  atomic_used = False
  if hasattr(store, "persist_generation_memory_checkpoint_atomic"):
    atomic_result = store.persist_generation_memory_checkpoint_atomic(
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      generation_run_id=generation_run_id,
      snapshot_kind=snapshot_kind,
      rolling_summary=rolling_summary,
      changed_paths=changed_paths,
      file_manifest=manifest,
      preview_status=preview_status,
      error_category=error_category,
      snapshot_metadata=snapshot_metadata,
      session_metadata=session_metadata,
      file_count=int(manifest.get("total") or 0),
      episode_payload=(
        {"scope": "personal", **episode_payload}
        if should_store_episode and not existing_episode
        else None
      ),
      episode_metadata=episode_metadata,
      existing_episode_id=str((existing_episode or {}).get("id") or "") or None,
    )
    snapshot = atomic_result.get("snapshot") or {}
    session_state = atomic_result.get("session_state") or {}
    if should_store_episode and not existing_episode:
      episode = atomic_result.get("episode")
      episode_status = "stored" if episode else "skipped"
      episode_skip_reason = "" if episode else "atomic_episode_insert_skipped"
    atomic_used = True
  else:
    snapshot = store.insert_memory_session_snapshot(
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      generation_run_id=generation_run_id,
      snapshot_kind=snapshot_kind,
      content=rolling_summary,
      changed_paths=changed_paths,
      file_manifest=manifest,
      preview_status=preview_status,
      error_category=error_category,
      metadata=snapshot_metadata,
    )
    session_state = store.upsert_memory_chat_session_state(
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      rolling_summary=rolling_summary,
      changed_paths=changed_paths,
      preview_status=preview_status,
      error_category=error_category,
      file_count=int(manifest.get("total") or 0),
      generation_run_id=generation_run_id,
      metadata=session_metadata,
    )
    if should_store_episode and not existing_episode:
      episode = store.insert_memory_episode(
        user,
        project_id=project_id,
        chat_session_id=chat_session_id,
        generation_run_id=generation_run_id,
        scope="personal",
        changed_paths=changed_paths,
        chat_topic_id=chat_topic_id,
        metadata=episode_metadata,
        **episode_payload,
      )
      episode_status = "stored"
      episode_skip_reason = ""
  if episode_status == "stored":
    prune_episodic_memories(
      store,
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
    )
    _sync_episode_vector_after_checkpoint(
      store,
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      episode=episode,
    )
  platform_pattern = None
  if episode and hasattr(store, "upsert_memory_platform_pattern"):
    from .platform_learning import maybe_promote_episode_to_platform_pattern

    platform_pattern = maybe_promote_episode_to_platform_pattern(
      store,
      episode=episode,
      domain=domain,
      modules=modules,
      intent=intent,
      error_category=error_category,
      changed_paths=changed_paths,
      preview_status=preview_status,
    )
  turn_learning = {"status": "skipped", "reason": "turn_learning_unavailable"}
  try:
    from .correction_learning import persist_turn_learning

    turn_learning = persist_turn_learning(
      store,
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      changed_paths=changed_paths,
      outcome=outcome,
      error_category=error_category,
    )
  except Exception as exc:
    turn_learning = {
      "status": "failed",
      "reason": "turn_learning_error",
      "error": str(exc)[:500],
    }
  learning_event = {"status": "skipped", "reason": "learning_event_unavailable"}
  try:
    from .learning_events import persist_learning_event_checkpoint

    learning_event = persist_learning_event_checkpoint(
      store,
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      generation_run_id=generation_run_id,
      prompt=prompt,
      intent=intent,
      outcome=outcome,
      domain=domain,
      modules=modules,
      changed_paths=changed_paths,
      preview_status=preview_status,
      error_category=error_category,
      extra={
        "turn_learning": turn_learning,
        **(extra or {}),
      },
    )
  except Exception as exc:
    learning_event = {
      "status": "failed",
      "reason": "learning_event_error",
      "error": str(exc)[:500],
    }
  profile = store.upsert_memory_user_profile(
    user,
    project_id=project_id,
    profile={
      "domain": domain,
      "framework": "vite",
      "language": "javascript",
      "ui_library": "tailwind",
      "current_goal": prompt.strip()[:400],
      "modules": modules,
    },
  ) if hasattr(store, "upsert_memory_user_profile") else None
  result = {
    "status": "stored",
    "snapshot_id": snapshot.get("id"),
    "session_state": session_state,
    "episode_id": (episode or {}).get("id"),
    "episode_status": episode_status,
    "episode_skip_reason": episode_skip_reason or None,
    "platform_pattern_id": (platform_pattern or {}).get("id"),
    "turn_learning": turn_learning,
    "correction_learning": turn_learning,
    "learning_event": learning_event,
    "profile_id": (profile or {}).get("id"),
    "domain": domain,
    "modules": modules,
    "consistency_jobs": consistency_jobs,
    "atomic_checkpoint": atomic_used,
  }
  if generation_run_id and not atomic_used and hasattr(store, "complete_memory_checkpoint"):
    store.complete_memory_checkpoint(
      generation_run_id=generation_run_id,
      snapshot_id=str(snapshot.get("id") or "") or None,
      episode_id=str((episode or {}).get("id") or "") or None,
    )
  return result


def persist_generation_memory_checkpoint(
  store: Any,
  user: Any,
  **kwargs: Any,
) -> dict[str, Any]:
  """Persist a checkpoint and release its claim immediately when any stage fails."""
  try:
    return _persist_generation_memory_checkpoint(store, user, **kwargs)
  except Exception as exc:
    generation_run_id = str(kwargs.get("generation_run_id") or "").strip()
    if generation_run_id and hasattr(store, "fail_memory_checkpoint"):
      try:
        store.fail_memory_checkpoint(
          generation_run_id=generation_run_id,
          error=str(exc),
        )
      except Exception:
        pass
    raise
