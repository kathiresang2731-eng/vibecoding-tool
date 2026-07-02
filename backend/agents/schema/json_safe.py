from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from typing import Any


_DROP = object()

RUNTIME_ONLY_STATE_KEYS = {
  "_dynamic_agent_registry",
  "_active_mas_action",
  "provider",
  "control_provider",
  "artifact_provider",
  "client",
  "registry",
  "execute_tool",
  "tool_executor",
  "tool_context",
  "progress",
  "progress_callback",
  "callback",
  "callbacks",
  "runtime_objects",
}

MINIMAL_OBJECT_ATTRIBUTES = (
  "id",
  "name",
  "model",
  "provider_role",
  "status",
  "email",
  "project_id",
  "agent_id",
  "thread_id",
)


def json_safe_value(value: Any) -> Any:
  sanitized = _sanitize_value(value, drop_runtime_keys=False, stringify_unknown=True)
  return None if sanitized is _DROP else sanitized


def sanitize_for_persistence(value: Any) -> Any:
  sanitized = _sanitize_value(value, drop_runtime_keys=True, stringify_unknown=False)
  return None if sanitized is _DROP else sanitized


def sanitize_for_checkpoint(value: Any) -> Any:
  sanitized = _sanitize_value(value, drop_runtime_keys=True, stringify_unknown=False)
  return None if sanitized is _DROP else sanitized


def _msgpack_pack(value: Any) -> None:
  import msgpack

  msgpack.packb(value, use_bin_type=True, strict_types=True)


def _is_msgpack_serializable(value: Any) -> bool:
  try:
    _msgpack_pack(value)
    return True
  except ModuleNotFoundError:
    import json

    try:
      json.dumps(value, ensure_ascii=False)
      return True
    except Exception:
      return False
  except Exception:
    return False


def ensure_msgpack_serializable(value: Any, *, context: str = "payload") -> Any:
  del context  # reserved for diagnostics; persistence must not fail on bad runtime objects.
  candidates: list[Any] = [
    sanitize_for_checkpoint(value),
    _sanitize_value(value, drop_runtime_keys=True, stringify_unknown=True),
    json_safe_value(value),
  ]
  for sanitized in candidates:
    if sanitized is _DROP:
      sanitized = None
    if _is_msgpack_serializable(sanitized):
      return sanitized
  if isinstance(value, dict):
    return {}
  if isinstance(value, (list, tuple, set, frozenset)):
    return []
  return None


def assert_msgpack_serializable(value: Any, context: str = "payload") -> Any:
  ensured = ensure_msgpack_serializable(value, context=context)
  if not _is_msgpack_serializable(ensured):
    raise TypeError(f"{context} is not MessagePack serializable after sanitization")
  return ensured


def sanitize_and_validate_for_checkpoint(value: Any, context: str = "checkpoint") -> Any:
  return ensure_msgpack_serializable(value, context=context)


def sanitize_and_validate_for_persistence(value: Any, context: str = "persistence") -> Any:
  sanitized = sanitize_for_persistence(value)
  if sanitized is _DROP:
    sanitized = None
  return ensure_msgpack_serializable(sanitized, context=context)


def json_dumps_for_persistence(value: Any, *, context: str = "persistence", ensure_ascii: bool = False) -> str:
  safe_value = sanitize_and_validate_for_persistence(value, context=context)
  return json.dumps(safe_value, ensure_ascii=ensure_ascii)


def sanitize_graph_node_state(state: dict[str, Any]) -> dict[str, Any]:
  scrub_runtime_objects_from_state(state)
  ensured = ensure_msgpack_serializable(state, context="langgraph.node_state")
  return ensured if isinstance(ensured, dict) else {}


def scrub_runtime_objects_from_state(state: dict[str, Any]) -> None:
  """Remove live runtime objects from graph state before checkpoint persistence."""
  if not isinstance(state, dict):
    return
  for key in list(state.keys()):
    if str(key) in RUNTIME_ONLY_STATE_KEYS:
      state.pop(key, None)
  registry = state.get("dynamic_agent_registry")
  if _is_agent_registry(registry):
    snapshot = getattr(registry, "snapshot", None)
    if callable(snapshot):
      try:
        state["dynamic_agent_registry"] = snapshot()
      except Exception:
        state.pop("dynamic_agent_registry", None)
    else:
      state.pop("dynamic_agent_registry", None)


def _sanitize_value(
  value: Any,
  *,
  drop_runtime_keys: bool,
  stringify_unknown: bool,
  _seen: set[int] | None = None,
  _depth: int = 0,
) -> Any:
  if _depth > 50:
    return _DROP
  if value is None or isinstance(value, (str, int, float, bool)):
    return value
  if isinstance(value, bytes):
    return value.decode("utf-8", errors="replace")

  _seen = _seen or set()
  value_id = id(value)
  if value_id in _seen:
    return _DROP

  if isinstance(value, dict):
    _seen.add(value_id)
    sanitized_dict: dict[str, Any] = {}
    for key, item in list(value.items()):
      key_text = str(key)
      if drop_runtime_keys and key_text in RUNTIME_ONLY_STATE_KEYS:
        continue
      sanitized_item = _sanitize_value(
        item,
        drop_runtime_keys=drop_runtime_keys,
        stringify_unknown=stringify_unknown,
        _seen=_seen,
        _depth=_depth + 1,
      )
      if sanitized_item is not _DROP:
        sanitized_dict[key_text] = sanitized_item
    _seen.discard(value_id)
    return sanitized_dict

  if isinstance(value, (list, tuple, set, frozenset)):
    _seen.add(value_id)
    sanitized_items: list[Any] = []
    for item in value:
      sanitized_item = _sanitize_value(
        item,
        drop_runtime_keys=drop_runtime_keys,
        stringify_unknown=stringify_unknown,
        _seen=_seen,
        _depth=_depth + 1,
      )
      if sanitized_item is not _DROP:
        sanitized_items.append(sanitized_item)
    _seen.discard(value_id)
    return sanitized_items

  interrupt_value = getattr(value, "value", None)
  if interrupt_value is not None and (
    type(value).__name__ == "Interrupt"
    or hasattr(value, "interrupt_id")
    or hasattr(value, "id")
  ):
    interrupt_id = getattr(value, "id", None) or getattr(value, "interrupt_id", None)
    return {
      "type": "langgraph_interrupt",
      "interrupt_id": str(interrupt_id) if interrupt_id is not None else "",
      "value": _sanitize_value(
        interrupt_value,
        drop_runtime_keys=drop_runtime_keys,
        stringify_unknown=stringify_unknown,
        _seen=_seen,
        _depth=_depth + 1,
      ),
    }

  if isinstance(value, BaseException):
    return {"type": type(value).__name__, "message": str(value)[:1200]}

  converted = _convert_known_object(value)
  if converted is not _DROP:
    return _sanitize_value(
      converted,
      drop_runtime_keys=drop_runtime_keys,
      stringify_unknown=stringify_unknown,
      _seen=_seen,
      _depth=_depth + 1,
    )

  metadata = _minimal_object_metadata(value)
  if metadata:
    return metadata

  if stringify_unknown:
    return str(value)
  return _DROP


def _convert_known_object(value: Any) -> Any:
  if _is_agent_registry(value):
    snapshot = getattr(value, "snapshot", None)
    if callable(snapshot):
      try:
        return snapshot()
      except Exception:
        return _DROP

  if is_dataclass(value) and not isinstance(value, type):
    try:
      return asdict(value)
    except Exception:
      return _DROP

  for method_name in ("model_dump", "dict", "to_dict", "snapshot"):
    method = getattr(value, method_name, None)
    if not callable(method):
      continue
    try:
      return method()
    except TypeError:
      try:
        return method(exclude_none=True)
      except Exception:
        continue
    except Exception:
      continue
  return _DROP


def _is_agent_registry(value: Any) -> bool:
  return type(value).__name__ == "AgentRegistry" and hasattr(value, "agents") and hasattr(value, "snapshot")


def _minimal_object_metadata(value: Any) -> dict[str, Any]:
  metadata: dict[str, Any] = {"type": type(value).__name__}
  for attribute in MINIMAL_OBJECT_ATTRIBUTES:
    try:
      item = getattr(value, attribute)
    except Exception:
      continue
    if item is None or callable(item):
      continue
    if isinstance(item, (str, int, float, bool)):
      metadata[attribute] = item
  return metadata if len(metadata) > 1 else {}
