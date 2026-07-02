"""Retrieve user-scoped memories from Meilisearch."""

from typing import Any

from src.config import (
    INDEX_EPISODE,
    INDEX_PREFERENCE,
    INDEX_PROFILE,
    INCLUDE_SHARED_EPISODES,
    SCOPE_PERSONAL,
    SCOPE_SHARED,
)
from src.meili_client import ensure_indexes_ready, search


def get_user_profile(user_id: str) -> list[dict[str, Any]]:
    ensure_indexes_ready()
    results = search(
        INDEX_PROFILE,
        "",
        {"filter": f'user_id = "{user_id}"', "limit": 1},
    )
    return results.get("hits", [])


def get_user_preferences(user_id: str) -> list[dict[str, Any]]:
    ensure_indexes_ready()
    results = search(
        INDEX_PREFERENCE,
        "",
        {"filter": f'user_id = "{user_id}"', "limit": 50},
    )
    return results.get("hits", [])


def retrieve_personal_episodes(user_id: str, intent: str, limit: int = 3) -> list[dict[str, Any]]:
    ensure_indexes_ready()
    results = search(
        INDEX_EPISODE,
        intent,
        {
            "filter": f'user_id = "{user_id}" AND scope = "{SCOPE_PERSONAL}"',
            "hybrid": {"semanticRatio": 0.5, "embedder": "default"},
            "limit": limit,
        },
    )
    return results.get("hits", [])


def retrieve_shared_episodes(intent: str, limit: int = 3) -> list[dict[str, Any]]:
    ensure_indexes_ready()
    results = search(
        INDEX_EPISODE,
        intent,
        {
            "filter": f'scope = "{SCOPE_SHARED}"',
            "hybrid": {"semanticRatio": 0.5, "embedder": "default"},
            "limit": limit,
        },
    )
    return results.get("hits", [])


def retrieve_episodes(user_id: str, intent: str) -> dict[str, Any]:
    personal = retrieve_personal_episodes(user_id, intent)
    shared: list[dict[str, Any]] = []
    if INCLUDE_SHARED_EPISODES:
        shared = retrieve_shared_episodes(intent)
    return {"personal": personal, "shared": shared}
