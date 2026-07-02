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
  _ = prompt, files
  name = str(project_name or "").strip().lower()
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
  manifest: dict[str, Any] = {"paths": [], "counts": {}}
  for item in files[:limit]:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").strip()
    if not path:
      continue
    manifest["paths"].append(path)
    prefix = path.split("/", 1)[0] if "/" in path else "root"
    manifest["counts"][prefix] = int(manifest["counts"].get(prefix) or 0) + 1
  manifest["total"] = len(manifest["paths"])
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


def persist_generation_memory_checkpoint(
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
  extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
  if store is None or not chat_session_id:
    return {"status": "skipped", "reason": "missing_chat_session"}
  if not hasattr(store, "insert_memory_session_snapshot"):
    return {"status": "skipped", "reason": "memory_framework_unavailable"}

  domain = infer_domain(prompt=prompt, project_name=project_name, files=files)
  modules = infer_modules(prompt=prompt, changed_paths=changed_paths)
  prior_state = store.get_memory_chat_session_state(user, chat_session_id=chat_session_id) if hasattr(store, "get_memory_chat_session_state") else None
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
  manifest = build_file_manifest(files or [])
  snapshot_kind = "error_recovery" if error_category else "update_checkpoint"
  snapshot = store.insert_memory_session_snapshot(
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    generation_run_id=generation_run_id,
    snapshot_kind=snapshot_kind,
    content=rolling_summary,
    changed_paths=changed_paths,
    file_manifest=manifest,
    preview_status=preview_status,
    error_category=error_category,
    metadata=extra or {},
  )
  session_state = store.upsert_memory_chat_session_state(
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    rolling_summary=rolling_summary,
    changed_paths=changed_paths,
    preview_status=preview_status,
    error_category=error_category,
    file_count=int(manifest.get("total") or 0),
    generation_run_id=generation_run_id,
    metadata={"domain": domain, "modules": modules, **(extra or {})},
  )
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
  if should_write_episodic_episode(
    intent=intent,
    outcome=outcome,
    changed_paths=changed_paths,
    error_category=error_category,
  ):
    existing_episode = None
    if generation_run_id and hasattr(store, "find_memory_episode_by_run_id"):
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
    else:
      recorded_at = datetime.now(timezone.utc).isoformat()
      episode = store.insert_memory_episode(
        user,
        project_id=project_id,
        chat_session_id=chat_session_id,
        generation_run_id=generation_run_id,
        scope="personal",
        changed_paths=changed_paths,
        metadata={
          "domain": domain,
          "modules": modules,
          "intent": intent,
          "prompt": prompt.strip()[:600],
          "run_id": generation_run_id,
          "recorded_at": recorded_at,
          **(extra or {}),
        },
        **episode_payload,
      )
      episode_status = "stored"
      episode_skip_reason = ""
      prune_episodic_memories(
        store,
        user,
        project_id=project_id,
        chat_session_id=chat_session_id,
      )
      try:
        from .episode_vector_sync import sync_episode_vector_from_row

        sync_episode_vector_from_row(
          episode,
          user_id=str(user.id),
          project_id=project_id,
          chat_session_id=chat_session_id,
        )
      except Exception:
        pass
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
  return {
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
  }
