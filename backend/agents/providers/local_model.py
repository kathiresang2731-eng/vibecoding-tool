from __future__ import annotations

import importlib
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from .constants import CONTROL_PROVIDER_ROLE


class LocalModelProvider:
  name = "local-gpt"
  provider_role = CONTROL_PROVIDER_ROLE

  def __init__(self, adapter: Any | None = None, *, endpoint: str | None = None, model: str | None = None, timeout_seconds: int = 120) -> None:
    self.adapter = adapter
    self.endpoint = endpoint
    self.model = model or "local-120b"
    self.timeout_seconds = timeout_seconds

  @classmethod
  def from_env_or_module(cls) -> "LocalModelProvider":
    json_endpoint = os.getenv("LOCAL_MODEL_JSON_ENDPOINT") or os.getenv("GPT_LOCAL_MODEL_JSON_ENDPOINT")
    adapter = package_export("import_optional_local_model", import_optional_local_model)()
    model = os.getenv("LOCAL_MODEL_NAME") or os.getenv("GPT_LOCAL_MODEL_NAME") or adapter_default_model_name(adapter)
    timeout_seconds = parse_int(os.getenv("LOCAL_MODEL_TIMEOUT_SECONDS"), fallback=120)
    if adapter is None and not json_endpoint:
      raise RuntimeError("Local model provider requires local_model.py or LOCAL_MODEL_JSON_ENDPOINT.")
    return cls(adapter=adapter, endpoint=None if adapter is not None else json_endpoint, model=model, timeout_seconds=timeout_seconds)

  def generate_json(
    self,
    prompt: str,
    *,
    system_instruction: str | None = None,
    trace_label: str = "local_model_generate_json",
    tools: list[dict[str, Any]] | None = None,
    response_schema: dict[str, Any] | None = None,
    max_output_tokens: int | None = None,
    chat_history: list[dict[str, Any]] | None = None,
    prompt_fragments_used: list[str] | None = None,
    selected_files: list[str] | None = None,
    memory_items_used: int = 0,
  ) -> dict[str, Any]:
    try:
      if self.adapter is not None:
        return normalize_local_model_json(
          call_local_model_adapter(
            self.adapter,
            prompt,
            system_instruction=system_instruction,
            trace_label=trace_label,
            model=self.model,
            tools=tools or [],
          )
        )
      if self.endpoint:
        return normalize_local_model_json(
          post_local_model_endpoint(
            self.endpoint,
            {
              "model": self.model,
              "prompt": prompt,
              "system_instruction": system_instruction,
              "trace_label": trace_label,
              "response_format": {"type": "json_object"},
              "tools": tools or [],
            },
            timeout_seconds=self.timeout_seconds,
          )
        )
      raise RuntimeError("Local model provider is not configured.")
    except Exception as exc:
      raise RuntimeError(f"Local GPT control model call failed during {trace_label}: {exc}") from exc


class UnavailableLocalControlProvider:
  name = "local-gpt-unavailable"
  provider_role = CONTROL_PROVIDER_ROLE
  model = "deterministic-control-fallback"

  def __init__(self, reason: str) -> None:
    self.reason = reason

  def generate_json(
    self,
    prompt: str,
    *,
    system_instruction: str | None = None,
    trace_label: str = "local_model_generate_json",
    tools: list[dict[str, Any]] | None = None,
    response_schema: dict[str, Any] | None = None,
    max_output_tokens: int | None = None,
    chat_history: list[dict[str, Any]] | None = None,
    prompt_fragments_used: list[str] | None = None,
    selected_files: list[str] | None = None,
    memory_items_used: int = 0,
  ) -> dict[str, Any]:
    raise RuntimeError(
      f"Local GPT control model call failed during {trace_label}: "
      f"local control provider unavailable; deterministic fallback required. {self.reason}"
    )


def package_export(name: str, fallback: Any) -> Any:
  package = sys.modules.get(__package__)
  if package is not None:
    return getattr(package, name, fallback)
  return fallback


def import_optional_local_model() -> Any | None:
  for module_name in (
    "backend.agents.local_model",
    "agents.local_model",
    "backend.llm.local_model",
    "llm.local_model",
    "local_model",
    "backend.local_model",
  ):
    try:
      return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
      if not is_optional_module_path_error(exc.name, module_name):
        raise RuntimeError(f"Failed to import {module_name}: missing dependency {exc.name}.") from exc
      continue
  return None


def adapter_default_model_name(adapter: Any | None) -> str:
  if adapter is not None:
    default_name = getattr(adapter, "DEFAULT_LOCAL_MODEL_NAME", None)
    if isinstance(default_name, str) and default_name.strip():
      return default_name.strip()
  return "local-120b"


def is_optional_module_path_error(missing_name: str | None, module_name: str) -> bool:
  if not missing_name:
    return False
  return module_name == missing_name or module_name.startswith(f"{missing_name}.")


def call_local_model_adapter(
  adapter: Any,
  prompt: str,
  *,
  system_instruction: str | None,
  trace_label: str,
  model: str,
  tools: list[dict[str, Any]],
) -> Any:
  runner = build_local_model_runner(adapter, model=model)
  if runner is not None:
    return call_local_model_runner(
      runner,
      prompt,
      system_instruction=system_instruction,
      trace_label=trace_label,
      tools=tools,
    )
  if hasattr(adapter, "generate_json"):
    return call_with_fallback_kwargs(
      adapter.generate_json,
      prompt,
      system_instruction=system_instruction,
      trace_label=trace_label,
      model=model,
      tools=tools,
    )
  if hasattr(adapter, "chat_json"):
    return call_with_fallback_kwargs(
      adapter.chat_json,
      prompt=prompt,
      system_instruction=system_instruction,
      trace_label=trace_label,
      model=model,
      tools=tools,
    )
  if hasattr(adapter, "generate"):
    return call_with_fallback_kwargs(
      adapter.generate,
      prompt=prompt,
      system_instruction=system_instruction,
      trace_label=trace_label,
      model=model,
      tools=tools,
    )
  raise RuntimeError("local_model.py must expose generate_json(), chat_json(), or generate().")


def build_local_model_runner(adapter: Any, *, model: str | None = None) -> Any | None:
  if hasattr(adapter, "run"):
    return adapter
  for class_name in ("OpenAILLM____", "OpenAILLM", "LocalModel", "LocalLLM"):
    model_class = getattr(adapter, class_name, None)
    if model_class is None:
      continue
    try:
      if model:
        return model_class(model_name=model)
      return model_class()
    except TypeError:
      try:
        if model:
          return model_class(model=model)
        return model_class()
      except TypeError:
        pass
    try:
      return model_class()
    except TypeError:
      return model_class
  return None


def call_local_model_runner(
  runner: Any,
  prompt: str,
  *,
  system_instruction: str | None,
  trace_label: str,
  tools: list[dict[str, Any]],
) -> Any:
  messages = []
  if system_instruction:
    messages.append({"role": "system", "content": system_instruction})
  messages.append({"role": "user", "content": prompt})
  return call_with_fallback_kwargs(
    runner.run,
    messages,
    tools=tools,
    reasoning_effort="low",
  )


def call_with_fallback_kwargs(function: Any, *args: Any, **kwargs: Any) -> Any:
  try:
    return function(*args, **kwargs)
  except TypeError:
    reduced_kwargs = {key: value for key, value in kwargs.items() if key != "model"}
    try:
      return function(*args, **reduced_kwargs)
    except TypeError:
      minimal_kwargs = {key: value for key, value in reduced_kwargs.items() if key in {"prompt", "system_instruction"}}
      return function(*args, **minimal_kwargs)


def post_local_model_endpoint(endpoint: str, payload: dict[str, Any], *, timeout_seconds: int) -> Any:
  request = urllib.request.Request(
    url=endpoint,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
  )
  try:
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
      return json.loads(response.read().decode("utf-8"))
  except urllib.error.URLError as exc:
    raise RuntimeError(f"Local model endpoint error: {exc}") from exc


def normalize_local_model_json(response: Any) -> dict[str, Any]:
  if isinstance(response, dict):
    content = response.get("content")
    if isinstance(content, str) and content.strip():
      parsed_content = parse_json_object_from_text(content)
      if isinstance(parsed_content, dict):
        return parsed_content
    if isinstance(response.get("json"), dict):
      return response["json"]
    if isinstance(response.get("data"), dict):
      return response["data"]
    return response
  if isinstance(response, str):
    try:
      parsed = json.loads(response)
    except json.JSONDecodeError as exc:
      raise RuntimeError("Local model response must be JSON.") from exc
    if isinstance(parsed, dict):
      return parsed
  raise RuntimeError("Local model response must be a JSON object.")


def parse_json_object_from_text(content: str) -> dict[str, Any] | None:
  text = content.strip()
  if text.startswith("```"):
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
      lines = lines[1:]
    if lines and lines[-1].strip() == "```":
      lines = lines[:-1]
    text = "\n".join(lines).strip()
  try:
    parsed = json.loads(text)
  except json.JSONDecodeError:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
      return None
    try:
      parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
      return None
  return parsed if isinstance(parsed, dict) else None


def parse_int(value: str | None, *, fallback: int) -> int:
  if not value:
    return fallback
  try:
    return int(value)
  except ValueError:
    return fallback
