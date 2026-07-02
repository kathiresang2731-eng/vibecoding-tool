from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, Lock
from typing import Iterator
from uuid import uuid4


class ProjectGenerationAlreadyRunningError(RuntimeError):
  pass


class ProjectGenerationCancelledError(RuntimeError):
  pass


@dataclass
class ActiveProjectRun:
  project_id: str
  user_id: str
  run_id: str
  started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
  cancel_event: Event = field(default_factory=Event)
  finished_event: Event = field(default_factory=Event)
  status: str = "running"

  def snapshot(self) -> dict[str, str | bool | float]:
    return {
      "project_id": self.project_id,
      "user_id": self.user_id,
      "run_id": self.run_id,
      "started_at": self.started_at.isoformat(),
      "cancel_requested": self.cancel_event.is_set(),
      "stopped": self.finished_event.is_set(),
      "status": self.status,
    }


_RUNS_LOCK = Lock()
_ACTIVE_RUNS: dict[str, ActiveProjectRun] = {}


@contextmanager
def acquire_project_run_lock(project_id: str, *, user_id: str | None = None) -> Iterator[ActiveProjectRun]:
  normalized_project_id = str(project_id or "").strip()
  if not normalized_project_id:
    raise ProjectGenerationAlreadyRunningError("Project id is required before starting generation.")

  run = ActiveProjectRun(
    project_id=normalized_project_id,
    user_id=str(user_id or ""),
    run_id=uuid4().hex,
  )
  with _RUNS_LOCK:
    existing = _ACTIVE_RUNS.get(normalized_project_id)
    if existing is not None:
      raise ProjectGenerationAlreadyRunningError(
        "Another generation or update is already running for this project. "
        "Wait for the active run to finish or cancel it before starting a new update."
      )
    _ACTIVE_RUNS[normalized_project_id] = run

  try:
    yield run
  except ProjectGenerationCancelledError:
    run.status = "cancelled"
    raise
  except Exception:
    run.status = "failed"
    raise
  else:
    run.status = "cancelled" if run.cancel_event.is_set() else "completed"
  finally:
    run.finished_event.set()
    with _RUNS_LOCK:
      if _ACTIVE_RUNS.get(normalized_project_id) is run:
        _ACTIVE_RUNS.pop(normalized_project_id, None)


def active_project_run(project_id: str, *, user_id: str | None = None) -> dict[str, str | bool | float] | None:
  with _RUNS_LOCK:
    run = _ACTIVE_RUNS.get(str(project_id or "").strip())
    if run is not None and user_id and run.user_id and run.user_id != str(user_id):
      return None
    return run.snapshot() if run else None


def cancel_project_run(
  project_id: str,
  *,
  user_id: str | None = None,
  run_id: str | None = None,
  wait_seconds: float = 0.0,
) -> dict[str, str | bool | float] | None:
  with _RUNS_LOCK:
    run = _ACTIVE_RUNS.get(str(project_id or "").strip())
    if run is None:
      return None
    if user_id and run.user_id and run.user_id != str(user_id):
      return None
    if run_id and run.run_id != str(run_id):
      return None
    run.status = "cancelling"
    run.cancel_event.set()
  if wait_seconds > 0:
    run.finished_event.wait(timeout=max(0.0, min(float(wait_seconds), 5.0)))
  return run.snapshot()


def raise_if_project_run_cancelled(run: ActiveProjectRun | None) -> None:
  if run is not None and run.cancel_event.is_set():
    raise ProjectGenerationCancelledError(
      "Generation was cancelled by the user. No further model calls, tools, validation steps, or file writes will start."
    )


def raise_if_project_cancelled(project_id: str) -> None:
  """Raise when the active project run was cancelled (for parallel worker wave boundaries)."""
  normalized_project_id = str(project_id or "").strip()
  if not normalized_project_id:
    return
  with _RUNS_LOCK:
    run = _ACTIVE_RUNS.get(normalized_project_id)
    if run is not None and run.cancel_event.is_set():
      raise ProjectGenerationCancelledError(
        "Generation was cancelled by the user. No further parallel worker activity will start."
      )
