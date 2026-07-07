"""Clone LLM provider instances for parallel worker threads."""

from __future__ import annotations

from typing import Any


def clone_llm_provider(provider: Any, *, copy_chat_history: bool = True) -> Any:
  """Return a fresh provider instance — shared HTTP clients are not thread-safe."""
  if provider is None:
    return None
  provider_type = type(provider)
  model = getattr(provider, "model", None)
  try:
    from .gemini import GeminiProvider
  except ImportError:
    from agents.providers.gemini import GeminiProvider

  cloned: Any
  if provider_type is GeminiProvider:
    cloned = GeminiProvider(model=model)
  elif hasattr(provider, "model"):
    try:
      cloned = provider_type(model=model)
    except TypeError:
      try:
        cloned = provider_type()
      except TypeError:
        cloned = provider
  else:
    cloned = provider

  if copy_chat_history and cloned is not provider:
    parent_history = getattr(provider, "chat_history", None)
    if isinstance(parent_history, list) and parent_history:
      setattr(cloned, "chat_history", list(parent_history))
  return cloned
