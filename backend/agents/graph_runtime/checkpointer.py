from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig

from ..schema.json_safe import (
  ensure_msgpack_serializable,
  sanitize_and_validate_for_checkpoint,
  sanitize_for_checkpoint,
)

try:
  from langgraph.checkpoint.memory import MemorySaver
  from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
except ImportError:
  MemorySaver = None  # type: ignore[misc, assignment]
  JsonPlusSerializer = None  # type: ignore[misc, assignment]


def _default_langgraph_serde() -> Any:
  if JsonPlusSerializer is None:
    return None
  return JsonPlusSerializer()


class SanitizingSerializer:
  """LangGraph serde wrapper that sanitizes values before MessagePack encoding."""

  def __init__(self, inner: Any) -> None:
    self._inner = inner

  def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
    safe_obj = ensure_msgpack_serializable(obj, context="langgraph.serde")
    return self._inner.dumps_typed(safe_obj)

  def loads_typed(self, data: tuple[str, bytes]) -> Any:
    return self._inner.loads_typed(data)

  def with_msgpack_allowlist(self, extra_allowlist: Any) -> Any:
    inner = self._inner
    method = getattr(inner, "with_msgpack_allowlist", None)
    if callable(method):
      return SanitizingSerializer(method(extra_allowlist))
    return self


def _sanitize_checkpoint_writes(
  writes: Sequence[tuple[str, Any]],
  *,
  context: str,
) -> list[tuple[str, Any]]:
  return [
    (channel, ensure_msgpack_serializable(value, context=context))
    for channel, value in writes
  ]


if MemorySaver is not None:

  class SanitizingMemorySaver(MemorySaver):
    """In-memory LangGraph saver that never persists non-serializable runtime objects."""

    def __init__(self, *, serde: Any | None = None) -> None:
      inner_serde = serde or _default_langgraph_serde()
      wrapped_serde = SanitizingSerializer(inner_serde) if inner_serde is not None else inner_serde
      super().__init__(serde=wrapped_serde)

    def put(
      self,
      config: RunnableConfig,
      checkpoint: dict[str, Any],
      metadata: dict[str, Any],
      new_versions: dict[str, Any],
    ) -> RunnableConfig:
      safe_config = sanitize_for_checkpoint(config)
      safe_checkpoint = sanitize_and_validate_for_checkpoint(checkpoint, context="langgraph.checkpoint")
      safe_metadata = sanitize_for_checkpoint(metadata)
      safe_new_versions = sanitize_for_checkpoint(new_versions)
      return super().put(safe_config, safe_checkpoint, safe_metadata, safe_new_versions)

    def put_writes(
      self,
      config: RunnableConfig,
      writes: Sequence[tuple[str, Any]],
      task_id: str,
      task_path: str = "",
    ) -> None:
      safe_writes = _sanitize_checkpoint_writes(writes, context="langgraph.put_writes")
      safe_config = sanitize_for_checkpoint(config)
      super().put_writes(safe_config, safe_writes, task_id, task_path)

    async def aput(
      self,
      config: RunnableConfig,
      checkpoint: dict[str, Any],
      metadata: dict[str, Any],
      new_versions: dict[str, Any],
    ) -> RunnableConfig:
      safe_config = sanitize_for_checkpoint(config)
      safe_checkpoint = sanitize_and_validate_for_checkpoint(checkpoint, context="langgraph.checkpoint")
      safe_metadata = sanitize_for_checkpoint(metadata)
      safe_new_versions = sanitize_for_checkpoint(new_versions)
      return await super().aput(safe_config, safe_checkpoint, safe_metadata, safe_new_versions)

    async def aput_writes(
      self,
      config: RunnableConfig,
      writes: Sequence[tuple[str, Any]],
      task_id: str,
      task_path: str = "",
    ) -> None:
      safe_writes = _sanitize_checkpoint_writes(writes, context="langgraph.aput_writes")
      safe_config = sanitize_for_checkpoint(config)
      await super().aput_writes(safe_config, safe_writes, task_id, task_path)

  class PostgresMirrorCheckpointer(SanitizingMemorySaver):
    """In-memory LangGraph saver that mirrors checkpoints into Postgres audit tables."""

    def __init__(
      self,
      *,
      store: Any | None = None,
      user: Any | None = None,
      agent_run_id: str | None = None,
      project_id: str | None = None,
    ) -> None:
      super().__init__()
      self._store = store
      self._user = user
      self._agent_run_id = agent_run_id
      self._project_id = project_id

    def put(
      self,
      config: RunnableConfig,
      checkpoint: dict[str, Any],
      metadata: dict[str, Any],
      new_versions: dict[str, Any],
    ) -> RunnableConfig:
      result = super().put(config, checkpoint, metadata, new_versions)
      safe_config = sanitize_for_checkpoint(config)
      safe_checkpoint = sanitize_and_validate_for_checkpoint(checkpoint, context="langgraph.checkpoint")
      safe_metadata = sanitize_for_checkpoint(metadata)
      self._mirror_checkpoint(safe_config, safe_checkpoint, safe_metadata)
      return result

    def _mirror_checkpoint(self, config: dict[str, Any], checkpoint: dict[str, Any], metadata: dict[str, Any]) -> None:
      if self._store is None or self._user is None or not self._agent_run_id:
        return
      record = getattr(self._store, "record_generation_checkpoint", None)
      if not callable(record):
        return
      configurable = config.get("configurable") if isinstance(config, dict) else {}
      thread_id = str((configurable or {}).get("thread_id") or "")
      channel_values = checkpoint.get("channel_values") if isinstance(checkpoint, dict) else {}
      step_name = str(metadata.get("source") or metadata.get("step") or "langgraph.checkpoint")
      try:
        record(
          self._agent_run_id,
          self._user,
          thread_id=thread_id,
          step_name=step_name[:120],
          state={
            "thread_id": thread_id,
            "project_id": self._project_id,
            "checkpoint_metadata": metadata,
            "channel_keys": sorted(channel_values.keys()) if isinstance(channel_values, dict) else [],
          },
        )
      except Exception:
        return

else:

  class SanitizingMemorySaver:  # type: ignore[no-redef]
    pass

  class PostgresMirrorCheckpointer:  # type: ignore[no-redef]
    pass


def langgraph_checkpoint_enabled() -> bool:
  try:
    from ..runtime_config import langgraph_checkpoint_enabled as parity_checkpoint_enabled

    return parity_checkpoint_enabled()
  except ImportError:
    raw = str(os.getenv("LANGGRAPH_CHECKPOINT_ENABLED", "")).strip().lower()
    if raw in {"0", "false", "no", "off"}:
      return False
    if raw in {"1", "true", "yes", "on"}:
      return True
    return False


def build_runtime_checkpointer(
  *,
  store: Any | None = None,
  user: Any | None = None,
  agent_run_id: str | None = None,
  project_id: str | None = None,
) -> Any | None:
  if MemorySaver is None:
    return None
  if not langgraph_checkpoint_enabled():
    return None
  if store is not None and user is not None and agent_run_id:
    return PostgresMirrorCheckpointer(
      store=store,
      user=user,
      agent_run_id=agent_run_id,
      project_id=project_id,
    )
  return SanitizingMemorySaver()
