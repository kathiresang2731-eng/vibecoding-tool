from __future__ import annotations

import re

from ..progress import compact_terminal_text


def extract_runtime_timeout_seconds(raw_error: str) -> int | None:
  match = re.search(r"agent runtime exceeded timeout budget of\s+(\d+)s", raw_error, flags=re.IGNORECASE)
  if not match:
    return None
  try:
    return int(match.group(1))
  except ValueError:
    return None


def extract_failure_repair_reason(raw_error: str) -> str | None:
  patterns = (
    r"Repair Agent repairing generated files because:\s*(?P<reason>.+)",
    r"Preview runtime scan failed:\s*(?P<reason>.+)",
    r"Previous build error:\s*(?P<reason>.+)",
  )
  for pattern in patterns:
    match = re.search(pattern, raw_error, flags=re.IGNORECASE | re.DOTALL)
    if match:
      return compact_terminal_text(match.group("reason"), max_chars=900)
  return None


def extract_last_runtime_step(raw_error: str) -> str | None:
  lowered = raw_error.lower()
  known_steps = (
    "build_staged_project_preview",
    "run_preview_visual_qa",
    "validate_project_artifact",
    "repair_website_artifact",
    "generate_website_artifact",
    "update_website_artifact",
    "write_project_files",
  )
  for step in known_steps:
    if step in lowered:
      return step
  tool_match = re.search(r"tool\s+([A-Z_]+)\s+failed", raw_error)
  if tool_match:
    return tool_match.group(1).lower()
  return None

