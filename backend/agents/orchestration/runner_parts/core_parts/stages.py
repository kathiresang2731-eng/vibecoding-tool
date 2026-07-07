from __future__ import annotations

from typing import Any

from backend.agents.orchestration.runner_parts.flow import build_agent_to_agent_communication
from backend.agents.orchestration.runner_parts.flow import build_gemini_tool_calling_setup
from backend.agents.orchestration.runner_parts.flow import build_google_adk_usage
from backend.agents.orchestration.runner_parts.flow import build_multi_agent_system
from backend.agents.orchestration.runner_parts.flow import build_proactive_thinking
from backend.agents.orchestration.runner_parts.flow import execute_orchestration_flow
from backend.agents.orchestration.state import GenerationPipelineState


def multi_agent_system(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  return build_multi_agent_system(orchestrator, state)


def gemini_tool_calling_setup(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  return build_gemini_tool_calling_setup(orchestrator, state)


def google_adk_usage(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  return build_google_adk_usage(orchestrator, state)


def orchestration_flow(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  return execute_orchestration_flow(orchestrator, state)


def agent_to_agent_communication(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  return build_agent_to_agent_communication(orchestrator, state)


def proactive_thinking(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  return build_proactive_thinking(orchestrator, state)
