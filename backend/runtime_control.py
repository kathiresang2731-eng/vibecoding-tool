from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from typing import Any, Callable, Iterator


CancellationCheck = Callable[[], None]

_CANCELLATION_CHECK: ContextVar[CancellationCheck | None] = ContextVar(
  "worktual_runtime_cancellation_check",
  default=None,
)


@contextmanager
def runtime_cancellation_scope(check: CancellationCheck | None) -> Iterator[None]:
  token = _CANCELLATION_CHECK.set(check)
  try:
    yield
  finally:
    _CANCELLATION_CHECK.reset(token)


def raise_if_runtime_cancelled() -> None:
  check = _CANCELLATION_CHECK.get()
  if check is not None:
    check()


def submit_with_runtime_context(executor: Any, function: Callable[..., Any], /, *args: Any, **kwargs: Any):
  context = copy_context()
  return executor.submit(context.run, function, *args, **kwargs)
