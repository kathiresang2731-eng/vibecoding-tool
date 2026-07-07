from __future__ import annotations

from typing import Any


_DEFAULT_CREDIT_RESERVATION_BY_ROUTE = {
  "tiny_chat": 0.0,
  "conversation": 2.0,
  "routing_pending": 2.0,
  "small_code": 2.0,
  "targeted_update": 8.0,
  "feature_update": 20.0,
  "large_project": 60.0,
  "full_generation": 80.0,
}


def default_credit_reservation_for_route(route: str | None) -> float:
  return float(_DEFAULT_CREDIT_RESERVATION_BY_ROUTE.get(str(route or "").strip(), 10.0))


def resolve_credit_reservation_estimate(route: str | None, explicit_estimate: float | int | None) -> float:
  if explicit_estimate is None:
    return default_credit_reservation_for_route(route)
  try:
    return max(0.0, float(explicit_estimate))
  except (TypeError, ValueError):
    return default_credit_reservation_for_route(route)
