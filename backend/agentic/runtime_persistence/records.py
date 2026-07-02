from __future__ import annotations

from typing import Any

try:
  from ...storage import PostgresStore, UserContext
except ImportError:
  from storage import PostgresStore, UserContext

from .utils import generation_intent, object_value, text_value

def record_tool_calls(
  store: PostgresStore,
  *,
  agent_run_id: str,
  user: UserContext,
  prompt: str,
  generation: dict[str, Any],
) -> None:
  runtime_trace = generation.get("gemini_tool_calling_setup", {}).get("runtime_trace") or {}
  trace_tool_calls = runtime_trace.get("tool_calls")
  if isinstance(trace_tool_calls, list) and trace_tool_calls:
    for index, tool_call in enumerate(trace_tool_calls, start=1):
      if not isinstance(tool_call, dict):
        continue
      store.record_tool_call(
        agent_run_id,
        user,
        tool_name=text_value(tool_call.get("name"), f"tool_{index}"),
        call_id=text_value(tool_call.get("call_id"), f"trace-tool-{index}"),
        status=text_value(tool_call.get("status"), "completed"),
        arguments=object_value(tool_call.get("arguments")),
        result=object_value(tool_call.get("output")),
        error=tool_call.get("error") if isinstance(tool_call.get("error"), str) else None,
      )
    return

  routing_result = generation.get("multi_agent_system", {}).get("routing_result") or {}
  generated_website = generation.get("orchestration_flow", {}).get("generated_website") or {}
  files = generated_website.get("files") if isinstance(generated_website, dict) else []
  sections = generated_website.get("sections") if isinstance(generated_website, dict) else []
  file_items = files if isinstance(files, list) else []
  section_items = sections if isinstance(sections, list) else []

  store.record_tool_call(
    agent_run_id,
    user,
    tool_name="route_generation_action",
    call_id="route-generation-action-1",
    status="completed",
    arguments={"message": prompt, "conversation_context": "website_builder_chat"},
    result=object_value(routing_result),
  )

  if generation_intent(generation) != "website_generation":
    conversation_response = generation.get("multi_agent_system", {}).get("conversation_response") or {}
    next_tool = text_value(routing_result.get("next_tool"), "conversation_response")
    store.record_tool_call(
      agent_run_id,
      user,
      tool_name=next_tool,
      call_id=f"{next_tool}-1",
      status="completed",
      arguments={"message": prompt},
      result=object_value(conversation_response),
    )
    return

  store.record_tool_call(
    agent_run_id,
    user,
    tool_name="analyze_prompt",
    call_id="analyze-prompt-1",
    status="completed",
    arguments={"prompt": prompt},
    result={
      "website_title": generated_website.get("title"),
      "section_count": len(section_items),
    },
  )
  store.record_tool_call(
    agent_run_id,
    user,
    tool_name="generate_website_files",
    call_id="generate-website-files-1",
    status="completed",
    arguments={"website_title": generated_website.get("title")},
    result={
      "file_count": len(file_items),
      "paths": [file_item.get("path") for file_item in file_items if isinstance(file_item, dict)],
    },
  )
  store.record_tool_call(
    agent_run_id,
    user,
    tool_name="validate_generated_website",
    call_id="validate-generated-website-1",
    status="completed",
    arguments={"website_title": generated_website.get("title")},
    result={
      "status": "prepared",
      "section_count": len(section_items),
      "file_count": len(file_items),
    },
  )

def record_agent_handoffs(
  store: PostgresStore,
  *,
  agent_run_id: str,
  user: UserContext,
  generation: dict[str, Any],
) -> None:
  communication = generation.get("agent_to_agent_communication") or {}
  a2a_runtime = communication.get("a2a_runtime") if isinstance(communication, dict) else None
  a2a_messages = a2a_runtime.get("messages") if isinstance(a2a_runtime, dict) else None
  if isinstance(a2a_messages, list):
    for message in a2a_messages:
      if not isinstance(message, dict):
        continue
      store.record_agent_message(
        agent_run_id,
        user,
        from_agent=text_value(message.get("from_agent"), "Source Agent"),
        to_agent=text_value(message.get("to_agent"), "Target Agent"),
        role="agent",
        content=text_value(message.get("intent"), "Agent handoff completed."),
        payload=message,
      )
    return

  agentic_handoffs = communication.get("agentic_handoffs") if isinstance(communication, dict) else None
  if isinstance(agentic_handoffs, list):
    for handoff in agentic_handoffs:
      if not isinstance(handoff, dict):
        continue
      store.record_agent_message(
        agent_run_id,
        user,
        from_agent=text_value(handoff.get("from_agent"), "Source Agent"),
        to_agent=text_value(handoff.get("to_agent"), "Target Agent"),
        role="agent",
        content=text_value(handoff.get("message", {}).get("next_action") if isinstance(handoff.get("message"), dict) else None, "Agent handoff completed."),
        payload=handoff,
      )

  contract = communication.get("message_contract") if isinstance(communication, dict) else None
  if not isinstance(contract, dict):
    return
  store.record_agent_message(
    agent_run_id,
    user,
    from_agent=text_value(contract.get("from_agent"), "Supervisor Agent"),
    to_agent=text_value(contract.get("to_agent"), "Worker Agent"),
    role="agent",
    content=text_value(contract.get("task"), "Agent handoff completed."),
    payload=contract,
  )
