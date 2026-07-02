from __future__ import annotations

import os


def env_bool(name: str, fallback: bool) -> bool:
  raw = str(os.getenv(name, "true" if fallback else "false")).strip().lower()
  if raw in {"1", "true", "yes", "on"}:
    return True
  if raw in {"0", "false", "no", "off"}:
    return False
  return fallback


def env_positive_int(name: str, fallback: int) -> int:
  try:
    value = int(str(os.getenv(name, fallback)).strip())
  except ValueError:
    return fallback
  return value if value > 0 else fallback


def dynamic_agent_timeout_seconds() -> int:
  return env_positive_int("DYNAMIC_AGENT_TIMEOUT_SECONDS", 60)


def dynamic_agent_max_tool_calls() -> int:
  return env_positive_int("DYNAMIC_AGENT_MAX_TOOL_CALLS", 6)


def dynamic_agent_max_patch_files() -> int:
  return env_positive_int("DYNAMIC_AGENT_MAX_PATCH_FILES", 6)


def dynamic_agent_max_patch_bytes() -> int:
  return env_positive_int("DYNAMIC_AGENT_MAX_PATCH_BYTES", 262144)


def dynamic_agent_promotion_min_successes() -> int:
  return env_positive_int("DYNAMIC_AGENT_PROMOTION_MIN_SUCCESSES", 3)


def dynamic_agent_tool_loop_enabled() -> bool:
  try:
    from ..runtime_config import dynamic_agent_tool_loop_enabled as parity_tool_loop_enabled
    return parity_tool_loop_enabled()
  except ImportError:
    from agents.runtime_config import dynamic_agent_tool_loop_enabled as parity_tool_loop_enabled
    return parity_tool_loop_enabled()


def default_dynamic_metrics() -> dict[str, object]:
  return {
    "usage_count": 0,
    "successful_runs": 0,
    "failed_runs": 0,
    "consecutive_failures": 0,
    "safety_violations": 0,
    "success_rate": 0.0,
    "avg_execution_ms": None,
  }
