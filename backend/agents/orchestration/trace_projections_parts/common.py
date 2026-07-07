from __future__ import annotations

import importlib.util
import inspect
from typing import Any

from backend.agents.agent_runtime.constants import SUPERVISOR_SYSTEM_INSTRUCTION

ADK_APP_NAME = "worktual_ai_website_builder"
ADK_RUNTIME_NAME = "worktual-google-adk-runtime"
LANGCHAIN_RUNTIME_NAME = "worktual-langchain-langgraph-runtime"
LANGCHAIN_STAGE_ORDER = [
  "router",
  "supervisor",
  "memory",
  "planner",
  "ux_review",
  "accessibility",
  "tool_executor",
  "validator",
  "preview",
  "visual_qa",
  "repair",
  "memory_writer",
]
LANGCHAIN_SYSTEM_PROMPT = (
  "You are Worktual AI Dev running inside a LangChain/LangGraph-compatible "
  "workflow. Gemini handles routing, greetings, detail collection, planning, "
  "reviews, supervision, tool routing, memory decisions, generation, and repair."
)
AGENT_STAGE_MAP = {
  "Intent Router Agent": "router",
  "Supervisor Agent": "supervisor",
  "Conversation Agent": "supervisor",
  "Prompt Analyst Agent": "supervisor",
  "Memory Agent": "memory_writer",
  "Planner Agent": "planner",
  "Planning Agent": "planner",
  "UX Review Agent": "ux_review",
  "Accessibility Agent": "accessibility",
  "Code Agent": "tool_executor",
  "Code Generation Agent": "tool_executor",
  "Validation Agent": "validator",
  "Preview Agent": "preview",
  "Visual QA Agent": "visual_qa",
  "Repair Agent": "repair",
}
AGENT_TO_ADK_NAME = {
  "Intent Router Agent": "intent_router_agent",
  "Supervisor Agent": "supervisor_agent",
  "Conversation Agent": "conversation_agent",
  "Memory Agent": "memory_agent",
  "Prompt Analyst Agent": "prompt_analyst_agent",
  "Planner Agent": "planner_agent",
  "Planning Agent": "planner_agent",
  "UX Review Agent": "ux_review_agent",
  "Accessibility Agent": "accessibility_agent",
  "Code Agent": "code_agent",
  "Code Generation Agent": "code_agent",
  "Validation Agent": "validation_agent",
  "Preview Agent": "preview_agent",
  "Visual QA Agent": "visual_qa_agent",
  "Repair Agent": "repair_agent",
}
ADK_AGENT_ORDER = [
  "orchestrator",
  "read_only_assistant_agent",
  "simple_code_writer_agent",
  "document_artifact_agent",
  "context_agent",
  "website_builder_agent",
  "quality_gate_service",
  "save_memory_service",
]
LOCAL_ADK_TOOL_SPECS = [
  {
    "name": "route_generation_action",
    "description": "Route a user turn to greeting handling, detail collection, or website generation.",
    "parameters": {
      "type": "object",
      "properties": {
        "message": {"type": "string"},
        "conversation_context": {"type": "string"},
      },
      "required": ["message"],
      "additionalProperties": False,
    },
    "adk_binding": {"type": "FunctionTool", "execution": "worktual_python_router"},
  },
  {
    "name": "load_memory",
    "description": "Load relevant project memory for the current user and project.",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string"},
        "project_id": {"type": "string"},
      },
      "required": ["query"],
      "additionalProperties": False,
    },
    "adk_binding": {"type": "BuiltInMemoryTool", "execution": "google_adk_memory_service"},
  },
]


class LangChainRuntimeError(RuntimeError):
  pass


class GoogleADKRuntimeError(RuntimeError):
  pass


def _text(value: Any, default: str = "") -> str:
  return str(value or default).strip() or default


def _list(value: Any) -> list[Any]:
  return list(value) if isinstance(value, list) else []


def _obj(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {}


def package_status(module_name: str) -> dict[str, Any]:
  spec = importlib.util.find_spec(module_name)
  if spec is None:
    return {"installed": False, "module": module_name, "reason": f"{module_name} is not installed."}
  return {"installed": True, "module": module_name, "origin": spec.origin}


def package_status_pair() -> dict[str, dict[str, Any]]:
  return {"langchain": package_status("langchain"), "langgraph": package_status("langgraph")}


def google_adk_package_status() -> dict[str, Any]:
  spec = importlib.util.find_spec("google.adk")
  if spec is None:
    return {"installed": False, "module": "google.adk", "reason": "google-adk is not installed."}
  return {"installed": True, "module": "google.adk", "origin": spec.origin}


def supervisor_instruction() -> str:
  text = SUPERVISOR_SYSTEM_INSTRUCTION
  if "Gemini" not in text or "Python" not in text:
    text = f"{text}\nGemini may reason about the next action, but Python remains the source of truth for backend tools."
  if "unsafe filesystem paths" not in text:
    text = f"{text}\nReject unsafe filesystem paths before any backend tool writes files."
  return text


def build_thread_config(thread_id: str) -> dict[str, dict[str, str]]:
  cleaned = thread_id.strip()
  if not cleaned:
    raise LangChainRuntimeError("thread_id is required for LangGraph persistence.")
  return {"configurable": {"thread_id": cleaned}}


def _create_adk_runner_metadata(*, model: str) -> dict[str, Any]:
  try:
    from google.adk.agents import LlmAgent
    from google.adk.memory import InMemoryMemoryService
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
  except ModuleNotFoundError:
    return {"status": "not_created", "reason": "google-adk is not installed."}

  agent = LlmAgent(model=model, name="supervisor_agent", instruction="Worktual supervisor agent.", tools=[])
  session_service = InMemorySessionService()
  memory_service = InMemoryMemoryService()
  runner_kwargs = {"agent": agent, "app_name": ADK_APP_NAME, "session_service": session_service}
  if "memory_service" in inspect.signature(Runner).parameters:
    runner_kwargs["memory_service"] = memory_service
  runner = Runner(**runner_kwargs)
  return {
    "status": "created",
    "agent_class": agent.__class__.__name__,
    "runner_class": runner.__class__.__name__,
    "session_service_class": session_service.__class__.__name__,
    "memory_service_class": memory_service.__class__.__name__,
  }
