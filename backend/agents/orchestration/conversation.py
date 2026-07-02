from __future__ import annotations

import json
from typing import Any

from ..prompts import CONVERSATION_SYSTEM_INSTRUCTION, build_conversation_response_prompt
from ..schema import ResponseContractError, sanitize_generation_response
from .constants import DEFAULT_AGENT_TEAM, DEFAULT_TOOL_REGISTRY
from .provider_utils import provider_name
from .state import GenerationPipelineState
from .tool_registry import log_tool_call


def compact_user_prompt(value: str, *, max_length: int = 80) -> str:
  compacted = " ".join(str(value or "").strip().split())
  if not compacted:
    return "hello"
  return compacted[:max_length].rstrip()


def fallback_greeting_message(state: GenerationPipelineState) -> str:
  greeting = compact_user_prompt(state.user_prompt)
  return (
    f"Hey{'' if greeting.lower() in {'hi', 'hello', 'hey'} else f' — {greeting.capitalize()}'}! "
    "I'm ready to help you build. What website or app do you have in mind, and who is it for?"
  )


def deterministic_conversation_response(state: GenerationPipelineState, *, error: str) -> dict[str, Any]:
  if state.intent == "greeting":
    message = fallback_greeting_message(state)
    guidance = ["Website type and brand name", "Target audience", "Sections and features", "Visual style"]
  else:
    prompt_context = compact_user_prompt(state.user_prompt)
    message = (
      f"I need a little more detail for: {prompt_context}.\n"
      "Please include the business type, brand name, audience, required sections, visual style, and must-have features."
    )
    guidance = ["Business or website type", "Brand name and audience", "Required sections", "Style and features"]
  return {
    "type": state.intent,
    "message": message,
    "received_message": state.user_prompt,
    "routing_result": {
      **state.routing_result,
      "fallback_reason": f"Gemini conversation response was unavailable: {error[:240]}",
    },
    "next_prompt_guidance": guidance,
  }

def generate_conversation_response(state: GenerationPipelineState, client: Any) -> dict[str, Any]:
  if state.conversation_response_override is not None:
    selected_tool = state.routing_result["next_tool"]
    log_tool_call(selected_tool, "output", state.conversation_response_override)
    return state.conversation_response_override
  selected_tool = state.routing_result["next_tool"]
  log_tool_call(
    selected_tool,
    "input",
    build_selected_tool_arguments(state, selected_tool),
  )
  prompt = build_conversation_response_prompt(
    state.user_prompt,
    intent=state.intent,
    selected_tool=selected_tool,
    routing_result=state.routing_result,
  )
  try:
    response = client.generate_json(
      prompt,
      system_instruction=CONVERSATION_SYSTEM_INSTRUCTION,
      trace_label=selected_tool,
    )
  except Exception as exc:
    fallback = deterministic_conversation_response(state, error=str(exc))
    log_tool_call(selected_tool, "fallback_output", fallback)
    return fallback
  log_tool_call(selected_tool, "raw_output", response)
  normalized = normalize_conversation_response(response, state)
  log_tool_call(selected_tool, "output", normalized)
  return normalized

def normalize_conversation_response(response: dict[str, Any], state: GenerationPipelineState) -> dict[str, Any]:
  if not isinstance(response, dict):
    raise ResponseContractError("Conversation tool response must be a JSON object.")

  message = response.get("message")
  guidance = response.get("next_prompt_guidance")
  if not isinstance(message, str) or not message.strip():
    raise ResponseContractError("Conversation tool response missing message.")
  if not isinstance(guidance, list) or not guidance or not all(isinstance(item, str) and item.strip() for item in guidance):
    raise ResponseContractError("Conversation tool response missing next_prompt_guidance.")

  return {
    "type": state.intent,
    "message": message.strip(),
    "received_message": state.user_prompt,
    "routing_result": state.routing_result,
    "next_prompt_guidance": [item.strip() for item in guidance],
  }

def build_conversation_generation_response(
  state: GenerationPipelineState,
  conversation_response: dict[str, Any],
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
  next_tool_name = state.routing_result["next_tool"]
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

  return sanitize_generation_response(
    {
      "multi_agent_system": {
        "goal": (
          "Handle a greeting and collect the website brief."
          if state.intent == "greeting"
          else "Present the execution brief and wait for explicit user confirmation."
          if state.intent == "needs_confirmation"
          else "Summarize the current live website without changing files."
          if state.intent == "project_info"
          else "Ask for more website details before generation."
        ),
        "intent": state.intent,
        "active_agent": (
          "Greeting Handler Agent"
          if state.intent == "greeting"
          else "Requirement Confirmation Agent"
          if state.intent == "needs_confirmation"
          else "Project Summary Agent"
          if state.intent == "project_info"
          else "Intent Router Agent"
        ),
        "routing_result": state.routing_result,
        "conversation_response": conversation_response,
        "agents": DEFAULT_AGENT_TEAM,
        "shared_state": {
          "prompt": state.user_prompt,
          "project_context": (
            "Execution brief is waiting for explicit user confirmation."
            if state.intent == "needs_confirmation"
            else "Current project information requested; no website generation or update has started."
            if state.intent == "project_info"
            else "Conversation-only input received; website generation has not started."
          ),
          "website_blueprint": (
            "Waiting for user confirmation before execution."
            if state.intent == "needs_confirmation"
            else "Current website summary and enhancement plan requested."
            if state.intent == "project_info"
            else "Waiting for user to describe the website."
          ),
          "generated_files": "No website files generated for this input.",
          "validation_report": "Routing tool handled the turn successfully.",
        },
      },
      "gemini_tool_calling_setup": {
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
          "final_response_text": conversation_response["message"],
        },
      },
      "google_adk_usage": {
        **state.prepared_sections["google_adk_usage"],
        "notes": [
          *state.prepared_sections["google_adk_usage"].get("notes", []),
          (
            "Requirement Confirmation Agent pauses high-impact work until the user explicitly approves the execution brief."
            if state.intent == "needs_confirmation"
            else "Greeting Handler Agent runs before the main website generation sequence."
          ),
        ],
      },
      "orchestration_flow": {
        "steps": [
          {
            "step": 1,
            "name": "Tool-based intent routing",
            "owner_agent": "Intent Router Agent",
            "input": state.user_prompt,
            "actions": ["Call route_generation_action", f"Call {next_tool_name}", "Ask for website brief"],
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
          "theme": {
            "colors": {
              "primary": "#0f766e",
              "secondary": "#2563eb",
              "accent": "#14212b",
              "background": "#ffffff",
              "text": "#14212b",
            },
            "style_direction": "Clean builder prompt starter state",
          },
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
      },
      "agent_to_agent_communication": {
        "message_contract": {
          "from_agent": "Intent Router Agent",
          "to_agent": "Prompt Analyst Agent",
          "sender": "Intent Router Agent",
          "receiver": "Prompt Analyst Agent",
          "task": (
            "Wait for explicit user approval of the execution brief."
            if state.intent == "needs_confirmation"
            else "Wait for a real website brief before starting generation."
          ),
          "input": {
            "received_message": state.user_prompt,
            "intent": state.intent,
          },
          "output": {
            "assistant_message": conversation_response["message"],
            "next_prompt_guidance": conversation_response["next_prompt_guidance"],
          },
          "next_action": "wait_for_user_confirmation" if state.intent == "needs_confirmation" else "respond_without_file_generation",
          "context": {
            "received_message": state.user_prompt,
            "intent": state.intent,
            "routing_result": state.routing_result,
          },
          "expected_output": {
            "next_user_message": "explicit confirmation" if state.intent == "needs_confirmation" else "website brief",
            "start_generation_when_ready": state.intent != "needs_confirmation",
          },
          "confidence": 0.98,
          "risks": ["User may send another short greeting instead of a website brief."],
        },
        "handoff_rules": [
          "Intent Router Agent owns action selection for every user turn.",
          "Greeting Handler Agent owns turns routed as greeting by the orchestrator.",
          "Requirement Confirmation Agent owns approval before high-impact execution.",
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
      },
      "proactive_thinking": {
        "assumptions": (
          ["The execution brief must be explicitly approved before work starts."]
          if state.intent == "needs_confirmation"
          else ["The routing tool decided this turn should not start website generation yet."]
        ),
        "missing_information": (
          conversation_response.get("confirmation", {}).get("open_questions", [])
          if state.intent == "needs_confirmation"
          else ["Website type", "Brand name", "Target audience", "Sections", "Visual style"]
        ),
        "predicted_risks": (
          ["Starting high-impact work without confirmation could produce the wrong result."]
          if state.intent == "needs_confirmation"
          else ["Starting generation without enough context would create irrelevant output."]
        ),
        "self_checks": ["Action selected by route_generation_action", "No backend error returned", "Next prompt guidance provided"],
        "recommended_next_actions": conversation_response["next_prompt_guidance"],
      },
    }
  )

def build_selected_tool_arguments(state: GenerationPipelineState, tool_name: str) -> dict[str, Any]:
  if tool_name == "handle_greeting":
    return {
      "message": state.user_prompt,
      "conversation_context": "website_builder_chat",
    }
  if tool_name == "confirm_execution_brief":
    return {
      "message": state.user_prompt,
      "execution_brief": (state.conversation_response_override or {}).get("confirmation", {}),
    }
  if tool_name == "summarize_current_project":
    return {
      "message": state.user_prompt,
      "conversation_context": "current_project_summary",
    }

  return {
    "message": state.user_prompt,
    "missing_fields": ["website type", "brand name", "sections", "style", "features"],
  }
