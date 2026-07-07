from __future__ import annotations

from typing import Any


def _process_job(store: Any, user: Any, job: dict[str, Any]) -> None:
  project_id = str(job.get("project_id") or "")
  job_type = str(job.get("job_type") or "")
  payload = job.get("payload_json") if isinstance(job.get("payload_json"), dict) else {}

  if job_type == "project_code_index_refresh":
    from ...storage.projects import (
      _persist_project_code_index_after_reindex,
      _reindex_project_files_after_persist,
    )

    files = list(store.list_files(project_id, user) or [])
    replace_all = bool(payload.get("replace_all"))
    changed_paths = payload.get("changed_paths") if isinstance(payload.get("changed_paths"), list) else None
    if not _reindex_project_files_after_persist(
      project_id,
      files,
      changed_paths=None if replace_all else changed_paths,
    ):
      raise RuntimeError("Code index refresh failed.")
    if not _persist_project_code_index_after_reindex(
      store,
      project_id,
      files,
      replace_all=replace_all,
    ):
      raise RuntimeError("Persistent code index refresh failed.")
    return

  if job_type == "project_ui_knowledge_refresh":
    from ...storage.projects import _refresh_project_ui_knowledge_after_persist

    if not _refresh_project_ui_knowledge_after_persist(
      store,
      project_id,
      user,
      chat_session_id=str(payload.get("chat_session_id") or "") or None,
      chat_topic_id=str(payload.get("chat_topic_id") or "") or None,
      generation_run_id=str(payload.get("generation_run_id") or "") or None,
    ):
      raise RuntimeError("Project UI knowledge refresh failed.")
    return

  if job_type == "episode_vector_upsert":
    from .episode_vector_sync import sync_episode_vector_from_row
    from .episode_vector_store import episode_vector_health

    episode_id = str(payload.get("episode_id") or job.get("target_key") or "")
    episode = store.get_memory_episode(user, project_id=project_id, episode_id=episode_id)
    if not episode:
      raise RuntimeError("Episode no longer exists.")
    session_id = str(episode.get("chat_session_id") or payload.get("chat_session_id") or "")
    vector_health = episode_vector_health()
    if not vector_health["enabled"]:
      store.set_memory_episode_vector_status(episode_id=episode_id, status="disabled")
      return
    ready = sync_episode_vector_from_row(
      episode,
      user_id=str(user.id),
      project_id=project_id,
      chat_session_id=session_id,
    )
    store.set_memory_episode_vector_status(
      episode_id=episode_id,
      status=("ready" if vector_health["durable"] else "volatile") if ready else "failed",
      error="" if ready else "Vector store unavailable.",
    )
    if not ready:
      raise RuntimeError("Episode vector upsert failed.")
    return

  if job_type == "episode_vector_delete":
    from .episode_vector_sync import remove_episode_vector

    episode_id = str(payload.get("episode_id") or job.get("target_key") or "")
    if not remove_episode_vector(episode_id=episode_id):
      raise RuntimeError("Episode vector delete failed.")
    return

  raise RuntimeError(f"Unsupported consistency job type: {job_type}")


def process_due_consistency_jobs(
  store: Any,
  user: Any,
  *,
  limit: int = 10,
) -> dict[str, int]:
  """Process retryable derived-state jobs for the supplied user."""
  if not all(
    hasattr(store, name)
    for name in (
      "list_due_consistency_jobs",
      "mark_consistency_job_processing",
      "complete_consistency_job",
      "fail_consistency_job",
    )
  ):
    return {"seen": 0, "completed": 0, "failed": 0, "skipped": 0}
  if hasattr(store, "enqueue_pending_episode_vector_jobs"):
    store.enqueue_pending_episode_vector_jobs(user, limit=limit)
  try:
    jobs = list(
      store.list_due_consistency_jobs(
        limit=limit,
        user_id=str(getattr(user, "id", "")) or None,
      )
      or []
    )
  except TypeError:
    jobs = list(store.list_due_consistency_jobs(limit=limit) or [])
  result = {"seen": len(jobs), "completed": 0, "failed": 0, "skipped": 0}
  for job in jobs:
    if str(job.get("user_id") or "") not in {"", str(getattr(user, "id", ""))}:
      result["skipped"] += 1
      continue
    job_id = str(job.get("id") or "")
    if not job_id or not store.mark_consistency_job_processing(job_id=job_id):
      result["skipped"] += 1
      continue
    try:
      _process_job(store, user, job)
      store.complete_consistency_job(job_id=job_id)
      result["completed"] += 1
    except Exception as exc:
      attempt = int(job.get("attempt_count") or 0) + 1
      retry_seconds = min(3600, 30 * (2 ** max(0, attempt - 1)))
      store.fail_consistency_job(
        job_id=job_id,
        error=str(exc),
        retry_seconds=retry_seconds,
      )
      result["failed"] += 1
  return result
