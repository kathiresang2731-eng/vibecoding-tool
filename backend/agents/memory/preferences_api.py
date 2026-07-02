from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .context import MIN_PREFERENCE_CONFIDENCE, _SKIPPED_PREFERENCE_DURABILITY

ALLOWED_POLARITIES = frozenset({"positive", "negative"})
ALLOWED_DURABILITIES = frozenset({"long_term", "session", "ephemeral", "temporary"})


def preference_is_injected(row: dict[str, Any]) -> bool:
  confidence = float(row.get("confidence") or 0)
  durability = str(row.get("durability") or "long_term").strip().lower()
  return confidence >= MIN_PREFERENCE_CONFIDENCE and durability not in _SKIPPED_PREFERENCE_DURABILITY


def serialize_memory_preference(row: dict[str, Any]) -> dict[str, Any]:
  return {
    "id": row.get("id"),
    "category": row.get("category"),
    "preference": row.get("preference"),
    "polarity": row.get("polarity"),
    "confidence": float(row.get("confidence") or 0),
    "durability": row.get("durability"),
    "reason": row.get("reason") or "",
    "metadata": row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {},
    "injected_into_agent_context": preference_is_injected(row),
    "created_at": row.get("created_at"),
    "updated_at": row.get("updated_at"),
  }


def list_memory_preferences_payload(user: Any, store: Any, *, limit: int = 50) -> dict[str, Any]:
  if not hasattr(store, "list_memory_preferences"):
    return {"preferences": [], "schema": "worktual.memory-preferences.v1"}
  rows = store.list_memory_preferences(user, limit=max(1, min(limit, 100)))
  preferences = [serialize_memory_preference(row) for row in rows if isinstance(row, dict)]
  return {
    "schema": "worktual.memory-preferences.v1",
    "preferences": preferences,
    "injection_rules": {
      "min_confidence": MIN_PREFERENCE_CONFIDENCE,
      "skipped_durability": sorted(_SKIPPED_PREFERENCE_DURABILITY),
    },
  }


def upsert_memory_preference_payload(user: Any, request: Any, store: Any) -> dict[str, Any]:
  try:
    from ...storage import StorageError
  except ImportError:
    from storage import StorageError

  if not hasattr(store, "upsert_memory_preference"):
    raise HTTPException(status_code=501, detail="Memory preferences are not available on this store.")
  category = str(getattr(request, "category", "") or "").strip()
  preference = str(getattr(request, "preference", "") or "").strip()
  if not category or not preference:
    raise HTTPException(status_code=400, detail="Category and preference text are required.")
  polarity = str(getattr(request, "polarity", "positive") or "positive").strip().lower()
  if polarity not in ALLOWED_POLARITIES:
    raise HTTPException(status_code=400, detail="Polarity must be positive or negative.")
  durability = str(getattr(request, "durability", "long_term") or "long_term").strip().lower()
  if durability not in ALLOWED_DURABILITIES:
    raise HTTPException(status_code=400, detail="Durability must be long_term, session, ephemeral, or temporary.")
  confidence = float(getattr(request, "confidence", 0.85))
  if confidence < 0 or confidence > 1:
    raise HTTPException(status_code=400, detail="Confidence must be between 0 and 1.")
  metadata = getattr(request, "metadata", None)
  reason = str(getattr(request, "reason", "") or "").strip()
  try:
    row = store.upsert_memory_preference(
      user,
      category=category,
      preference=preference,
      polarity=polarity,
      confidence=confidence,
      durability=durability,
      reason=reason,
      metadata=metadata or {},
    )
  except StorageError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  return {
    "schema": "worktual.memory-preferences.v1",
    "preference": serialize_memory_preference(row),
  }


def delete_memory_preference_payload(user: Any, preference_id: str, store: Any) -> dict[str, Any]:
  try:
    from ...storage import StorageError
  except ImportError:
    from storage import StorageError

  if not hasattr(store, "delete_memory_preference"):
    raise HTTPException(status_code=501, detail="Memory preferences are not available on this store.")
  try:
    deleted = store.delete_memory_preference(user, preference_id=preference_id)
  except StorageError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  if not deleted:
    raise HTTPException(status_code=404, detail="Preference not found.")
  return {"deleted": True, "id": preference_id}
