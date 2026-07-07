from __future__ import annotations

from typing import Any

try:
  from ...agents.memory.platform_patterns_api import list_platform_memory_patterns_payload
except ImportError:
  from agents.memory.platform_patterns_api import list_platform_memory_patterns_payload


def v1_platform_memory_patterns(
  store: Any,
  *,
  domain: str | None = None,
  module: str | None = None,
  pattern_type: str | None = None,
  limit: int = 25,
) -> dict[str, Any]:
  return list_platform_memory_patterns_payload(
    store,
    domain=domain,
    module=module,
    pattern_type=pattern_type,
    limit=limit,
  )
