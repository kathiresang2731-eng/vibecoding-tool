import json
import uuid
from datetime import datetime, timezone
from typing import Any

from src.config import (
    INDEX_EPISODE,
    INDEX_PREFERENCE,
    INDEX_PROFILE,
    PROCEDURE_FILES,
    SCOPE_PERSONAL,
)
from src.meili_client import client, ensure_indexes_ready
from src.retriever import get_user_preferences, retrieve_episodes


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── Tool schemas ──────────────────────────────────────────────────────────────

user_profile_extractor_schema = {
    "type": "function",
    "function": {
        "name": "user_profile_extractor",
        "description": "Store or update user profile memory in Meilisearch (scoped by user_id).",
        "parameters": {
            "type": "object",
            "properties": {
                "user_profile_memory": {
                    "type": "object",
                    "properties": {
                        "display_name": {"type": "string"},
                        "project_name": {"type": "string"},
                        "framework": {"type": "string"},
                        "language": {"type": "string"},
                        "ui_library": {"type": "string"},
                        "database": {"type": "string"},
                        "auth_provider": {"type": "string"},
                        "deployment_target": {"type": "string"},
                        "current_goal": {"type": "string"},
                        "pain_points": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                }
            },
            "required": ["user_profile_memory"],
        },
    },
}

user_preference_extractor_schema = {
    "type": "function",
    "function": {
        "name": "user_preference_extractor",
        "description": "Store user coding preferences in Meilisearch (scoped by user_id).",
        "parameters": {
            "type": "object",
            "properties": {
                "preference_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string"},
                            "preference": {"type": "string"},
                            "polarity": {
                                "type": "string",
                                "enum": ["positive", "negative", "neutral"],
                            },
                            "confidence": {"type": "number"},
                            "reason": {"type": "string"},
                            "durability": {
                                "type": "string",
                                "enum": ["short_term", "long_term"],
                            },
                        },
                        "required": ["category", "preference", "polarity"],
                    },
                }
            },
            "required": ["preference_items"],
        },
    },
}

episode_extractor_schema = {
    "type": "function",
    "function": {
        "name": "episode_extractor",
        "description": "Store personal episodic memory for a user (scoped by user_id).",
        "parameters": {
            "type": "object",
            "properties": {
                "episodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "memory_type": {
                                "type": "string",
                                "enum": [
                                    "workflow",
                                    "tool_pattern",
                                    "fix_pattern",
                                    "conversation_improvement",
                                ],
                            },
                            "title": {"type": "string"},
                            "searchable_summary": {"type": "string"},
                            "situation": {"type": "string"},
                            "stack_tags": {"type": "string"},
                            "improved_behavior": {"type": "string"},
                            "avoid": {"type": "string"},
                        },
                        "required": [
                            "memory_type",
                            "title",
                            "searchable_summary",
                            "situation",
                            "improved_behavior",
                        ],
                    },
                }
            },
            "required": ["episodes"],
        },
    },
}

episode_retriever_schema = {
    "type": "function",
    "function": {
        "name": "episode_retriever",
        "description": (
            "Retrieve personal episodic memories for the current user by intent. "
            "Use when a similar past coding session may inform this task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": (
                        "Short natural-language intent, e.g. "
                        "'fix Next.js hydration error' or 'add Supabase auth'."
                    ),
                }
            },
            "required": ["intent"],
        },
    },
}

get_procedure_schema = {
    "type": "function",
    "function": {
        "name": "get_procedure",
        "description": "Load a dev workflow playbook into context before structured tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "procedure_name": {
                    "type": "string",
                    "enum": list(PROCEDURE_FILES.keys()),
                }
            },
            "required": ["procedure_name"],
        },
    },
}

get_project_context_schema = {
    "type": "function",
    "function": {
        "name": "get_project_context",
        "description": (
            "Stub: return current project context (files, stack). "
            "Wire to your vibe-coding IDE in production."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Optional path or area, e.g. 'src/components' or 'auth'.",
                }
            },
        },
    },
}


# ── Handlers ──────────────────────────────────────────────────────────────────

def store_user_profile(payload: dict[str, Any], user_id: str, **kwargs) -> dict[str, Any]:
    profile = payload.get("user_profile_memory") or {}
    if not profile:
        return {"status": "skipped", "reason": "empty profile"}

    ensure_indexes_ready()
    profile["id"] = f"prof_{user_id}"
    profile["user_id"] = user_id
    profile["updated_at"] = _now_iso()

    task = client.index(INDEX_PROFILE).add_documents([profile])
    client.wait_for_task(task.task_uid, timeout_in_ms=120_000)
    return {"status": "success", "id": profile["id"]}


def store_user_preferences(payload: dict[str, Any], user_id: str, **kwargs) -> dict[str, Any]:
    items = payload.get("preference_items") or []
    if not items:
        return {"status": "skipped", "reason": "empty preferences"}

    ensure_indexes_ready()
    existing = get_user_preferences(user_id)
    existing_keys = {
        (p.get("category", "").lower(), p.get("preference", "").lower())
        for p in existing
    }

    docs = []
    now = _now_iso()
    for item in items:
        key = (item.get("category", "").lower(), item.get("preference", "").lower())
        if key in existing_keys:
            continue
        doc = dict(item)
        doc["id"] = _doc_id("pref")
        doc["user_id"] = user_id
        doc["created_at"] = now
        docs.append(doc)
        existing_keys.add(key)

    if not docs:
        return {"status": "skipped", "reason": "all preferences already stored"}

    task = client.index(INDEX_PREFERENCE).add_documents(docs)
    client.wait_for_task(task.task_uid, timeout_in_ms=120_000)
    return {"status": "success", "count": len(docs)}


def store_episodes(payload: dict[str, Any], user_id: str, **kwargs) -> dict[str, Any]:
    episodes = payload.get("episodes") or []
    if not episodes:
        return {"status": "skipped", "reason": "no episodes"}

    ensure_indexes_ready()
    docs = []
    now = _now_iso()
    for ep in episodes:
        doc = dict(ep)
        doc["id"] = _doc_id("ep")
        doc["user_id"] = user_id
        doc["scope"] = SCOPE_PERSONAL
        doc["created_at"] = now
        docs.append(doc)

    task = client.index(INDEX_EPISODE).add_documents(docs)
    client.wait_for_task(task.task_uid, timeout_in_ms=120_000)
    return {"status": "success", "count": len(docs)}


def episode_retriever(intent: str, user_id: str, **kwargs) -> dict[str, Any]:
    return retrieve_episodes(user_id, intent)


def handle_get_procedure(procedure_name: str, **kwargs) -> str:
    path = PROCEDURE_FILES.get(procedure_name)
    if not path:
        valid = ", ".join(PROCEDURE_FILES.keys())
        raise ValueError(f"Unknown procedure '{procedure_name}'. Valid: {valid}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def get_project_context(focus: str = "", user_id: str = "", **kwargs) -> dict[str, Any]:
    return {
        "status": "stub",
        "message": "Connect get_project_context to your IDE file tree and build state.",
        "user_id": user_id,
        "focus": focus or "project root",
        "files": [],
    }


EXTRACTION_TOOLS = [
    user_profile_extractor_schema,
    user_preference_extractor_schema,
    episode_extractor_schema,
]

CHAT_TOOLS = [
    episode_retriever_schema,
    get_procedure_schema,
    get_project_context_schema,
]

TOOL_HANDLERS = {
    "user_profile_extractor": store_user_profile,
    "user_preference_extractor": store_user_preferences,
    "episode_extractor": store_episodes,
    "episode_retriever": episode_retriever,
    "get_procedure": handle_get_procedure,
    "get_project_context": get_project_context,
}
