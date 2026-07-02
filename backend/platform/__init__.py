"""Compatibility alias for :mod:`backend.app_platform`."""

from __future__ import annotations

from ..app_platform import *  # noqa: F403
from ..app_platform import (  # noqa: F401
  PLATFORM_PARITY_ITEMS,
  PLATFORM_PHASES,
  classify_tool_risk,
  current_platform_phase,
  failure_repair_route,
  platform_capabilities_payload,
  platform_parity_status,
  policy_tier_for_tool,
)
