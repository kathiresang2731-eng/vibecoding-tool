from __future__ import annotations


def parse_positive_int(value: str | None, fallback: int) -> int:
  try:
    parsed = int(str(value or "").strip())
  except ValueError:
    return fallback
  return parsed if parsed > 0 else fallback
