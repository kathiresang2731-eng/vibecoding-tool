from __future__ import annotations

import time
import os

from .constants import (
  DEFAULT_AGENT_RUNTIME_TIMEOUT_SECONDS,
  DEFAULT_REPAIR_MODEL_SOFT_TIMEOUT_SECONDS,
  DEFAULT_SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS,
  REPAIR_RUNTIME_MIN_REMAINING_SECONDS,
)


def artifact_call_soft_timeout_seconds(trace_label: str) -> int:
  if trace_label == "scoped_update_artifact":
    return scoped_update_model_soft_timeout_seconds()
  if trace_label == "repair_website_artifact":
    return repair_model_soft_timeout_seconds()
  return artifact_model_soft_timeout_seconds()


def artifact_model_soft_timeout_seconds() -> int:
  raw_value = os.getenv("ARTIFACT_MODEL_SOFT_TIMEOUT_SECONDS")
  if raw_value is None:
    raw_value = os.getenv("GEMINI_TIMEOUT_SECONDS")
  if raw_value is None:
    return 0
  try:
    timeout_seconds = int(str(raw_value).strip())
  except ValueError:
    return 0
  return max(0, timeout_seconds)


def repair_model_soft_timeout_seconds() -> int:
  raw_value = os.getenv("REPAIR_MODEL_SOFT_TIMEOUT_SECONDS")
  if raw_value is None:
    raw_value = str(DEFAULT_REPAIR_MODEL_SOFT_TIMEOUT_SECONDS)
  try:
    timeout_seconds = int(str(raw_value).strip())
  except ValueError:
    return DEFAULT_REPAIR_MODEL_SOFT_TIMEOUT_SECONDS
  return max(0, timeout_seconds)


def scoped_update_model_soft_timeout_seconds() -> int:
  raw_value = os.getenv("SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS")
  if raw_value is not None:
    try:
      return max(1, int(str(raw_value).strip()))
    except ValueError:
      return DEFAULT_SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS

  repair_timeout = os.getenv("REPAIR_MODEL_SOFT_TIMEOUT_SECONDS")
  if repair_timeout is not None:
    try:
      return max(1, int(str(repair_timeout).strip()))
    except ValueError:
      return DEFAULT_REPAIR_MODEL_SOFT_TIMEOUT_SECONDS

  return DEFAULT_SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS


def scoped_update_sequence_timeout_seconds() -> int:
  raw_value = os.getenv("SCOPED_UPDATE_SEQUENCE_TIMEOUT_SECONDS")
  if raw_value is None:
    return 30
  try:
    timeout_seconds = int(str(raw_value).strip())
  except ValueError:
    return 30
  return max(1, timeout_seconds)


def runtime_timeout_seconds() -> int:
  raw_value = os.getenv("AGENT_RUNTIME_TIMEOUT_SECONDS", str(DEFAULT_AGENT_RUNTIME_TIMEOUT_SECONDS))
  try:
    timeout_seconds = int(str(raw_value).strip())
  except ValueError:
    return DEFAULT_AGENT_RUNTIME_TIMEOUT_SECONDS
  return max(1, timeout_seconds)


def remaining_runtime_seconds(*, start_time: float, timeout_seconds: int) -> float:
  return float(timeout_seconds) - (time.monotonic() - start_time)


def repair_runtime_min_remaining_seconds() -> int:
  raw_value = os.getenv("REPAIR_RUNTIME_MIN_REMAINING_SECONDS")
  if raw_value is None:
    raw_value = str(REPAIR_RUNTIME_MIN_REMAINING_SECONDS)
  try:
    threshold = int(str(raw_value).strip())
  except ValueError:
    return REPAIR_RUNTIME_MIN_REMAINING_SECONDS
  return max(0, threshold)


def should_skip_gemini_repair_for_budget(*, start_time: float, timeout_seconds: int) -> bool:
  return remaining_runtime_seconds(start_time=start_time, timeout_seconds=timeout_seconds) < repair_runtime_min_remaining_seconds()
