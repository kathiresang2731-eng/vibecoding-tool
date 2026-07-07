from __future__ import annotations

from typing import Any

from .values import int_value, list_value


def summarize_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
  max_score = sum(int_value(check.get("points")) for check in checks)
  earned = sum(int_value(check.get("earned")) for check in checks)
  percentage = round((earned / max_score) * 100, 2) if max_score else 0.0
  missing: list[str] = []
  for check in checks:
    for item in list_value(check.get("missing")):
      if isinstance(item, str) and item not in missing:
        missing.append(item)
  return {
    "score": earned,
    "max_score": max_score,
    "percentage": percentage,
    "passed": max_score > 0 and earned == max_score,
    "checks": checks,
    "missing": missing,
  }

def add_check(
  checks: list[dict[str, Any]],
  *,
  name: str,
  passed: bool,
  detail: str,
  missing: list[str],
  points: int = 10,
) -> None:
  checks.append(
    {
      "name": name,
      "status": "passed" if passed else "failed",
      "points": points,
      "earned": points if passed else 0,
      "detail": detail,
      "missing": missing,
    }
  )
