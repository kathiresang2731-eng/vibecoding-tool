from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from .consistency_worker import process_due_consistency_jobs

logger = logging.getLogger(__name__)


def run_consistency_cycle(
  store: Any,
  *,
  batch_size: int = 20,
  lock_timeout_seconds: int = 300,
) -> dict[str, int]:
  result = {
    "recovered": 0,
    "users": 0,
    "seen": 0,
    "completed": 0,
    "failed": 0,
    "skipped": 0,
  }
  if hasattr(store, "recover_stale_consistency_jobs"):
    result["recovered"] = int(
      store.recover_stale_consistency_jobs(
        lock_timeout_seconds=lock_timeout_seconds,
      )
      or 0
    )
  jobs = list(store.list_due_consistency_jobs(limit=batch_size) or [])
  user_ids = {
    str(job.get("user_id") or "")
    for job in jobs
    if isinstance(job, dict) and job.get("user_id")
  }
  for user_id in sorted(user_ids):
    user = store.get_user_by_id(user_id) if hasattr(store, "get_user_by_id") else None
    if user is None or not getattr(user, "is_active", True):
      result["skipped"] += sum(1 for job in jobs if str(job.get("user_id") or "") == user_id)
      continue
    processed = process_due_consistency_jobs(store, user, limit=batch_size)
    result["users"] += 1
    for key in ("seen", "completed", "failed", "skipped"):
      result[key] += int(processed.get(key) or 0)
  return result


async def consistency_worker_loop(
  store: Any,
  *,
  interval_seconds: int = 15,
  batch_size: int = 20,
  lock_timeout_seconds: int = 300,
) -> None:
  interval = max(1, int(interval_seconds))
  while True:
    try:
      await asyncio.to_thread(
        run_consistency_cycle,
        store,
        batch_size=batch_size,
        lock_timeout_seconds=lock_timeout_seconds,
      )
    except asyncio.CancelledError:
      raise
    except Exception:
      logger.exception("Memory consistency worker cycle failed.")
    await asyncio.sleep(interval)


def start_consistency_worker(
  store: Any,
  *,
  interval_seconds: int = 15,
  batch_size: int = 20,
  lock_timeout_seconds: int = 300,
) -> asyncio.Task[None]:
  return asyncio.create_task(
    consistency_worker_loop(
      store,
      interval_seconds=interval_seconds,
      batch_size=batch_size,
      lock_timeout_seconds=lock_timeout_seconds,
    ),
    name="worktual-memory-consistency",
  )


async def stop_consistency_worker(task: asyncio.Task[None] | None) -> None:
  if task is None:
    return
  task.cancel()
  with suppress(asyncio.CancelledError):
    await task
