from __future__ import annotations

import functools
import inspect
import os
import time
from contextvars import ContextVar
from typing import Any, Callable, TypeVar, get_type_hints


F = TypeVar("F", bound=Callable[..., Any])
_FLOW_TRACE_EVENTS: ContextVar[list[dict[str, Any]] | None] = ContextVar("worktual_backend_flow_trace_events", default=None)
_MAX_CAPTURED_TRACE_EVENTS = 400


def backend_trace_enabled() -> bool:
  value = os.getenv("WORKTUAL_BACKEND_FLOW_TRACE", "0").strip().lower()
  return value not in {"0", "false", "no", "off"}


def _short(value: Any, *, max_chars: int = 180) -> str:
  text = str(value)
  if len(text) <= max_chars:
    return text
  return f"{text[:max_chars]}..."


def _class_name(function: Callable[..., Any], args: tuple[Any, ...]) -> str:
  qualname = getattr(function, "__qualname__", "")
  if "." in qualname:
    owner = qualname.split(".", 1)[0]
    if owner != "<locals>":
      return owner
  if args:
    owner = args[0].__class__.__name__
    if owner not in {"str", "dict", "list", "tuple", "int", "float", "bool"}:
      return owner
  return "-"


def _format_metadata(metadata: dict[str, Any]) -> str:
  clean = {
    key: _short(value)
    for key, value in metadata.items()
    if value is not None and value != ""
  }
  if not clean:
    return ""
  return " " + " ".join(f"{key}={value}" for key, value in clean.items())


def trace_print(phase: str, *, file: str, function: str, class_name: str = "-", **metadata: Any) -> None:
  module_file = file.rsplit("/", 1)[-1]
  _record_trace_event(
    phase=phase,
    file=file,
    module_file=module_file,
    function=function,
    class_name=class_name,
    metadata=metadata,
  )
  if not backend_trace_enabled():
    return
  print(
    f"[BackendFlow] {phase} file={module_file} class={class_name} function={function}"
    f"{_format_metadata(metadata)}",
    flush=True,
  )


def trace_function(**metadata_getters: Callable[..., Any] | Any) -> Callable[[F], F]:
  def decorator(function: F) -> F:
    function_signature = inspect.signature(function)
    try:
      resolved_annotations = get_type_hints(function)
    except Exception:
      resolved_annotations = getattr(function, "__annotations__", {})
    if resolved_annotations:
      signature_parameters = [
        parameter.replace(annotation=resolved_annotations.get(name, parameter.annotation))
        for name, parameter in function_signature.parameters.items()
      ]
      function_signature = function_signature.replace(
        parameters=signature_parameters,
        return_annotation=resolved_annotations.get("return", function_signature.return_annotation),
      )

    async def _call_async(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
      return await function(*args, **kwargs)

    def _call_sync(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
      return function(*args, **kwargs)

    def _before(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[str, str, str, dict[str, Any], float]:
      file = getattr(function, "__code__", None).co_filename if getattr(function, "__code__", None) else getattr(function, "__module__", "")
      function_name = getattr(function, "__name__", "unknown")
      class_name = _class_name(function, args)
      metadata = _resolve_metadata(metadata_getters, args, kwargs)
      trace_print("ENTER", file=file, class_name=class_name, function=function_name, **metadata)
      return file, function_name, class_name, metadata, time.monotonic()

    def _after(file: str, function_name: str, class_name: str, started_at: float) -> None:
      trace_print(
        "EXIT",
        file=file,
        class_name=class_name,
        function=function_name,
        duration_ms=round((time.monotonic() - started_at) * 1000, 2),
      )

    def _error(file: str, function_name: str, class_name: str, started_at: float, exc: Exception) -> None:
      trace_print(
        "ERROR",
        file=file,
        class_name=class_name,
        function=function_name,
        duration_ms=round((time.monotonic() - started_at) * 1000, 2),
        error=_short(exc),
      )

    if inspect.iscoroutinefunction(function):
      @functools.wraps(function)
      async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        if not backend_trace_enabled():
          return await _call_async(args, kwargs)
        file, function_name, class_name, _metadata, started_at = _before(args, kwargs)
        try:
          result = await _call_async(args, kwargs)
        except Exception as exc:
          _error(file, function_name, class_name, started_at, exc)
          raise
        _after(file, function_name, class_name, started_at)
        return result

      async_wrapper.__signature__ = function_signature  # type: ignore[attr-defined]
      async_wrapper.__annotations__ = resolved_annotations
      return async_wrapper  # type: ignore[return-value]

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
      if not backend_trace_enabled():
        return _call_sync(args, kwargs)
      file, function_name, class_name, _metadata, started_at = _before(args, kwargs)
      try:
        result = _call_sync(args, kwargs)
      except Exception as exc:
        _error(file, function_name, class_name, started_at, exc)
        raise
      _after(file, function_name, class_name, started_at)
      return result

    wrapper.__signature__ = function_signature  # type: ignore[attr-defined]
    wrapper.__annotations__ = resolved_annotations
    return wrapper  # type: ignore[return-value]

  return decorator


def _resolve_metadata(
  metadata_getters: dict[str, Callable[..., Any] | Any],
  args: tuple[Any, ...],
  kwargs: dict[str, Any],
) -> dict[str, Any]:
  metadata: dict[str, Any] = {}
  for key, getter in metadata_getters.items():
    try:
      metadata[key] = getter(*args, **kwargs) if callable(getter) else getter
    except Exception:
      metadata[key] = "unavailable"
  return metadata


def begin_backend_flow_capture() -> None:
  _FLOW_TRACE_EVENTS.set([])


def snapshot_backend_flow_capture() -> dict[str, Any]:
  events = list(_FLOW_TRACE_EVENTS.get() or [])
  files_in_order: list[str] = []
  functions_by_file: dict[str, list[str]] = {}
  process: list[str] = []
  seen_files: set[str] = set()
  seen_process: set[str] = set()

  for event in events:
    file_path = str(event.get("file") or "").strip()
    function = str(event.get("function") or "").strip()
    class_name = str(event.get("class_name") or "").strip()
    phase = str(event.get("phase") or "").strip()
    if file_path and file_path not in seen_files:
      seen_files.add(file_path)
      files_in_order.append(file_path)
    if file_path and function:
      label = f"{class_name}.{function}" if class_name and class_name != "-" else function
      existing = functions_by_file.setdefault(file_path, [])
      if label not in existing:
        existing.append(label)
    if function and phase:
      process_label = f"{phase.lower()}.{function}"
      if process_label not in seen_process:
        seen_process.add(process_label)
        process.append(process_label)

  return {
    "events": events,
    "files": files_in_order,
    "functions_by_file": functions_by_file,
    "process": process,
  }


def clear_backend_flow_capture() -> None:
  _FLOW_TRACE_EVENTS.set([])


def _record_trace_event(
  *,
  phase: str,
  file: str,
  module_file: str,
  function: str,
  class_name: str,
  metadata: dict[str, Any],
) -> None:
  current = _FLOW_TRACE_EVENTS.get()
  if current is None:
    return
  if len(current) >= _MAX_CAPTURED_TRACE_EVENTS:
    return
  current.append(
    {
      "phase": str(phase or "").strip(),
      "file": str(file or "").strip(),
      "module_file": str(module_file or "").strip(),
      "function": str(function or "").strip(),
      "class_name": str(class_name or "").strip(),
      "metadata": {
        key: _short(value, max_chars=120)
        for key, value in metadata.items()
        if value is not None and value != ""
      },
    }
  )
