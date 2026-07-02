from __future__ import annotations

try:
  from ...app_platform import platform_capabilities_payload
except ImportError:
  from backend.app_platform import platform_capabilities_payload


def v1_platform_capabilities() -> dict:
  return platform_capabilities_payload()
