from __future__ import annotations

from typing import Any

from .browser import browser_candidates
from .types import BrowserCommand


def skipped_visual_qa(project_id: str, reason: str) -> dict[str, Any]:
  return {
    "project_id": project_id,
    "status": "skipped",
    "mode": "browser_render_skipped",
    "browser_rendered": False,
    "checks": [
      {
        "name": "browser_render",
        "status": "skipped",
        "detail": reason,
      }
    ],
    "warnings": [reason],
    "diagnostics": {
      "configuration": "Set VISUAL_QA_BROWSER_COMMAND, CHROME_PATH, CHROMIUM_PATH, PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH, or BROWSER.",
      "candidates_checked": browser_candidates(),
    },
  }

def failed_visual_qa(
  project_id: str,
  reason: str,
  *,
  browser_command: BrowserCommand,
  target_url: str,
  failure_kind: str = "browser_render_failed",
) -> dict[str, Any]:
  return {
    "project_id": project_id,
    "status": "failed",
    "mode": "browser_render_failed",
    "failure_kind": failure_kind,
    "browser_rendered": False,
    "browser_command": browser_command.display,
    "browser_command_source": browser_command.source,
    "target_url": target_url,
    "checks": [
      {
        "name": "browser_render",
        "status": "failed",
        "detail": reason,
      }
    ],
    "warnings": [reason],
  }
