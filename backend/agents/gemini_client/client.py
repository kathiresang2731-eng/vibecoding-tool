from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, ClassVar

try:
  from ...audit_logging import log_query_event
  from ...debug_trace import trace_function, trace_print
except ImportError:
  from audit_logging import log_query_event
  from debug_trace import trace_function, trace_print

from ..prompts import build_gemini_system_instruction
from .config import load_dotenv, parse_timeout_seconds
from .errors import GeminiClientError
from .parsing import parse_json_text
from .response import extract_finish_reason, extract_text
from .transport import post_generate_content
from .usage import log_token_usage
try:
  from ...runtime_control import raise_if_runtime_cancelled
except ImportError:
  from runtime_control import raise_if_runtime_cancelled


@dataclass
class GeminiClient:
  provider_roles: ClassVar[tuple[str, str]] = ("control", "artifact")
  api_key: str
  model: str = "gemini-3.5-flash"
  timeout_seconds: int = 60

  @classmethod
  @trace_function()
  def from_env(cls) -> "GeminiClient":
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash"
    timeout_seconds = parse_timeout_seconds(os.getenv("GEMINI_TIMEOUT_SECONDS"), fallback=180)

    if not api_key or api_key == "your_gemini_api_key_here":
      raise GeminiClientError("Missing GEMINI_API_KEY in .env")

    return cls(api_key=api_key, model=model, timeout_seconds=timeout_seconds)

  @trace_function(trace_label=lambda _self, _prompt, **kwargs: kwargs.get("trace_label", "gemini_generate_json"), model=lambda self, *_args, **_kwargs: self.model, google_search=lambda _self, _prompt, **kwargs: kwargs.get("google_search", False), history=lambda _self, _prompt, **kwargs: len(kwargs.get("chat_history") or []))
  def generate_json(
    self,
    prompt: str,
    *,
    system_instruction: str | None = None,
    trace_label: str = "gemini_generate_json",
    google_search: bool = False,
    response_schema: dict[str, Any] | None = None,
    max_output_tokens: int | None = None,
    chat_history: list[dict[str, Any]] | None = None,
    prompt_fragments_used: list[str] | None = None,
    selected_files: list[str] | None = None,
    memory_items_used: int = 0,
  ) -> dict[str, Any]:
    payload = build_generate_json_payload(
      prompt,
      system_instruction=system_instruction,
      google_search=google_search,
      response_schema=response_schema,
      max_output_tokens=max_output_tokens,
      chat_history=chat_history,
      thinking_level=thinking_level_for_trace(trace_label),
    )
    raise_if_runtime_cancelled()
    trace_print("EXIT", file=__file__, class_name="GeminiClient", function="build_generate_json_payload", content_count=len(payload.get("contents") or []))
    started_at = time.monotonic()
    log_query_event(
      "model.call.requested",
      status="running",
      payload={"call": trace_label, "prompt": prompt, "google_search": google_search},
      provider="gemini",
      model=self.model,
    )
    try:
      response = self._post_generate_content(payload)
    except Exception as exc:
      log_query_event(
        "model.call.failed",
        status="failed",
        payload={"call": trace_label, "error": str(exc)},
        provider="gemini",
        model=self.model,
        duration_ms=(time.monotonic() - started_at) * 1000,
      )
      raise
    raise_if_runtime_cancelled()
    text = extract_text(response)
    finish_reason = extract_finish_reason(response)
    system_chars, history_chars = prompt_context_char_counts(payload)
    log_token_usage(
      response,
      model=self.model,
      trace_label=trace_label,
      prompt_chars=len(prompt),
      output_chars=len(text),
      duration_ms=(time.monotonic() - started_at) * 1000,
      finish_reason=finish_reason,
      thinking_level=thinking_level_for_trace(trace_label),
      execution_stage=execution_stage_for_trace(trace_label),
      model_role=model_role_for_trace(trace_label),
      system_instruction_chars=system_chars,
      chat_history_chars=history_chars,
      prompt_fragments_used=prompt_fragments_used,
      selected_files=selected_files,
      memory_items_used=memory_items_used,
    )
    if finish_reason == "MAX_TOKENS":
      raise GeminiClientError(
        f"Gemini response was truncated during {trace_label} because the max output token budget was exhausted."
      )
    return parse_json_text(text)

  @trace_function(model=lambda self, _payload: self.model, content_count=lambda _self, payload: len(payload.get("contents") or []))
  def _post_generate_content(self, payload: dict[str, Any]) -> dict[str, Any]:
    raise_if_runtime_cancelled()
    try:
      return post_generate_content(
        payload,
        api_key=self.api_key,
        model=self.model,
        timeout_seconds=self.timeout_seconds,
      )
    except GeminiClientError as exc:
      retry_payload = payload_without_unsupported_thinking_config(payload, exc)
      if retry_payload is None:
        raise
      log_query_event(
        "model.call.thinking_config_fallback",
        status="completed",
        payload={"reason": str(exc)[:300]},
        provider="gemini",
        model=self.model,
      )
      return post_generate_content(
        retry_payload,
        api_key=self.api_key,
        model=self.model,
        timeout_seconds=self.timeout_seconds,
      )


def build_generate_json_payload(
  prompt: str,
  *,
  system_instruction: str | None,
  google_search: bool,
  response_schema: dict[str, Any] | None,
  max_output_tokens: int | None,
  chat_history: list[dict[str, Any]] | None = None,
  thinking_level: str | None = None,
) -> dict[str, Any]:
  contents = list(chat_history or [])
  contents.append(
    {
      "role": "user",
      "parts": [{"text": prompt}],
    }
  )
  generation_config = build_generation_config(
    response_mime_type="application/json",
    thinking_level=thinking_level,
  )
  payload: dict[str, Any] = {
    "systemInstruction": {
      "parts": [{"text": system_instruction or build_gemini_system_instruction()}],
    },
    "contents": contents,
    "generationConfig": generation_config,
  }
  if response_schema:
    payload["generationConfig"]["responseSchema"] = response_schema
  if max_output_tokens:
    payload["generationConfig"]["maxOutputTokens"] = max_output_tokens
  if google_search:
    payload["tools"] = [{"google_search": {}}]
  return payload


def prompt_context_char_counts(payload: dict[str, Any]) -> tuple[int, int]:
  system_chars = 0
  for part in ((payload.get("systemInstruction") or {}).get("parts") or []):
    if isinstance(part, dict):
      system_chars += len(str(part.get("text") or ""))
  contents = payload.get("contents") or []
  history_chars = 0
  for content in contents[:-1]:
    if not isinstance(content, dict):
      continue
    for part in content.get("parts") or []:
      if isinstance(part, dict):
        history_chars += len(str(part.get("text") or ""))
  return system_chars, history_chars


def build_generation_config(
  *,
  response_mime_type: str | None = None,
  thinking_level: str | None = None,
) -> dict[str, Any]:
  config: dict[str, Any] = {}
  if response_mime_type:
    config["responseMimeType"] = response_mime_type
  if sampling_overrides_enabled():
    config["temperature"] = _env_float("GEMINI_TEMPERATURE", 0.35)
    config["topP"] = _env_float("GEMINI_TOP_P", 0.9)
  thinking_config = thinking_config_for_level(thinking_level)
  if thinking_config:
    config["thinkingConfig"] = thinking_config
  return config


def sampling_overrides_enabled() -> bool:
  raw = str(os.getenv("GEMINI_ENABLE_SAMPLING_OVERRIDES", "")).strip().lower()
  return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, fallback: float) -> float:
  try:
    return float(str(os.getenv(name) or "").strip())
  except ValueError:
    return fallback


def thinking_level_for_trace(trace_label: str | None) -> str:
  explicit = str(os.getenv("GEMINI_THINKING_LEVEL") or "").strip().lower()
  if explicit in {"minimal", "low", "medium", "high", "off"}:
    return explicit
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


def model_role_for_trace(trace_label: str | None) -> str:
  stage = execution_stage_for_trace(trace_label)
  if stage in {"routing", "memory", "planning"}:
    return "control"
  if stage in {"patch", "artifact"}:
    return "artifact"
  return ""


def execution_stage_for_trace(trace_label: str | None) -> str:
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


def thinking_config_for_level(level: str | None) -> dict[str, Any] | None:
  if str(os.getenv("ENABLE_GEMINI_THINKING_CONFIG", "true")).strip().lower() not in {"1", "true", "yes", "on"}:
    return None
  normalized = str(level or "low").strip().lower()
  budgets = {
    "off": 0,
    "minimal": 0,
    "low": 256,
    "medium": 1024,
    "high": 4096,
  }
  if normalized not in budgets:
    normalized = "low"
  return {"thinkingBudget": budgets[normalized]}


def payload_without_unsupported_thinking_config(payload: dict[str, Any], exc: Exception) -> dict[str, Any] | None:
  generation_config = payload.get("generationConfig")
  if not isinstance(generation_config, dict) or "thinkingConfig" not in generation_config:
    return None
  message = str(exc).lower()
  if "thinking" not in message and "generationconfig" not in message and "unknown name" not in message:
    return None
  retry_payload = dict(payload)
  retry_config = dict(generation_config)
  retry_config.pop("thinkingConfig", None)
  retry_payload["generationConfig"] = retry_config
  return retry_payload
