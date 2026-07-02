from __future__ import annotations

from typing import Any

from ..providers import GeminiProvider

def is_artifact_intent(intent: str) -> bool:
  return intent in {"simple_code", "website_generation", "website_update"}

def default_control_provider() -> Any:
  return GeminiProvider()

def provider_name(provider: Any) -> str:
  name = getattr(provider, "name", None)
  if isinstance(name, str) and name.strip():
    return name.strip()
  return provider.__class__.__name__ if provider is not None else "unknown"

def configured_adk_model() -> str:
  try:
    from ..config import load_settings

    return load_settings(require_database=False).gemini_model
  except Exception:
    return "gemini-3.5-flash"
