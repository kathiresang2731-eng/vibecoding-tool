from __future__ import annotations

from enum import Enum
from typing import Any


class RiskTier(str, Enum):
  LOW = "low"
  MEDIUM = "medium"
  HIGH = "high"
  CRITICAL = "critical"


_TOOL_RISK: dict[str, RiskTier] = {
  "READ_PROJECT_FILES": RiskTier.LOW,
  "READ_FILE": RiskTier.LOW,
  "READ_FILE_RANGE": RiskTier.LOW,
  "LIST_DIR": RiskTier.LOW,
  "GLOB_SEARCH": RiskTier.LOW,
  "LOAD_PROJECT_MEMORY": RiskTier.LOW,
  "SEARCH_CODEBASE": RiskTier.LOW,
  "APPLY_PATCH": RiskTier.MEDIUM,
  "STR_REPLACE": RiskTier.MEDIUM,
  "WRITE_PROJECT_FILES": RiskTier.MEDIUM,
  "VALIDATE_PROJECT_ARTIFACT": RiskTier.LOW,
  "BUILD_PROJECT_PREVIEW": RiskTier.LOW,
  "BUILD_STAGED_PROJECT_PREVIEW": RiskTier.LOW,
  "RUN_PREVIEW_VISUAL_QA": RiskTier.LOW,
  "PERSIST_PROJECT_MEMORY": RiskTier.MEDIUM,
  "SYNC_LOCAL_PROJECT": RiskTier.MEDIUM,
  "RUN_TERMINAL": RiskTier.HIGH,
  "GIT_STATUS": RiskTier.LOW,
  "GIT_DIFF": RiskTier.LOW,
  "GIT_COMMIT": RiskTier.HIGH,
  "RUN_TESTS": RiskTier.MEDIUM,
  "RUN_BUILD": RiskTier.MEDIUM,
  "RUN_LINT": RiskTier.LOW,
  "MCP_CALL_TOOL": RiskTier.MEDIUM,
  "SPAWN_SUBAGENT": RiskTier.MEDIUM,
  "WAIT_SUBAGENT": RiskTier.LOW,
}


def policy_tier_for_tool(tool_name: str) -> RiskTier:
  return _TOOL_RISK.get(str(tool_name or "").strip().upper(), RiskTier.MEDIUM)


def classify_tool_risk(tool_name: str, *, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
  tier = policy_tier_for_tool(tool_name)
  requires_approval = tier in {RiskTier.HIGH, RiskTier.CRITICAL}
  auto_approve = tier == RiskTier.LOW
  return {
    "tool": tool_name,
    "risk_tier": tier.value,
    "auto_approve": auto_approve,
    "requires_approval": requires_approval,
    "blocked": tier == RiskTier.CRITICAL,
    "arguments_preview_keys": sorted((arguments or {}).keys())[:12],
  }
