import json
import time
from datetime import datetime, timezone

from pydantic import BaseModel

from src.llm import OpenAILLM
from src.memory import SessionManager
from src.prompt import system_prompt
from src.retriever import get_user_preferences, get_user_profile
from src.tools import CHAT_TOOLS, TOOL_HANDLERS

with open("skills/initial_session.md", encoding="utf-8") as f:
    default_procedure = f.read()

session_manager = SessionManager()
LLM = OpenAILLM()


class ChatRequest(BaseModel):
    userID: str
    sessionID: str
    query: str


def _format_profile(hits: list) -> str:
    if not hits:
        return "No profile memory yet for this user."
    return json.dumps(hits[0], indent=2, default=str)


def _format_preferences(hits: list) -> str:
    if not hits:
        return "No preference memory yet for this user."
    return json.dumps(hits, indent=2, default=str)


def _inject_tool_context(handler_kwargs: dict, session_id: str, user_id: str) -> dict:
    return {**handler_kwargs, "session_id": session_id, "user_id": user_id}


def _run_tool_loop(memory, request: ChatRequest, base_system_prompt: str) -> tuple[dict, list]:
    message = memory.get_session_messages()
    res = LLM.run(messages=message, tools=CHAT_TOOLS)

    if res.get("content"):
        memory.add_session_messages({"role": "assistant", "content": res["content"]})
        return res, memory.get_session_messages()

    while True:
        for tool_call in res.get("tool_calls") or []:
            memory.add_session_messages({"role": "assistant", "tool_calls": [tool_call]})

            fn_name = tool_call["function"]["name"]
            args = json.loads(tool_call["function"]["arguments"])
            handler = TOOL_HANDLERS[fn_name]
            tool_response = handler(
                **_inject_tool_context(args, request.sessionID, request.userID)
            )

            if fn_name == "get_procedure":
                procedure_text = tool_response if isinstance(tool_response, str) else str(tool_response)
                memory.memory[0]["content"] = base_system_prompt.format(
                    st_profile=_format_profile(get_user_profile(request.userID)),
                    st_pref=_format_preferences(get_user_preferences(request.userID)),
                    date_time=datetime.now(timezone.utc).isoformat(),
                    procedure=procedure_text,
                )
                tool_content = "Procedure loaded into context."
            else:
                tool_content = json.dumps(tool_response, default=str)

            memory.add_session_messages(
                {
                    "role": "tool",
                    "name": fn_name,
                    "tool_call_id": tool_call["id"],
                    "content": tool_content,
                }
            )

        message = memory.get_session_messages()
        res = LLM.run(messages=message, tools=CHAT_TOOLS)

        if res.get("content"):
            memory.add_session_messages({"role": "assistant", "content": res["content"]})
            return res, memory.get_session_messages()


def generate_response(request: ChatRequest) -> tuple[dict, list]:
    start = time.time()
    profile_hits = get_user_profile(request.userID)
    pref_hits = get_user_preferences(request.userID)
    date_time = datetime.now(timezone.utc).isoformat()

    formatted_system = system_prompt.format(
        st_profile=_format_profile(profile_hits),
        st_pref=_format_preferences(pref_hits),
        date_time=date_time,
        procedure=default_procedure,
    )

    if not session_manager.is_session_present(request.sessionID):
        memory = session_manager.create_memory(request.sessionID, formatted_system)
    else:
        memory = session_manager.get_memory(request.sessionID)
        memory.memory[0]["content"] = formatted_system

    memory.add_session_messages({"role": "user", "content": request.query})

    res, full_conversation = _run_tool_loop(memory, request, system_prompt)
    print(f"response time: {time.time() - start:.2f}s")
    return res, full_conversation


# Backward-compatible alias for app import
Generate_response = generate_response
