"""Commit vs preview-build policy for streaming website updates."""

from __future__ import annotations

from typing import Any

try:
  from ..runtime_config import build_gate_rollback_on_failure
except ImportError:
  from agents.runtime_config import build_gate_rollback_on_failure

BUILD_FAILED_FILES_COMMITTED_MESSAGE = (
  "Files were saved locally. The staged Vite preview build did not pass — "
  "your code is on disk; retry preview or ask the agent to fix the build log when ready."
)

BUILD_FAILED_FILES_ROLLED_BACK_MESSAGE = (
  "Generated files failed the staged Vite preview build. No files were committed."
)

VISUAL_QA_FAILED_FILES_COMMITTED_MESSAGE = (
  "Files were saved locally. Visual QA did not pass — open Preview to review layout and styling."
)


def should_rollback_after_build_gate(build_gate_result: dict[str, Any] | None) -> bool:
  if not build_gate_rollback_on_failure():
    return False
  if not isinstance(build_gate_result, dict):
    return False
  status = str(build_gate_result.get("status") or "").lower()
  return status not in {"ready", "skipped"}


def build_gate_failure_user_message(*, rolled_back: bool) -> str:
  if rolled_back:
    return BUILD_FAILED_FILES_ROLLED_BACK_MESSAGE
  return BUILD_FAILED_FILES_COMMITTED_MESSAGE


def build_gate_failure_detail(
  *,
  build_gate_result: dict[str, Any],
  rolled_back: bool,
  **extra: Any,
) -> dict[str, Any]:
  detail = {
    "files_committed": not rolled_back,
    "rolled_back": rolled_back,
    "user_message": build_gate_failure_user_message(rolled_back=rolled_back),
    "category": "preview_build",
    "code": "build_gate_failed",
  }
  detail.update(extra)
  if not rolled_back:
    detail.setdefault(
      "suggested_actions",
      [
        "Your updated files are already saved — open them in the file tree.",
        "Retry Preview when your network or build environment is stable.",
        "Ask the agent to fix only the files listed in the build log.",
      ],
    )
  return detail
