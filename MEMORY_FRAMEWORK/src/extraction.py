import json
import re
from typing import Any

from src.extractors import (
    EPISODE_EXTRACTOR_PROMPT,
    USER_PREFERENCE_EXTRACTOR_PROMPT,
    USER_PROFILE_EXTRACTOR_PROMPT,
)
from src.llm import OpenAILLM
from src.tools import (
    TOOL_HANDLERS,
    episode_extractor_schema,
    user_preference_extractor_schema,
    user_profile_extractor_schema,
)

LLM = OpenAILLM()

MAX_RETRIES = 3

EXTRACTOR_CONFIG = {
    "user_profile_extractor": {
        "prompt": USER_PROFILE_EXTRACTOR_PROMPT,
        "tool_schema": user_profile_extractor_schema,
    },
    "user_preference_extractor": {
        "prompt": USER_PREFERENCE_EXTRACTOR_PROMPT,
        "tool_schema": user_preference_extractor_schema,
    },
    "episode_extractor": {
        "prompt": EPISODE_EXTRACTOR_PROMPT,
        "tool_schema": episode_extractor_schema,
    },
}

RETRY_NUDGE = (
    "You did not call the required tool. "
    "Do NOT write a user-facing reply. "
    "Call the tool NOW with the extracted JSON payload."
)


def _tool_choice_for(tool_name: str) -> dict:
    return {"type": "function", "function": {"name": tool_name}}


def _fallback_profile(convo: list) -> dict[str, Any] | None:
    """Rule-based backup when the LLM skips the tool call."""
    text = " ".join(
        m.get("content", "")
        for m in convo
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    )
    if not text.strip():
        return None

    profile: dict[str, str] = {}

    name_match = re.search(r"project name is ['\"]?([^'\".\n]+)", text, re.I)
    if name_match:
        profile["project_name"] = name_match.group(1).strip()

    if re.search(r"next\.?js", text, re.I):
        ver = re.search(r"next\.?js\s*(\d+)", text, re.I)
        profile["framework"] = f"Next.js {ver.group(1)}" if ver else "Next.js"

    if re.search(r"typescript", text, re.I):
        profile["language"] = "TypeScript"
    elif re.search(r"javascript", text, re.I):
        profile["language"] = "JavaScript"

    if re.search(r"tailwind", text, re.I):
        profile["ui_library"] = "Tailwind CSS"

    if not profile:
        return None

    return {"user_profile_memory": profile}


def _run_extractor(tool_name: str, convo: list, user_id: str) -> dict[str, Any]:
    config = EXTRACTOR_CONFIG[tool_name]
    tool_schema = config["tool_schema"]
    handler = TOOL_HANDLERS[tool_name]

    memory = [
        {
            "role": "system",
            "content": config["prompt"]
            + f"\n\nREQUIRED: You MUST call `{tool_name}` exactly once. "
            "Never respond with plain text only.",
        },
        {"role": "user", "content": json.dumps(convo, default=str)},
    ]

    tool_results: list[dict[str, Any]] = []

    for attempt in range(MAX_RETRIES):
        res = LLM.run(
            messages=memory,
            tools=[tool_schema],
            tool_choice=_tool_choice_for(tool_name),
        )

        if res.get("tool_calls"):
            memory.append({"role": "assistant", "tool_calls": res["tool_calls"]})

            for tool_call in res["tool_calls"]:
                if tool_call["function"]["name"] != tool_name:
                    continue
                arguments = json.loads(tool_call["function"]["arguments"])
                result = handler(arguments, user_id=user_id)
                tool_results.append(result)
                memory.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": tool_name,
                        "content": json.dumps(result, default=str),
                    }
                )

            return {
                "status": "stored",
                "tool": tool_name,
                "tool_results": tool_results,
                "attempts": attempt + 1,
            }

        memory.append({"role": "assistant", "content": res.get("content") or ""})
        memory.append({"role": "user", "content": RETRY_NUDGE})

    # Fallback for profile only
    if tool_name == "user_profile_extractor":
        fallback = _fallback_profile(convo)
        if fallback:
            result = handler(fallback, user_id=user_id)
            return {
                "status": "stored_fallback",
                "tool": tool_name,
                "tool_results": [result],
                "attempts": MAX_RETRIES,
            }

    if tool_name == "episode_extractor":
        result = handler({"episodes": []}, user_id=user_id)
        return {
            "status": "skipped",
            "tool": tool_name,
            "tool_results": [result],
            "attempts": MAX_RETRIES,
            "reason": "no tool call after retries; nothing to store",
        }

    return {
        "status": "failed",
        "tool": tool_name,
        "tool_results": tool_results,
        "attempts": MAX_RETRIES,
        "last_content": res.get("content"),
    }


def extract_episode_memory(convo: list, user_id: str) -> dict[str, Any]:
    return _run_extractor("episode_extractor", convo, user_id)


def extract_user_preferences(convo: list, user_id: str) -> dict[str, Any]:
    return _run_extractor("user_preference_extractor", convo, user_id)


def extract_user_profile(convo: list, user_id: str) -> dict[str, Any]:
    return _run_extractor("user_profile_extractor", convo, user_id)


def extract_all_memories(convo: list, user_id: str) -> dict[str, Any]:
    if not convo:
        return {"skipped": True, "reason": "empty conversation"}

    return {
        "profile": extract_user_profile(convo, user_id),
        "preferences": extract_user_preferences(convo, user_id),
        "episodes": extract_episode_memory(convo, user_id),
    }


agent_episode_extractor = extract_episode_memory
client_prefrance_extraction = extract_user_preferences
client_profile_extraction = extract_user_profile
