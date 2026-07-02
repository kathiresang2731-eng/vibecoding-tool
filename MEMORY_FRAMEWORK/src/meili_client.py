"""Shared Meilisearch client and one-time index bootstrap."""

from __future__ import annotations

import meilisearch
from meilisearch.errors import MeilisearchApiError

from src.config import (
    INDEX_EPISODE,
    INDEX_PREFERENCE,
    INDEX_PROFILE,
    MEILISEARCH_KEY,
    MEILISEARCH_URL,
)

client = meilisearch.Client(MEILISEARCH_URL, MEILISEARCH_KEY)

# filterable fields required before `user_id = "..."` filters work
INDEX_FILTERABLE: dict[str, list[str]] = {
    INDEX_PROFILE: ["user_id"],
    INDEX_PREFERENCE: ["user_id"],
    INDEX_EPISODE: ["user_id", "scope"],
}

_indexes_ready = False


def ensure_indexes_ready() -> None:
    """Create indexes if missing and wait until filterable attributes are active."""
    global _indexes_ready
    if _indexes_ready:
        return

    for index_name, filterable in INDEX_FILTERABLE.items():
        try:
            client.create_index(index_name, {"primaryKey": "id"})
        except MeilisearchApiError as exc:
            # index already exists — expected on subsequent runs
            if exc.code != "index_already_exists":
                raise

        task = client.index(index_name).update_filterable_attributes(filterable)
        client.wait_for_task(task.task_uid, timeout_in_ms=120_000)

    _indexes_ready = True


def search(index_name: str, query: str, options: dict | None = None) -> dict:
    """Run a search after indexes are ready; fall back if hybrid search is unavailable."""
    ensure_indexes_ready()
    opts = options or {}
    index = client.index(index_name)

    try:
        return index.search(query, opts)
    except MeilisearchApiError as exc:
        if "hybrid" not in opts:
            raise
        # embedder not configured — keyword search still works for testing
        fallback = {k: v for k, v in opts.items() if k != "hybrid"}
        try:
            return index.search(query, fallback)
        except MeilisearchApiError:
            raise exc
