from __future__ import annotations

from typing import Any

_USAGE_STORE: Any | None = None


def bind_usage_store(store: Any) -> None:
  global _USAGE_STORE
  _USAGE_STORE = store


def record_user_token_usage_from_logger(
  user_id: str | None,
  tokens: int,
  *,
  payload: dict[str, Any] | None = None,
  telemetry: Any | None = None,
  duration_ms: float | int | None = None,
) -> None:
  if not user_id or not _USAGE_STORE:
    return
  usage_payload = payload or {}
  if hasattr(_USAGE_STORE, "record_user_token_usage_event"):
    try:
      _USAGE_STORE.record_user_token_usage_event(
        str(user_id),
        project_id=getattr(telemetry, "project_id", None),
        request_id=getattr(telemetry, "request_id", None),
        generation_run_id=getattr(telemetry, "generation_run_id", None),
        agent_run_id=getattr(telemetry, "agent_run_id", None),
        provider=str(usage_payload.get("provider") or "gemini"),
        model=str(usage_payload.get("model") or ""),
        call=str(usage_payload.get("call") or ""),
        input_tokens=int(usage_payload.get("input_tokens") or 0),
        output_tokens=int(usage_payload.get("output_tokens") or 0),
        total_tokens=int(tokens or usage_payload.get("total_tokens") or 0),
        thought_tokens=int(usage_payload.get("thought_tokens") or 0),
        cached_tokens=int(usage_payload.get("cached_tokens") or 0),
        cached_input_tokens=int(usage_payload.get("cached_input_tokens") or usage_payload.get("cached_tokens") or 0),
        prompt_chars=int(usage_payload.get("prompt_chars") or 0),
        output_chars=int(usage_payload.get("output_chars") or 0),
        estimated_cost_usd=usage_payload.get("estimated_cost_usd"),
        estimated_credits=usage_payload.get("estimated_credits"),
        pricing_version=str(usage_payload.get("pricing_version") or ""),
        route=str(usage_payload.get("route") or ""),
        execution_stage=str(usage_payload.get("execution_stage") or ""),
        model_role=str(usage_payload.get("model_role") or ""),
        thinking_level=str(usage_payload.get("thinking_level") or ""),
        context_chars=int(usage_payload.get("context_chars") or usage_payload.get("prompt_chars") or 0),
        duration_ms=duration_ms,
        metadata={
          "source": "gemini_token_usage_logger",
          "finish_reason": usage_payload.get("finish_reason") or "",
          "pricing_version": usage_payload.get("pricing_version") or "",
          "prompt_fragments_used": usage_payload.get("prompt_fragments_used") or [],
          "input_chars": int(usage_payload.get("input_chars") or 0),
          "system_instruction_chars": int(usage_payload.get("system_instruction_chars") or 0),
          "chat_history_chars": int(usage_payload.get("chat_history_chars") or 0),
          "tool_schema_chars": int(usage_payload.get("tool_schema_chars") or 0),
          "selected_files": usage_payload.get("selected_files") or [],
          "memory_items_used": int(usage_payload.get("memory_items_used") or 0),
        },
      )
    except Exception:
      pass
  try:
    _USAGE_STORE.record_user_token_usage(str(user_id), int(tokens or 0))
  except Exception:
    pass
