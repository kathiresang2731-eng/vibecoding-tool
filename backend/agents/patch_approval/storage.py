from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .constants import PATCH_APPROVAL_KEY, PATCH_APPROVAL_NAMESPACE

try:
  from ..schema.json_safe import json_dumps_for_persistence
except ImportError:
  from schema.json_safe import json_dumps_for_persistence


def patch_approval_store_ready(tool_context: Any) -> bool:
  store = getattr(tool_context, "store", None)
  return bool(
    store is not None
    and hasattr(store, "list_memory_items")
    and hasattr(store, "upsert_memory_item")
  )


def load_pending_patch(tool_context: Any, user: Any, *, project_id: str) -> dict[str, Any] | None:
  if not patch_approval_store_ready(tool_context):
    return None
  memories = tool_context.store.list_memory_items(
    user,
    project_id=project_id,
    namespace=PATCH_APPROVAL_NAMESPACE,
    limit=5,
  )
  for memory in memories:
    if not isinstance(memory, dict) or memory.get("key") != PATCH_APPROVAL_KEY:
      continue
    try:
      content = json.loads(str(memory.get("content") or "{}"))
    except json.JSONDecodeError:
      return None
    if not isinstance(content, dict):
      continue
    status = str(content.get("status") or "").strip()
    if status == "pending":
      return content
  return None


def persist_pending_patch(tool_context: Any, user: Any, *, project_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
  pending = {
    **snapshot,
    "status": "pending",
    "updated_at": datetime.now(timezone.utc).isoformat(),
  }
  tool_context.store.upsert_memory_item(
    user,
    project_id=project_id,
    namespace=PATCH_APPROVAL_NAMESPACE,
    key=PATCH_APPROVAL_KEY,
    kind="pending_patch",
    content=json_dumps_for_persistence(pending, context="patch_approval.pending"),
    metadata={
      "status": "pending",
      "path_count": len(pending.get("paths") or []),
    },
  )
  return pending


def resolve_pending_patch(
  tool_context: Any,
  user: Any,
  *,
  project_id: str,
  pending: dict[str, Any],
  status: str,
) -> dict[str, Any]:
  resolved = {
    **pending,
    "status": status,
    "resolved_at": datetime.now(timezone.utc).isoformat(),
  }
  tool_context.store.upsert_memory_item(
    user,
    project_id=project_id,
    namespace=PATCH_APPROVAL_NAMESPACE,
    key=PATCH_APPROVAL_KEY,
    kind="pending_patch",
    content=json_dumps_for_persistence(resolved, context="patch_approval.resolved"),
    metadata={
      "status": status,
      "path_count": len(resolved.get("paths") or []),
    },
  )
  return resolved
