from __future__ import annotations

import copy
import json
import os
import time
from typing import Any, Callable

from ..gemini_client import (
  GeminiClient,
  build_generation_config,
  execution_stage_for_trace,
  log_token_usage,
  model_role_for_trace,
  thinking_level_for_trace,
)
from .errors import GeminiToolCallingError
from .messages import messages_to_gemini_contents
from .mode import normalize_tool_calling_mode
from .response import extract_function_calls, extract_text_or_empty, first_candidate_content
from .schema import openai_tools_to_gemini_function_declarations
try:
  from ...runtime_control import raise_if_runtime_cancelled
except ImportError:
  from runtime_control import raise_if_runtime_cancelled

try:
  from ...audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event


def _bounded_env_int(name: str, fallback: int, *, minimum: int, maximum: int) -> int:
  try:
    value = int(str(os.getenv(name) or "").strip())
  except ValueError:
    value = fallback
  if value <= 0:
    value = fallback
  return max(minimum, min(value, maximum))


def _tool_loop_context_max_chars() -> int:
  return _bounded_env_int(
    "GEMINI_TOOL_LOOP_CONTEXT_MAX_CHARS",
    24_000,
    minimum=8_000,
    maximum=200_000,
  )


def _tool_loop_argument_max_chars() -> int:
  return _bounded_env_int(
    "GEMINI_TOOL_LOOP_ARGUMENT_MAX_CHARS",
    2_000,
    minimum=500,
    maximum=12_000,
  )


def _json_chars(value: Any) -> int:
  return len(json.dumps(value, ensure_ascii=False, default=str))


def _compact_argument_text(value: str, *, max_chars: int) -> str:
  if len(value) <= max_chars:
    return value
  head_chars = max(200, int(max_chars * 0.7))
  tail_chars = max(100, max_chars - head_chars)
  omitted = max(0, len(value) - head_chars - tail_chars)
  return (
    f"{value[:head_chars]}\n"
    f"... [{omitted} chars omitted from completed tool call; use read_file for exact content] ...\n"
    f"{value[-tail_chars:]}"
  )


def _compact_model_tool_content(content: dict[str, Any]) -> dict[str, Any]:
  compacted = copy.deepcopy(content)
  max_chars = _tool_loop_argument_max_chars()
  for part in compacted.get("parts") or []:
    if not isinstance(part, dict):
      continue
    function_call = part.get("functionCall") or part.get("function_call")
    if not isinstance(function_call, dict):
      continue
    arguments = function_call.get("args")
    if not isinstance(arguments, dict):
      arguments = function_call.get("arguments")
    if not isinstance(arguments, dict):
      continue
    for key in ("content", "old_string", "new_string"):
      value = arguments.get(key)
      if isinstance(value, str):
        arguments[key] = _compact_argument_text(value, max_chars=max_chars)
  return compacted


def _tool_call_summary(tool_call: dict[str, Any]) -> str:
  arguments = tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {}
  result = tool_call.get("result") if isinstance(tool_call.get("result"), dict) else {}
  name = str(tool_call.get("name") or "tool")
  path = str(arguments.get("path") or result.get("path") or "").strip()
  status = str(tool_call.get("status") or result.get("status") or "completed")
  details: list[str] = []
  if path:
    details.append(path)
  if result.get("size") is not None:
    details.append(f"{result.get('size')} chars")
  if result.get("replacements") is not None:
    details.append(f"{result.get('replacements')} replacement(s)")
  if result.get("truncated"):
    details.append("read truncated")
  if tool_call.get("error"):
    details.append(str(tool_call.get("error"))[:160])
  suffix = f" ({', '.join(details)})" if details else ""
  return f"- {name}: {status}{suffix}"


def _selected_tool_file_paths(tool_calls: list[dict[str, Any]]) -> list[str]:
  paths: list[str] = []
  for tool_call in tool_calls:
    arguments = tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {}
    result = tool_call.get("result") if isinstance(tool_call.get("result"), dict) else {}
    path = str(arguments.get("path") or result.get("path") or "").strip()
    if path and path not in paths:
      paths.append(path)
  return paths[:12]


def _select_tool_loop_contents(
  contents: list[dict[str, Any]],
  *,
  executed_tool_calls: list[dict[str, Any]],
  anchor_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
  original_chars = _json_chars(contents)
  budget = _tool_loop_context_max_chars()
  if original_chars <= budget:
    return contents, {
      "compacted": False,
      "original_chars": original_chars,
      "selected_chars": original_chars,
      "budget_chars": budget,
    }

  safe_anchor_count = max(1, min(anchor_count, len(contents)))
  anchors = [copy.deepcopy(item) for item in contents[:safe_anchor_count]]
  recent_start = max(safe_anchor_count, len(contents) - 2)
  recent = [copy.deepcopy(item) for item in contents[recent_start:]]
  summarized_calls = executed_tool_calls[:-1] if recent else executed_tool_calls
  summary_lines = [
    "Completed tool progress (older full payloads omitted to control token usage):",
    *[_tool_call_summary(item) for item in summarized_calls[-24:]],
    "Exact staged file contents remain available through read_file.",
  ]
  summary = {"role": "user", "parts": [{"text": "\n".join(summary_lines)}]}
  selected = [*anchors, summary, *recent]
  selected_chars = _json_chars(selected)
  return selected, {
    "compacted": True,
    "original_chars": original_chars,
    "selected_chars": selected_chars,
    "budget_chars": budget,
    "original_items": len(contents),
    "selected_items": len(selected),
    "budget_exceeded_by_required_recent_turn": selected_chars > budget,
  }


def run_gemini_tool_calling_loop(
  *,
  client: GeminiClient,
  messages: list[dict[str, Any]],
  tools: list[dict[str, Any]],
  execute_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
  max_steps: int = 6,
  mode: str | None = None,
  trace_label: str = "gemini_tool_calling_loop",
  on_step_text: Callable[[str, int], None] | None = None,
  on_tool_start: Callable[[str, dict[str, Any], int], None] | None = None,
  on_tool_end: Callable[[str, dict[str, Any], dict[str, Any], int], None] | None = None,
) -> dict[str, Any]:
  if not messages:
    raise GeminiToolCallingError("At least one message is required.")
  if max_steps < 1:
    raise GeminiToolCallingError("max_steps must be at least 1.")

  declarations = openai_tools_to_gemini_function_declarations(tools)
  if not declarations:
    raise GeminiToolCallingError("At least one Gemini function declaration is required.")

  contents = messages_to_gemini_contents(messages)
  base_content_count = len(contents)
  executed_tool_calls: list[dict[str, Any]] = []
  tool_payload = [{"function_declarations": declarations}]
  normalized_mode = normalize_tool_calling_mode(mode or os.getenv("GEMINI_TOOL_CALLING_MODE") or "VALIDATED")

  for step_index in range(max_steps):
    raise_if_runtime_cancelled()
    request_contents, context_meta = _select_tool_loop_contents(
      contents,
      executed_tool_calls=executed_tool_calls,
      anchor_count=base_content_count,
    )
    if context_meta["compacted"]:
      log_query_event(
        "model.tool_loop.context_compacted",
        status="completed",
        payload={"call": trace_label, "step": step_index + 1, **context_meta},
        provider="gemini",
        model=client.model,
      )
    thinking_level = thinking_level_for_trace(trace_label)
    payload = {
      "contents": request_contents,
      "tools": tool_payload,
      "generationConfig": build_generation_config(thinking_level=thinking_level),
      "tool_config": {
        "function_calling_config": {
          "mode": normalized_mode,
        }
      },
    }
    started_at = time.monotonic()
    log_query_event(
      "model.tool_loop.requested",
      status="running",
      payload={"call": trace_label, "step": step_index + 1, "available_tools": [item["name"] for item in declarations]},
      provider="gemini",
      model=client.model,
    )
    try:
      response = client._post_generate_content(payload)
    except Exception as exc:
      log_query_event(
        "model.tool_loop.failed",
        status="failed",
        payload={"call": trace_label, "step": step_index + 1, "error": str(exc)},
        provider="gemini",
        model=client.model,
        duration_ms=(time.monotonic() - started_at) * 1000,
      )
      raise
    raise_if_runtime_cancelled()
    text = extract_text_or_empty(response)
    if text and on_step_text:
      on_step_text(text, step_index + 1)
    log_token_usage(
      response,
      model=client.model,
      trace_label=trace_label,
      prompt_chars=_json_chars(request_contents),
      output_chars=len(text),
      duration_ms=(time.monotonic() - started_at) * 1000,
      thinking_level=thinking_level,
      execution_stage=execution_stage_for_trace(trace_label),
      model_role=model_role_for_trace(trace_label),
      tool_schema_chars=_json_chars(tool_payload),
      prompt_fragments_used=["conversation_context", "tool_progress", "tool_schemas"],
      selected_files=_selected_tool_file_paths(executed_tool_calls),
    )

    function_calls = extract_function_calls(response)
    if not function_calls:
      return {
        "status": "completed",
        "response": response,
        "output_text": text,
        "tool_calls": executed_tool_calls,
        "provider": "gemini-native",
        "tool_calling_mode": normalized_mode,
      }

    model_content = first_candidate_content(response)
    if model_content:
      contents.append(_compact_model_tool_content(model_content))

    function_response_parts: list[dict[str, Any]] = []
    for function_call in function_calls:
      raise_if_runtime_cancelled()
      if on_tool_start:
        on_tool_start(function_call.name, function_call.arguments, step_index + 1)
      log_query_event(
        "tool.requested",
        status="running",
        payload={
          "call_id": function_call.call_id,
          "tool_name": function_call.name,
          "arguments": function_call.arguments,
          "source": "gemini_native_tool_loop",
        },
        provider="gemini",
        model=client.model,
      )
      try:
        result = execute_tool(function_call.name, function_call.arguments)
        status = "completed"
        error = None
      except Exception as exc:
        result = {"error": str(exc)}
        status = "failed"
        error = str(exc)
      raise_if_runtime_cancelled()
      executed_tool_calls.append(
        {
          "call_id": function_call.call_id,
          "name": function_call.name,
          "arguments": function_call.arguments,
          "result": result,
          "status": status,
          "error": error,
          "provider": "gemini-native",
        }
      )
      log_query_event(
        "tool.completed" if status == "completed" else "tool.failed",
        status=status,
        payload={
          "call_id": function_call.call_id,
          "tool_name": function_call.name,
          "arguments": function_call.arguments,
          "result": result,
          "error": error,
          "source": "gemini_native_tool_loop",
        },
        provider="gemini",
        model=client.model,
      )
      if on_tool_end:
        on_tool_end(function_call.name, function_call.arguments, result, step_index + 1)
      raise_if_runtime_cancelled()
      function_response_parts.append(
        {
          "functionResponse": {
            "name": function_call.name,
            "id": function_call.call_id,
            "response": {"result": result},
          }
        }
      )

    if step_index == max_steps - 1:
      break
    contents.append({"role": "user", "parts": function_response_parts})

  raise GeminiToolCallingError(f"Gemini tool-calling loop exceeded {max_steps} steps.")
