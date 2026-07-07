from __future__ import annotations

import json
from typing import Any

from ..constants import DEFAULT_TOOL_REGISTRY, VISIBLE_AGENT_TEAM
from ..provider_utils import provider_name
from ..state import GenerationPipelineState
from .tools import build_selected_tool_arguments


def build_conversation_multi_agent_system(state: GenerationPipelineState, conversation_response: dict[str, Any]) -> dict[str, Any]:
  selected_tool = str(state.routing_result.get("next_tool") or "conversation_response")
  waiting_for_confirmation = state.intent == "needs_confirmation"
  run_state = "clarification_required" if state.intent in {"needs_confirmation", "needs_more_detail"} else "answer_only_completed"
  execution_plan = (
    (state.routing_result.get("orchestrator_brain") or {}).get("execution_plan")
    if isinstance(state.routing_result.get("orchestrator_brain"), dict)
    else None
  )
  target_resolution = (
    state.routing_result.get("target_resolution")
    if isinstance(state.routing_result.get("target_resolution"), dict)
    else {}
  )
  return {
    "goal": (
      "Present the execution brief and wait for explicit user confirmation."
      if waiting_for_confirmation
      else f"Execute the LLM-selected conversation tool {selected_tool} without generating or changing project files."
    ),
    "intent": state.intent,
    "active_agent": (
      "Requirement Confirmation Agent"
      if waiting_for_confirmation
      else "Intent Router Agent"
      if selected_tool == "handle_greeting"
      else "Read-only Assistant Agent"
    ),
    "routing_result": state.routing_result,
    "conversation_response": conversation_response,
    "agentic_runtime": {
      "engine": "conversation_response",
      "status": "completed",
      "run_state": run_state,
      "final_output": {
        "run_state": run_state,
        "preview_status": "not_applicable",
        "files_saved": False,
      },
      "diagnostic_report": {
        "query_class": "clarification" if run_state == "clarification_required" else "answer_only",
        "selected_path": (execution_plan or {}).get("primary_path") or "conversation_response",
        "mutation_allowed": False,
        "model_used": selected_tool not in {"handle_greeting"},
        "target_files": [],
        "candidate_files": [],
        "saved_paths": [],
        "save_status": "not_applicable",
        "preview_status": "not_applicable",
        "visual_qa_status": "not_applicable",
        "run_state": run_state,
        "target_resolution": target_resolution,
      },
    },
    "mutation_guard": {
      "mutation_allowed": False,
      "reason": "Conversation-only turns must not start artifact generation or project file writes.",
    },
    "agents": VISIBLE_AGENT_TEAM,
    "shared_state": {
      "prompt": state.user_prompt,
      "project_context": (
        "Execution brief is waiting for explicit user confirmation."
        if waiting_for_confirmation
        else f"Conversation tool {selected_tool} selected by the LLM router; artifact execution has not started."
      ),
      "website_blueprint": (
        "Waiting for user confirmation before execution."
        if waiting_for_confirmation
        else "Not applicable for this conversation-only turn."
      ),
      "generated_files": "No website files generated for this input.",
      "validation_report": "Routing tool handled the turn successfully.",
    },
  }


def build_conversation_gemini_tool_calling_setup(
  state: GenerationPipelineState,
  conversation_response: dict[str, Any],
  next_tool_name: str,
) -> dict[str, Any]:
  route_tool_call = {
    "call_id": "local-route-1",
    "name": "route_generation_action",
    "arguments": {
      "message": state.user_prompt,
      "conversation_context": "website_builder_chat",
    },
    "output": state.routing_result,
  }
  next_tool_call = {
    "call_id": f"local-{next_tool_name}-1",
    "name": next_tool_name,
    "arguments": build_selected_tool_arguments(state, next_tool_name),
    "output": {
      "intent": state.intent,
      "reply": conversation_response["message"],
      "next_prompt_guidance": conversation_response["next_prompt_guidance"],
    },
  }
  return {
    "tool_policy": "Conversation-only messages run on Gemini control and stop before artifact generation.",
    "provider": "gemini-native-control-artifact",
    "control_provider": provider_name(state.control_client),
    "artifact_provider": "not-used",
    "native_tool_calling": {
      "status": "available",
      "mode": "VALIDATED",
      "safety_boundary": "No artifact tools are called for greeting/detail-only turns.",
    },
    "tools": DEFAULT_TOOL_REGISTRY,
    "tool_call_sequence": ["route_generation_action", next_tool_name],
    "runtime_trace": {
      "runtime_status": "completed",
      "provider": "gemini-native-control-artifact",
      "model": provider_name(state.control_client),
      "tool_calls": [route_tool_call, next_tool_call],
      "steps": [
        {
          "agent": "intent_router_agent",
          "tool": "route_generation_action",
          "status": "completed",
        },
        {
          "agent": "intent_router_agent" if next_tool_name == "handle_greeting" else "read_only_assistant_agent",
          "tool": next_tool_name,
          "status": "completed",
        },
      ],
      "final_response_text": conversation_response["message"],
    },
  }


def build_conversation_google_adk_usage(state: GenerationPipelineState) -> dict[str, Any]:
  return {
    **state.prepared_sections["google_adk_usage"],
    "notes": [
      *state.prepared_sections["google_adk_usage"].get("notes", []),
      (
        "Requirement Confirmation Agent pauses high-impact work until the user explicitly approves the execution brief."
        if state.intent == "needs_confirmation"
        else (
          f"The LLM router selected {state.routing_result.get('next_tool')}; "
          "the turn stops before artifact generation."
        )
      ),
    ],
  }


def build_conversation_orchestration_flow(state: GenerationPipelineState, conversation_response: dict[str, Any]) -> dict[str, Any]:
  next_tool_name = state.routing_result["next_tool"]
  return {
    "steps": [
      {
        "step": 1,
        "name": "Tool-based intent routing",
        "owner_agent": "Intent Router Agent",
        "input": state.user_prompt,
        "actions": [
          "Call the LLM route_generation_action tool",
          f"Call the selected {next_tool_name} tool",
          "Return its response without artifact generation or file writes",
        ],
        "output": conversation_response["message"],
      },
    ],
    "generated_website": {
      "title": "Worktual AI Dev",
      "headline": "Tell me what website you want to build",
      "subheadline": "Start with your business type, brand name, sections, style, and required features.",
      "primary_cta": "Describe website",
      "secondary_cta": "Use example prompt",
      "preview_html": "",
      "sections": [
        {
          "name": "Prompt Guidance",
          "purpose": "Help the user provide enough detail for website generation.",
          "content": "Share what you want to build and Worktual AI Dev will generate the website preview and files.",
          "items": conversation_response["next_prompt_guidance"],
        },
      ],
      "files": [
        {
          "path": "conversation/response.json",
          "purpose": "Conversation response and next prompt guidance.",
          "code": json.dumps(conversation_response, indent=2),
        },
      ],
    },
  }


def build_conversation_agent_to_agent_communication(
  state: GenerationPipelineState,
  conversation_response: dict[str, Any],
) -> dict[str, Any]:
  waiting_for_confirmation = state.intent == "needs_confirmation"
  return {
    "message_contract": {
      "from_agent": "Intent Router Agent",
      "to_agent": "Prompt Analyst Agent",
      "sender": "Intent Router Agent",
      "receiver": "Prompt Analyst Agent",
      "task": (
        "Wait for explicit user approval of the execution brief."
        if waiting_for_confirmation
        else "Return the selected conversation tool response and wait for the next independently routed user turn."
      ),
      "input": {
        "received_message": state.user_prompt,
        "intent": state.intent,
      },
      "output": {
        "assistant_message": conversation_response["message"],
        "next_prompt_guidance": conversation_response["next_prompt_guidance"],
      },
      "next_action": "wait_for_user_confirmation" if waiting_for_confirmation else "respond_without_file_generation",
      "context": {
        "received_message": state.user_prompt,
        "intent": state.intent,
        "routing_result": state.routing_result,
      },
      "expected_output": {
        "next_user_message": (
          "explicit confirmation"
          if waiting_for_confirmation
          else "a new turn that will be classified again by the LLM router"
        ),
        "start_generation_when_ready": False,
      },
      "confidence": 0.98,
      "risks": ["A later user turn must be classified again before any artifact or file-write tool runs."],
    },
    "handoff_rules": [
      "Intent Router Agent owns action selection for every user turn.",
      "Intent Router Agent owns the handle_greeting tool for turns routed as greeting.",
      "Requirement Confirmation Agent owns approval before high-impact execution.",
      "Read-only Assistant Agent owns questions, general queries, and web search without file writes.",
      "Prompt Analyst Agent starts only after the user provides a website description.",
      "No website code generation runs for conversation-only input.",
    ],
    "example_messages": [
      {
        "from_agent": "Intent Router Agent",
        "to_agent": "User",
        "message": conversation_response,
      },
    ],
  }


def build_conversation_proactive_thinking(
  state: GenerationPipelineState,
  conversation_response: dict[str, Any],
) -> dict[str, Any]:
  waiting_for_confirmation = state.intent == "needs_confirmation"
  return {
    "assumptions": (
      ["The execution brief must be explicitly approved before work starts."]
      if waiting_for_confirmation
      else ["The routing tool decided this turn should not start website generation or file updates."]
    ),
    "missing_information": (
      conversation_response.get("confirmation", {}).get("open_questions", [])
      if waiting_for_confirmation
      else []
    ),
    "predicted_risks": (
      ["Starting high-impact work without confirmation could produce the wrong result."]
      if waiting_for_confirmation
      else ["A conversation-only route must not be promoted into artifact execution without a new LLM routing decision."]
    ),
    "self_checks": ["Action selected by route_generation_action", "No backend error returned", "Next prompt guidance provided"],
    "recommended_next_actions": conversation_response["next_prompt_guidance"],
  }
