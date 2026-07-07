from __future__ import annotations

import re
from typing import Any


_SYMBOL_PATTERNS = (
  re.compile(r"^\s*(?:export\s+default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
  re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)\b"),
  re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
  ),
  re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:React\.)?(?:memo|forwardRef|lazy|observer)\b"
  ),
  re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Z][A-Za-z0-9_$]*)\s*="),
  re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\("),
)


def _symbol_from_line(line: str) -> str:
  for pattern in _SYMBOL_PATTERNS:
    match = pattern.search(line)
    if match:
      return match.group(1)
  return ""


def source_symbol_for_line(content: str, line: int | None) -> dict[str, Any]:
  """Return the closest owning function/component for a source line.

  This is used for observability only. It does not decide routing or scope; it
  simply labels already-selected file/line anchors in terminal progress.
  """
  lines = str(content or "").splitlines()
  if not lines:
    return {}
  try:
    requested_line = int(line or 1)
  except (TypeError, ValueError):
    requested_line = 1
  requested_line = max(1, min(requested_line, len(lines)))
  start_index = requested_line - 1
  for index in range(start_index, -1, -1):
    symbol = _symbol_from_line(lines[index])
    if symbol:
      return {
        "function_name": symbol,
        "function_line": index + 1,
      }
  for index, source_line in enumerate(lines):
    symbol = _symbol_from_line(source_line)
    if symbol:
      return {
        "function_name": symbol,
        "function_line": index + 1,
      }
  return {}


__all__ = ["source_symbol_for_line"]
