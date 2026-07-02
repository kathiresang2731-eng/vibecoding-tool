from __future__ import annotations

import json
import os
from typing import Any, Callable

try:
  from ...audit_logging import log_query_event
  from ...debug_trace import trace_function
except ImportError:
  from audit_logging import log_query_event
  from debug_trace import trace_function
from ..gemini_client import GeminiClient
from ..gemini_client.errors import GeminiClientError
from ..gemini_tool_calling import run_gemini_tool_calling_loop
from .constants import DUAL_PROVIDER_ROLE


class GeminiProvider:
  name = "gemini"
  provider_role = DUAL_PROVIDER_ROLE

  @trace_function(model=lambda _self, client=None, model=None, **_kwargs: model or getattr(client, "model", None) or "env-default")
  def __init__(
    self,
    client: GeminiClient | None = None,
    *,
    model: str | None = None,
    provider_role: str = DUAL_PROVIDER_ROLE,
  ) -> None:
    self.client = client
    self.model = model or getattr(client, "model", None)
    self.provider_role = provider_role or DUAL_PROVIDER_ROLE
    self.chat_history: list[dict[str, Any]] = []

  @trace_function(model=lambda self: self.model or "env-default")
  def resolved_client(self) -> GeminiClient:
    if self.client is None:
      self.client = GeminiClient.from_env()
    if self.model:
      self.client.model = self.model
    return self.client

  @trace_function(trace_label=lambda _self, _prompt, **kwargs: kwargs.get("trace_label", "gemini_generate_json"), history=lambda self, *_args, chat_history=None, **_kwargs: len(chat_history if chat_history is not None else self.chat_history))
  def generate_json(
    self,
    prompt: str,
    *,
    system_instruction: str | None = None,
    trace_label: str = "gemini_generate_json",
    tools: list[dict[str, Any]] | None = None,
    response_schema: dict[str, Any] | None = None,
    max_output_tokens: int | None = None,
    chat_history: list[dict[str, Any]] | None = None,
    prompt_fragments_used: list[str] | None = None,
    selected_files: list[str] | None = None,
    memory_items_used: int = 0,
  ) -> dict[str, Any]:
    client = self.resolved_client()
    raw_history = chat_history if chat_history is not None else self.chat_history
    history, context_meta = select_model_chat_history(raw_history)
    if context_meta["compacted"]:
      log_query_event(
        "model.context.compacted",
        status="completed",
        payload={"call": trace_label, **context_meta},
        provider="gemini",
        model=client.model,
      )
    try:
      return client.generate_json(
        prompt,
        system_instruction=system_instruction,
        trace_label=trace_label,
        response_schema=response_schema,
        max_output_tokens=max_output_tokens,
        chat_history=history,
        prompt_fragments_used=prompt_fragments_used,
        selected_files=selected_files,
        memory_items_used=memory_items_used,
      )
    except GeminiClientError as exc:
      if not should_escalate_to_pro(client.model, exc):
        raise
      escalated_client = GeminiClient(
        api_key=client.api_key,
        model="gemini-3.1-pro-preview",
        timeout_seconds=client.timeout_seconds,
      )
      log_query_event(
        "model.call.escalated",
        status="running",
        payload={
          "call": trace_label,
          "from_model": client.model,
          "to_model": escalated_client.model,
          "reason": str(exc)[:500],
        },
        provider="gemini",
        model=escalated_client.model,
      )
      return escalated_client.generate_json(
        prompt,
        system_instruction=system_instruction,
        trace_label=f"{trace_label}.pro_escalation",
        response_schema=response_schema,
        max_output_tokens=max_output_tokens,
        chat_history=history,
        prompt_fragments_used=prompt_fragments_used,
        selected_files=selected_files,
        memory_items_used=memory_items_used,
      )

  @trace_function(trace_label=lambda _self, _prompt, **kwargs: kwargs.get("trace_label", "gemini_search_generate_json"))
  def generate_json_with_search(
    self,
    prompt: str,
    *,
    system_instruction: str | None = None,
    trace_label: str = "gemini_search_generate_json",
  ) -> dict[str, Any]:
    return self.resolved_client().generate_json(
      prompt,
      system_instruction=system_instruction,
      trace_label=trace_label,
      google_search=True,
      chat_history=self.chat_history,
    )

  @trace_function(trace_label=lambda _self, **kwargs: kwargs.get("trace_label", "gemini_tool_calling_loop"), tool_count=lambda _self, **kwargs: len(kwargs.get("tools") or []))
  def run_tool_loop(
    self,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    execute_tool,
    max_steps: int = 6,
    mode: str | None = None,
    trace_label: str = "gemini_tool_calling_loop",
    on_step_text: Callable[..., None] | None = None,
    on_tool_start: Callable[..., None] | None = None,
    on_tool_end: Callable[..., None] | None = None,
  ) -> dict[str, Any]:
    return run_gemini_tool_calling_loop(
      client=self.resolved_client(),
      messages=messages,
      tools=tools,
      execute_tool=execute_tool,
      max_steps=max_steps,
      mode=mode,
      trace_label=trace_label,
      on_step_text=on_step_text,
      on_tool_start=on_tool_start,
      on_tool_end=on_tool_end,
    )


def should_escalate_to_pro(model: str | None, error: Exception) -> bool:
  enabled = str(os.getenv("ENABLE_GEMINI_PRO_ESCALATION", "true")).strip().lower()
  if enabled not in {"1", "true", "yes", "on"}:
    return False
  if str(model or "").strip() != "gemini-3.5-flash":
    return False
  message = str(error or "").lower()
  return any(
    marker in message
    for marker in (
      "returned invalid json",
      "response was truncated",
      "unexpected gemini response shape",
    )
  )


def select_model_chat_history(
  history: list[dict[str, Any]] | None,
  *,
  max_chars: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
  items = [dict(item) for item in (history or []) if isinstance(item, dict)]
  original_chars = _history_chars(items)
  budget = max_chars if max_chars is not None else _model_history_budget_chars()
  if original_chars <= budget:
    return items, {
      "compacted": False,
      "original_chars": original_chars,
      "selected_chars": original_chars,
      "original_items": len(items),
      "selected_items": len(items),
      "budget_chars": budget,
    }

  anchors: list[dict[str, Any]] = []
  for item in items[:4]:
    text = _history_item_text(item)
    if "CURRENT PROJECT FILE INDEX" in text or "CURRENT LIVE WEBSITE CODE CONTEXT" in text:
      index = items.index(item)
      anchors = items[index : min(len(items), index + 2)]
      break

  selected_reversed: list[dict[str, Any]] = []
  used = _history_chars(anchors)
  for item in reversed(items):
    if any(item == anchor for anchor in anchors):
      continue
    item_chars = _history_chars([item])
    if used + item_chars > budget:
      continue
    selected_reversed.append(item)
    used += item_chars

  selected = [*anchors, *reversed(selected_reversed)]
  while selected and str(selected[0].get("role") or "") == "model" and selected[0] not in anchors:
    selected.pop(0)
  selected_chars = _history_chars(selected)
  return selected, {
    "compacted": True,
    "original_chars": original_chars,
    "selected_chars": selected_chars,
    "original_items": len(items),
    "selected_items": len(selected),
    "budget_chars": budget,
  }


def _model_history_budget_chars() -> int:
  raw = str(os.getenv("MODEL_CALL_HISTORY_MAX_CHARS", "60000")).strip()
  try:
    return max(12_000, min(int(raw), 200_000))
  except ValueError:
    return 60_000


def _history_chars(history: list[dict[str, Any]]) -> int:
  return sum(len(json.dumps(item, ensure_ascii=False, default=str)) for item in history)


def _history_item_text(item: dict[str, Any]) -> str:
  parts = item.get("parts")
  if not isinstance(parts, list):
    return str(item.get("content") or "")
  return "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
