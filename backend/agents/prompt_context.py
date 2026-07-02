from __future__ import annotations


ORCHESTRATOR_CONTEXT_MARKER = "Additional conversation context for model routing and planning."


def current_user_prompt(prompt: str) -> str:
  text = prompt.strip()
  marker_index = text.find(ORCHESTRATOR_CONTEXT_MARKER)
  if marker_index >= 0:
    text = text[:marker_index].strip()
  return text
