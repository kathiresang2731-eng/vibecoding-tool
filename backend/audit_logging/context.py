from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Iterator


@dataclass(frozen=True)
class RunTelemetryContext:
  request_id: str
  user_id: str | None = None
  project_id: str | None = None
  agent_run_id: str | None = None
  generation_run_id: str | None = None

  @classmethod
  def create(
    cls,
    *,
    user_id: str | None = None,
    project_id: str | None = None,
    request_id: str | None = None,
  ) -> "RunTelemetryContext":
    return cls(
      request_id=request_id or str(uuid.uuid4()),
      user_id=user_id,
      project_id=project_id,
    )


_TELEMETRY_CONTEXT: ContextVar[RunTelemetryContext | None] = ContextVar("worktual_telemetry_context", default=None)


def current_telemetry_context() -> RunTelemetryContext | None:
  return _TELEMETRY_CONTEXT.get()


@contextmanager
def telemetry_scope(context: RunTelemetryContext) -> Iterator[RunTelemetryContext]:
  token = _TELEMETRY_CONTEXT.set(context)
  try:
    yield context
  finally:
    _TELEMETRY_CONTEXT.reset(token)


def update_telemetry_context(**changes: Any) -> RunTelemetryContext:
  current = current_telemetry_context() or RunTelemetryContext.create()
  allowed = {key: value for key, value in changes.items() if key in asdict(current)}
  updated = replace(current, **allowed)
  _TELEMETRY_CONTEXT.set(updated)
  return updated


def run_with_telemetry_context(context: RunTelemetryContext | None, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
  if context is None:
    return function(*args, **kwargs)
  with telemetry_scope(context):
    return function(*args, **kwargs)
