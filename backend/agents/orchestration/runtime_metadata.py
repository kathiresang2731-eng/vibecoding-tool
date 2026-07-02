from __future__ import annotations

from typing import Any

from ..schema import ResponseContractError
from .constants import DEFAULT_AGENT_TEAM, DEFAULT_TOOL_REGISTRY
from .state import GenerationPipelineState
from .tool_registry import (
  merge_agents,
  merge_tool_registry_entries,
  merge_tool_sequence,
  merge_tools,
  real_backend_tool_registry_entries,
)

def require_pipeline_response(state: GenerationPipelineState) -> dict[str, Any]:
  if state.response is None:
    raise ResponseContractError("Generation pipeline has no normalized LLM response yet.")
  return state.response

def existing_agentic_runtime(response: dict[str, Any]) -> dict[str, Any] | None:
  runtime = response.get("multi_agent_system", {}).get("agentic_runtime") if isinstance(response, dict) else None
  if isinstance(runtime, dict) and runtime.get("tool_source_of_truth") and isinstance(runtime.get("steps"), list):
    return runtime
  return None

def apply_backend_routing_to_response(state: GenerationPipelineState) -> None:
  response = require_pipeline_response(state)
  multi_agent_system = response["multi_agent_system"]
  multi_agent_system["intent"] = state.intent
  runtime = existing_agentic_runtime(response)
  multi_agent_system["active_agent"] = (
    "Memory Agent"
    if runtime
    else "Simple Code Writer Agent"
    if state.intent == "simple_code"
    else "Prompt Analyst Agent"
  )
  multi_agent_system["routing_result"] = state.routing_result
  multi_agent_system.setdefault("conversation_response", {})

  tool_setup = response["gemini_tool_calling_setup"]
  if runtime:
    runtime_agents = runtime.get("agents") if isinstance(runtime.get("agents"), list) else []
    multi_agent_system["agents"] = merge_agents(runtime_agents, [])
    real_tool_sequence = ["route_generation_action"]
    for call in runtime.get("tool_calls", []):
      if isinstance(call, dict):
        name = str(call.get("name") or "").strip()
        if name:
          real_tool_sequence.append(name)
    route_tool = [tool for tool in DEFAULT_TOOL_REGISTRY if tool.get("name") == "route_generation_action"]
    tool_setup["tools"] = merge_tool_registry_entries(
      route_tool,
      real_backend_tool_registry_entries(),
    )
    tool_setup["tool_call_sequence"] = merge_tool_sequence([], real_tool_sequence)
    return

  multi_agent_system["agents"] = merge_agents(DEFAULT_AGENT_TEAM, multi_agent_system.get("agents") or [])
  tool_setup["tools"] = merge_tools(DEFAULT_TOOL_REGISTRY, tool_setup.get("tools") or [])
  default_sequence = (
    ["route_generation_action", "generate_simple_code_file", "validate_generated_website"]
    if state.intent == "simple_code"
    else [
      "route_generation_action",
      "analyze_prompt",
      "generate_website_files",
      "validate_generated_website",
    ]
  )
  tool_setup["tool_call_sequence"] = merge_tool_sequence(default_sequence, tool_setup.get("tool_call_sequence") or [])

def format_stage_name(stage_name: str) -> str:
  return stage_name.replace("_", " ")

def summarize_stage_output(output: dict[str, Any]) -> str:
  if not isinstance(output, dict) or not output:
    return "No structured output."

  if "goal" in output:
    return str(output["goal"])
  if "tool_policy" in output:
    tools = output.get("tools") or []
    return f"Prepared {len(tools)} Gemini/local tools."
  if "summary" in output:
    return str(output["summary"])
  if "generated_website" in output:
    generated = output.get("generated_website") or {}
    return f"Generated website: {generated.get('title', 'Untitled')}"
  if "message_contract" in output:
    return "Prepared agent communication contract."
  if "recommended_next_actions" in output:
    actions = output.get("recommended_next_actions") or []
    return f"Prepared {len(actions)} next actions."

  return "Completed stage."
