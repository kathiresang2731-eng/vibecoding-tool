from __future__ import annotations

from typing import Any

try:
  from ...storage import PostgresStore, UserContext
except ImportError:
  from storage import PostgresStore, UserContext

from .memory import build_memory_summary
from .records import record_agent_handoffs, record_tool_calls
from .utils import active_agent_name, generation_intent, text_value

def persist_agent_runtime_output(
  store: PostgresStore,
  *,
  agent_run_id: str,
  user: UserContext,
  prompt: str,
  generation: dict[str, Any],
  generation_run: dict[str, Any],
  files: list[dict[str, Any]],
  local_sync: dict[str, Any] | None,
  local_sync_error: str | None,
) -> None:
  intent = generation_intent(generation)
  generated_website = generation.get("orchestration_flow", {}).get("generated_website") or {}
  tool_sequence = generation.get("gemini_tool_calling_setup", {}).get("tool_call_sequence") or []
  conversation_response = generation.get("multi_agent_system", {}).get("conversation_response") or {}
  response_message = text_value(conversation_response.get("message"), "Request handled.")

  store.record_agent_message(
    agent_run_id,
    user,
    from_agent="User",
    to_agent="Intent Router Agent",
    role="user",
    content=prompt,
    payload={"messages": [{"role": "user", "content": prompt}]},
  )
  record_tool_calls(store, agent_run_id=agent_run_id, user=user, prompt=prompt, generation=generation)
  record_agent_handoffs(store, agent_run_id=agent_run_id, user=user, generation=generation)
  store.record_agent_message(
    agent_run_id,
    user,
    from_agent=active_agent_name(generation),
    to_agent="User",
    role="assistant",
    content=response_message,
    payload={
      "intent": intent,
      "conversation_response": conversation_response,
      "file_count": len(files),
      "local_sync": local_sync,
      "local_sync_error": local_sync_error,
    },
  )

  store.record_generation_checkpoint(
    agent_run_id,
    user,
    thread_id=str(generation_run.get("id") or agent_run_id),
    step_name="generation.completed",
    state={
      "intent": intent,
      "generation_run_id": generation_run.get("id"),
      "tool_call_sequence": tool_sequence,
      "file_count": len(files),
      "local_sync": local_sync,
      "local_sync_error": local_sync_error,
    },
  )

  memory_content = build_memory_summary(
    prompt=prompt,
    intent=intent,
    generated_website=generated_website,
    file_count=len(files),
    response_message=response_message,
  )
  store.upsert_memory_item(
    user,
    project_id=str(generation_run["project_id"]),
    namespace="project",
    key="latest_generation_summary",
    kind="summary",
    content=memory_content,
    metadata={
      "generation_run_id": generation_run.get("id"),
      "agent_run_id": agent_run_id,
      "intent": intent,
      "tool_call_sequence": tool_sequence,
    },
  )
