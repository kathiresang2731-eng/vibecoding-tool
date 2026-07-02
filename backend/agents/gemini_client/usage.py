from __future__ import annotations

import json
from typing import Any

try:
  from ...audit_logging import log_query_event
  from ...gemini_token_usage_logger import log_gemini_token_usage
  from ...storage.token_pricing import estimate_model_usage_cost
except ImportError:
  from audit_logging import log_query_event
  from gemini_token_usage_logger import log_gemini_token_usage
  from storage.token_pricing import estimate_model_usage_cost


def _thinking_level_for_trace(trace_label: str | None) -> str:
  label = str(trace_label or "").lower()
  if "route_generation_action" in label or "routing" in label:
    return "minimal"
  if "update_analysis" in label or "memory" in label or "conversation" in label:
    return "minimal"
  if "streaming_file_agent.website_generation" in label or "full_generation" in label or "large_project" in label:
    return "medium"
  if "streaming_file_agent" in label or "scoped_update" in label or "simple_code" in label:
    return "low"
  if "generation" in label or "artifact" in label:
    return "medium"
  return "low"


def _execution_stage_for_trace(trace_label: str | None) -> str:
  label = str(trace_label or "").lower()
  if "route" in label:
    return "routing"
  if "memory" in label:
    return "memory"
  if "analysis" in label or "planning" in label:
    return "planning"
  if "streaming_file_agent.website_generation" in label or "full_generation" in label or "large_project" in label:
    return "artifact"
  if "streaming_file_agent" in label or "scoped_update" in label:
    return "patch"
  if "simple_code" in label or "artifact" in label or "generation" in label:
    return "artifact"
  return "model_call"


def _model_role_for_stage(stage: str) -> str:
  if stage in {"routing", "memory", "planning"}:
    return "control"
  if stage in {"patch", "artifact"}:
    return "artifact"
  return ""


def _route_for_trace(trace_label: str | None) -> str:
  label = str(trace_label or "").lower()
  if "streaming_file_agent.website_generation" in label or "full_generation" in label:
    return "full_generation"
  if "large_project" in label:
    return "large_project"
  if "streaming_file_agent.website_update" in label or "targeted_update" in label:
    return "targeted_update"
  if "simple_code" in label:
    return "small_code"
  return ""


def log_token_usage(
  response: dict[str, Any],
  *,
  model: str,
  trace_label: str,
  prompt_chars: int,
  output_chars: int,
  duration_ms: float | int | None = None,
  finish_reason: str | None = None,
  thinking_level: str | None = None,
  execution_stage: str | None = None,
  model_role: str | None = None,
  system_instruction_chars: int = 0,
  chat_history_chars: int = 0,
  tool_schema_chars: int = 0,
  prompt_fragments_used: list[str] | None = None,
  selected_files: list[str] | None = None,
  memory_items_used: int = 0,
) -> None:
  usage = response.get("usageMetadata") or {}
  input_tokens = int(usage.get("promptTokenCount") or 0)
  output_tokens = int(usage.get("candidatesTokenCount") or 0)
  thought_tokens = int(usage.get("thoughtsTokenCount") or 0)
  cached_tokens = int(usage.get("cachedContentTokenCount") or 0)
  resolved_stage = execution_stage or _execution_stage_for_trace(trace_label)
  resolved_thinking = thinking_level or _thinking_level_for_trace(trace_label)
  resolved_role = model_role or _model_role_for_stage(resolved_stage)
  total_context_chars = (
    max(0, int(prompt_chars or 0))
    + max(0, int(system_instruction_chars or 0))
    + max(0, int(chat_history_chars or 0))
    + max(0, int(tool_schema_chars or 0))
  )
  fragments = list(prompt_fragments_used or [])
  if not fragments:
    fragments = ["user_prompt"]
    if system_instruction_chars:
      fragments.append("system_instruction")
    if chat_history_chars:
      fragments.append("chat_history")
    if tool_schema_chars:
      fragments.append("tool_schemas")
  cost = estimate_model_usage_cost(
    model=model,
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    thought_tokens=thought_tokens,
    cached_tokens=cached_tokens,
  )
  payload = {
    "provider": "gemini",
    "model": model,
    "call": trace_label,
    "input_tokens": input_tokens,
    "output_tokens": output_tokens,
    "total_tokens": usage.get("totalTokenCount"),
    "prompt_chars": prompt_chars,
    "output_chars": output_chars,
    "cached_input_tokens": cost["cached_input_tokens"],
    "estimated_cost_usd": cost["estimated_cost_usd"],
    "estimated_credits": cost["estimated_credits"],
    "pricing_version": cost["pricing_version"],
    "route": _route_for_trace(trace_label),
    "execution_stage": resolved_stage,
    "model_role": resolved_role,
    "thinking_level": resolved_thinking,
    "context_chars": total_context_chars,
    "input_chars": total_context_chars,
    "system_instruction_chars": max(0, int(system_instruction_chars or 0)),
    "chat_history_chars": max(0, int(chat_history_chars or 0)),
    "tool_schema_chars": max(0, int(tool_schema_chars or 0)),
    "prompt_fragments_used": fragments,
    "selected_files": [str(path) for path in (selected_files or [])[:12]],
    "memory_items_used": max(0, int(memory_items_used or 0)),
  }
  if finish_reason:
    payload["finish_reason"] = finish_reason
  if "thoughtsTokenCount" in usage:
    payload["thought_tokens"] = usage.get("thoughtsTokenCount")
  if "cachedContentTokenCount" in usage:
    payload["cached_tokens"] = usage.get("cachedContentTokenCount")

  log_query_event(
    "model.call.completed",
    payload=payload,
    provider="gemini",
    model=model,
    duration_ms=duration_ms,
  )
  log_gemini_token_usage(payload, duration_ms=duration_ms)
  print(f"[WorktualTokenUsage] {json.dumps(payload, ensure_ascii=False)}", flush=True)
