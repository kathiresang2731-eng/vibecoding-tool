from __future__ import annotations

from typing import Any


def build_adk_trace_summary(runtime: dict[str, Any]) -> dict[str, Any]:
  return {
    "runtime": runtime["runtime"],
    "status": runtime["status"],
    "execution_mode": runtime["execution_mode"],
    "source_of_truth": runtime.get("source_of_truth") is True,
    "source_of_truth_runtime": runtime.get("source_of_truth_runtime"),
    "package_installed": runtime["package"]["installed"],
    "app_name": runtime["app_name"],
    "root_agent": runtime["root_agent"],
    "event_count": len(runtime["events"]),
    "validation_status": runtime["validation"]["status"],
  }
