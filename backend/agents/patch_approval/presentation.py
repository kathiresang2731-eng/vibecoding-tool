from __future__ import annotations

from typing import Any


def public_patch_approval_brief(pending: dict[str, Any]) -> dict[str, Any]:
  diff_detail = pending.get("diff_detail") if isinstance(pending.get("diff_detail"), dict) else {}
  return {
    "status": pending.get("status", "pending"),
    "paths": list(pending.get("paths") or []),
    "file_count": diff_detail.get("file_count") or len(pending.get("paths") or []),
    "added": diff_detail.get("added"),
    "removed": diff_detail.get("removed"),
    "diff_detail": diff_detail,
  }


def patch_approval_conversation_response(pending: dict[str, Any], *, message: str | None = None) -> dict[str, Any]:
  paths = list(pending.get("paths") or [])
  path_summary = ", ".join(paths[:3])
  if len(paths) > 3:
    path_summary = f"{path_summary}, +{len(paths) - 3} more"
  default_message = (
    "I prepared code changes and paused before committing them to your project.\n\n"
    f"Files: {path_summary or 'updated files'}\n\n"
    "Review the patch diff in the workspace panel, then approve to apply or reject to discard."
  )
  return {
    "type": "awaiting_patch_approval",
    "message": message or default_message,
    "next_prompt_guidance": [
      "Approve and apply the proposed patch",
      "Reject the proposed patch",
      "Ask for a revised change",
    ],
    "patch_approval": public_patch_approval_brief(pending),
  }
