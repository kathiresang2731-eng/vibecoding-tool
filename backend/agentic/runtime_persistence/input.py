from __future__ import annotations

from typing import Any

from .constants import SYSTEM_MEMORY_PROMPT

def build_agent_run_input(
  *,
  project: dict[str, Any],
  prompt: str,
  provider: str,
  model: str | None,
  request_id: str | None = None,
) -> dict[str, Any]:
  return {
    "request_id": request_id,
    "project": {
      "id": project.get("id"),
      "name": project.get("name"),
      "local_path": project.get("local_path"),
    },
    "provider": provider,
    "model": model,
    "messages": [
      {"role": "system", "content": SYSTEM_MEMORY_PROMPT},
      {"role": "user", "content": prompt},
    ],
  }
