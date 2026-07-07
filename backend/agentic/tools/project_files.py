from __future__ import annotations

from typing import Any

try:
  from ...storage import UserContext
except ImportError:
  from storage import UserContext

_STORE_FILE_CACHE: dict[int, dict[tuple[str, str], list[dict[str, Any]]]] = {}


def _store_cache(store: Any) -> dict[tuple[str, str], list[dict[str, Any]]] | None:
  try:
    store_bucket = _STORE_FILE_CACHE.get(id(store))
  except Exception:
    return None
  if store_bucket is None:
    store_bucket = {}
    _STORE_FILE_CACHE[id(store)] = store_bucket
  return store_bucket


def snapshot_project_files(context: Any, user: UserContext, project_id: str, *, refresh: bool = False) -> list[dict[str, Any]]:
  store = getattr(context, "store", None)
  if store is None or not hasattr(store, "list_files"):
    return []
  cache = _store_cache(store)
  cache_key = (user.id, project_id)
  if cache is not None and not refresh and cache_key in cache:
    return [dict(item) for item in cache[cache_key]]
  files = store.list_files(project_id, user)
  normalized = [dict(item) for item in files if isinstance(item, dict)]
  if cache is not None:
    cache[cache_key] = [dict(item) for item in normalized]
  return normalized


def invalidate_project_files_snapshot(context: Any, user: UserContext | None = None, project_id: str | None = None) -> None:
  store = getattr(context, "store", None)
  if store is None:
    return
  cache = _store_cache(store)
  if cache is None:
    return
  if user is not None and project_id is not None:
    cache.pop((user.id, project_id), None)
    return
  if user is not None:
    keys_to_remove = [key for key in cache if key[0] == user.id]
    for key in keys_to_remove:
      cache.pop(key, None)
    return
  if project_id is not None:
    keys_to_remove = [key for key in cache if key[1] == project_id]
    for key in keys_to_remove:
      cache.pop(key, None)
    return
  cache.clear()
