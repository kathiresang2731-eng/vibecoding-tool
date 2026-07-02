from __future__ import annotations

import hashlib
import importlib.util
import inspect
from typing import Any

from ..runtime_config import agentic_parity_target, runtime_engine
from .provider_utils import configured_adk_model

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
  "intent_router_agent",
  "supervisor_agent",
  "conversation_agent",
  "memory_agent",
  "prompt_analyst_agent",
  "planner_agent",
  "ux_review_agent",
  "accessibility_agent",
  "code_agent",
  "validation_agent",
  "preview_agent",
  "visual_qa_agent",
  "repair_agent",
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


def build_langchain_trace_from_runtime(
  *,
  user_prompt: str,
  routing_result: dict[str, Any],
  runtime_trace: dict[str, Any],
  a2a_runtime: dict[str, Any],
  google_adk_runtime: dict[str, Any],
) -> dict[str, Any]:
  packages = _package_status_pair()
  graph_ready = packages["langchain"]["installed"] and packages["langgraph"]["installed"]
  executing = runtime_engine() == "langgraph" and agentic_parity_target() >= 90 and bool(runtime_trace.get("tool_source_of_truth"))
  if executing and graph_ready:
    execution_mode = "executing"
  elif graph_ready:
    execution_mode = "graph_ready"
  else:
    execution_mode = "dry_run"

  branch = _text(runtime_trace.get("branch"), "unknown")
  digest = hashlib.sha1(user_prompt.encode("utf-8")).hexdigest()[:12]
  thread_id = f"langgraph-{branch}-{digest}"
  final_output = _obj(runtime_trace.get("final_output"))
  memory_line = f"Latest branch: {branch}."
  if isinstance(final_output.get("file_count"), int):
    memory_line = f"{memory_line} File count: {final_output['file_count']}."
  messages = [
    {"role": "system", "content": LANGCHAIN_SYSTEM_PROMPT},
    {"role": "system", "content": f"Relevant persisted memory:\n[runtime/summary/latest_agentic_output] {memory_line}"},
    {"role": "user", "content": user_prompt.strip()},
  ]
  nodes = _build_langgraph_nodes(runtime_trace=runtime_trace, a2a_runtime=a2a_runtime)
  runtime = {
    "runtime": LANGCHAIN_RUNTIME_NAME,
    "status": "completed",
    "execution_mode": execution_mode,
    "source_of_truth": executing and graph_ready,
    "source_of_truth_runtime": runtime_trace.get("runtime"),
    "projection_source": "live_runtime_trace" if runtime_trace.get("tool_source_of_truth") else "legacy_response_trace",
    "packages": packages,
    "thread_config": {"configurable": {"thread_id": thread_id}},
    "stage_order": list(LANGCHAIN_STAGE_ORDER),
    "messages": messages,
    "state": {
      "routing_result": routing_result,
      "branch": branch,
      "a2a_protocol": a2a_runtime.get("protocol"),
      "google_adk_execution_mode": google_adk_runtime.get("execution_mode"),
      "final_output": final_output,
      "graph_topology": runtime_trace.get("graph_topology") or runtime_trace.get("runtime_graph_topology"),
    },
    "graph": {
      "entrypoint": "router",
      "terminal": "memory_writer",
      "nodes": nodes,
      "edges": [{"from": source, "to": target} for source, target in zip(LANGCHAIN_STAGE_ORDER, LANGCHAIN_STAGE_ORDER[1:])],
      "compiled": graph_ready,
    },
  }
  runtime["validation"] = _validate_langchain_trace(runtime)
  return runtime


def build_adk_trace_from_runtime(
  *,
  user_prompt: str,
  model: str,
  routing_result: dict[str, Any],
  runtime_trace: dict[str, Any],
  a2a_runtime: dict[str, Any],
) -> dict[str, Any]:
  plan = _build_adk_agent_plan(model)
  tools = _build_adk_tool_specs()
  package = _google_adk_package_status()
  prompt_digest = hashlib.sha1(user_prompt.encode("utf-8")).hexdigest()[:12]
  branch = _text(runtime_trace.get("branch"), "unknown")
  session = {
    "app_name": ADK_APP_NAME,
    "user_id": "worktual-local-user",
    "session_id": f"adk-{branch}-{prompt_digest}",
    "new_message": {"role": "user", "parts": [{"text": user_prompt}]},
    "state": {
      "routing_result": routing_result,
      "agentic_branch": branch,
      "a2a_protocol": a2a_runtime.get("protocol"),
      "a2a_message_count": len(_list(a2a_runtime.get("messages"))),
    },
  }
  events = _build_adk_events(runtime_trace=runtime_trace, a2a_runtime=a2a_runtime)
  runtime = {
    "runtime": ADK_RUNTIME_NAME,
    "status": "completed",
    "execution_mode": "dry_run" if not package["installed"] else "runner_ready",
    "source_of_truth": bool(runtime_trace.get("tool_source_of_truth")),
    "source_of_truth_runtime": runtime_trace.get("runtime"),
    "projection_source": "live_runtime_trace" if runtime_trace.get("tool_source_of_truth") else "legacy_response_trace",
    "package": package,
    "app_name": ADK_APP_NAME,
    "model": plan["model"],
    "root_agent": plan["root_agent"],
    "agent_plan": plan,
    "tool_specs": tools,
    "session": session,
    "events": events,
    "runner": {"status": "not_created", "reason": package.get("reason", "Dry-run mode requested.")},
  }
  if package["installed"]:
    runtime["runner"] = _create_adk_runner_metadata(model=plan["model"])
  runtime["validation"] = _validate_adk_trace(runtime)
  return runtime


def build_langchain_trace_summary(runtime: dict[str, Any]) -> dict[str, Any]:
  return {
    "runtime": runtime["runtime"],
    "status": runtime["status"],
    "execution_mode": runtime["execution_mode"],
    "source_of_truth": runtime.get("source_of_truth") is True,
    "source_of_truth_runtime": runtime.get("source_of_truth_runtime"),
    "thread_id": runtime["thread_config"]["configurable"]["thread_id"],
    "message_count": len(runtime["messages"]),
    "node_count": len(runtime["graph"]["nodes"]),
    "validation_status": runtime["validation"]["status"],
  }


def build_adk_trace_summary(runtime: dict[str, Any]) -> dict[str, Any]:
  return {
    "runtime": runtime["runtime"],
    "status": runtime["status"],
    "execution_mode": runtime["execution_mode"],
    "source_of_truth": runtime.get("source_of_truth") is True,
    "source_of_truth_runtime": runtime.get("source_of_truth_runtime"),
    "package_installed": runtime["package"]["installed"],
    "app_name": runtime["app_name"],
    "root_agent": runtime["root_agent"],
    "event_count": len(runtime["events"]),
    "validation_status": runtime["validation"]["status"],
  }


def _build_langgraph_nodes(*, runtime_trace: dict[str, Any], a2a_runtime: dict[str, Any]) -> list[dict[str, Any]]:
  steps = _list(runtime_trace.get("steps"))
  messages = _list(a2a_runtime.get("messages"))
  incoming_by_agent = {message.get("to_agent"): message for message in messages if isinstance(message, dict)}
  outgoing_by_agent = {message.get("from_agent"): message for message in messages if isinstance(message, dict)}
  nodes: list[dict[str, Any]] = []
  for step in steps:
    if not isinstance(step, dict):
      continue
    agent = _text(step.get("agent"), "Unknown Agent")
    stage = AGENT_STAGE_MAP.get(agent, "supervisor")
    action = _text(step.get("action"), "agent_step")
    if agent == "Memory Agent" and any(term in action for term in ("read", "load")):
      stage = "memory"
    nodes.append(
      {
        "node": stage,
        "agent": agent,
        "action": action,
        "status": _text(step.get("status"), "completed"),
        "input_keys": sorted(_obj(step.get("input")).keys()),
        "output_keys": sorted(_obj(step.get("output")).keys()),
        "tool_calls": _list(step.get("tool_calls")),
        "a2a_received_message_id": _obj(incoming_by_agent.get(agent)).get("message_id"),
        "a2a_sent_message_id": _obj(outgoing_by_agent.get(agent)).get("message_id"),
      }
    )
  return nodes


def _build_adk_events(*, runtime_trace: dict[str, Any], a2a_runtime: dict[str, Any]) -> list[dict[str, Any]]:
  steps = _list(runtime_trace.get("steps"))
  messages = _list(a2a_runtime.get("messages"))
  incoming_by_agent = {message.get("to_agent"): message for message in messages if isinstance(message, dict)}
  outgoing_by_agent = {message.get("from_agent"): message for message in messages if isinstance(message, dict)}
  events: list[dict[str, Any]] = []
  for step in steps:
    if not isinstance(step, dict):
      continue
    agent_name = _text(step.get("agent"), "Unknown Agent")
    adk_agent_name = AGENT_TO_ADK_NAME.get(agent_name, agent_name.lower().replace(" ", "_"))
    events.append(
      {
        "event_id": f"adk-event-{len(events) + 1}-{adk_agent_name}",
        "author": adk_agent_name,
        "source_agent": agent_name,
        "status": _text(step.get("status"), "completed"),
        "action": _text(step.get("action"), "agent_step"),
        "tool_calls": _list(step.get("tool_calls")),
        "a2a_received_message_id": _obj(incoming_by_agent.get(agent_name)).get("message_id"),
        "a2a_sent_message_id": _obj(outgoing_by_agent.get(agent_name)).get("message_id"),
      }
    )
  return events


def _build_adk_agent_plan(model: str) -> dict[str, Any]:
  cleaned_model = model.strip() or "gemini-3.5-flash"
  return {
    "app_name": ADK_APP_NAME,
    "model": cleaned_model,
    "root_agent": "supervisor_agent",
    "execution_strategy": "Gemini controls specialist agents and can request backend FunctionTool calls; Python remains the source of truth for tool execution and commits.",
    "agents": [
      {
        "name": "intent_router_agent",
        "adk_type": "LlmAgent",
        "instruction": "Route the user turn to greeting, detail collection, or website generation.",
        "tools": ["route_generation_action"],
      },
      {
        "name": "supervisor_agent",
        "adk_type": "Agent",
        "instruction": "Use Gemini to coordinate website planning, validation, repair routing, and memory updates.",
        "tools": [],
      },
      {
        "name": "conversation_agent",
        "adk_type": "LlmAgent",
        "instruction": "Reply to greeting or incomplete prompts without creating website files.",
        "tools": [],
      },
      {
        "name": "memory_agent",
        "adk_type": "LlmAgent",
        "instruction": "Load project memory before planning and persist concise project memory after completion.",
        "tools": ["load_memory", "LOAD_PROJECT_MEMORY", "PERSIST_PROJECT_MEMORY"],
      },
      {
        "name": "prompt_analyst_agent",
        "adk_type": "LlmAgent",
        "instruction": "Extract audience, brand, sections, style, business goal, and implementation constraints.",
        "tools": [],
      },
      {
        "name": "planner_agent",
        "adk_type": "LlmAgent",
        "instruction": "Plan the website structure and component responsibilities before code is written.",
        "tools": [],
      },
      {
        "name": "ux_review_agent",
        "adk_type": "LlmAgent",
        "instruction": "Review planned website UX for user flow, conversion clarity, responsive behavior, and content gaps.",
        "tools": [],
      },
      {
        "name": "accessibility_agent",
        "adk_type": "LlmAgent",
        "instruction": "Review planned UI for contrast, semantics, keyboard flow, and mobile text fit.",
        "tools": [],
      },
      {
        "name": "code_agent",
        "adk_type": "LlmAgent",
        "instruction": "Call the selected Gemini generation model only for React, CSS, config, and public asset artifact generation or update.",
        "tools": ["READ_PROJECT_FILES", "WRITE_PROJECT_FILES"],
      },
      {
        "name": "validation_agent",
        "adk_type": "LlmAgent",
        "instruction": "Validate generated artifacts, paths, sections, theme, and required files before preview builds.",
        "tools": ["VALIDATE_PROJECT_ARTIFACT"],
      },
      {
        "name": "preview_agent",
        "adk_type": "LlmAgent",
        "instruction": "Build the generated project preview and return build status, logs, and preview URL.",
        "tools": ["BUILD_STAGED_PROJECT_PREVIEW", "BUILD_PROJECT_PREVIEW"],
      },
      {
        "name": "visual_qa_agent",
        "adk_type": "LlmAgent",
        "instruction": "Run backend preview integrity QA before generated files are committed.",
        "tools": ["RUN_PREVIEW_VISUAL_QA"],
      },
      {
        "name": "repair_agent",
        "adk_type": "LlmAgent",
        "instruction": "Call the selected Gemini generation model for code repair from validation or preview errors, then restore previous files if repair fails.",
        "tools": ["WRITE_PROJECT_FILES", "BUILD_PROJECT_PREVIEW"],
      },
    ],
  }


def build_adk_agent_plan(model: str) -> dict[str, Any]:
  return _build_adk_agent_plan(model)


def supervisor_instruction() -> str:
  return (
    "You are the Worktual AI Dev supervisor agent. Use backend tools to read, write, "
    "validate, build, and repair generated website projects. Preserve project memory, "
    "avoid unsafe filesystem paths, use Gemini for control/artifact decisions, and keep "
    "Python as the source of truth for backend tool execution."
  )


def _build_adk_tool_specs() -> list[dict[str, Any]]:
  tools = [dict(tool) for tool in LOCAL_ADK_TOOL_SPECS]
  try:
    from ...agent_tools import website_tool_schemas
  except ImportError:
    from agent_tools import website_tool_schemas
  for schema in website_tool_schemas():
    tools.append(
      {
        "name": schema["name"],
        "description": schema.get("description", ""),
        "parameters": schema.get("parameters", {}),
        "adk_binding": {"type": "FunctionTool", "execution": "backend_tool_registry"},
      }
    )
  return tools


def build_adk_tool_specs() -> list[dict[str, Any]]:
  return _build_adk_tool_specs()


def _package_status_pair() -> dict[str, dict[str, Any]]:
  return {"langchain": _package_status("langchain"), "langgraph": _package_status("langgraph")}


def _package_status(module_name: str) -> dict[str, Any]:
  spec = importlib.util.find_spec(module_name)
  if spec is None:
    return {"installed": False, "module": module_name, "reason": f"{module_name} is not installed."}
  return {"installed": True, "module": module_name, "origin": spec.origin}


def _google_adk_package_status() -> dict[str, Any]:
  spec = importlib.util.find_spec("google.adk")
  if spec is None:
    return {"installed": False, "module": "google.adk", "reason": "google-adk is not installed."}
  return {"installed": True, "module": "google.adk", "origin": spec.origin}


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


def _validate_langchain_trace(runtime: dict[str, Any]) -> dict[str, Any]:
  graph = _obj(runtime.get("graph"))
  nodes = _list(graph.get("nodes"))
  return {
    "status": "valid",
    "message_count": len(_list(runtime.get("messages"))),
    "node_count": len(nodes),
    "edge_count": len(_list(graph.get("edges"))),
  }


def _validate_adk_trace(runtime: dict[str, Any]) -> dict[str, Any]:
  plan = _obj(runtime.get("agent_plan"))
  agent_names = [agent.get("name") for agent in _list(plan.get("agents")) if isinstance(agent, dict)]
  return {
    "status": "valid",
    "agent_count": len(agent_names),
    "tool_count": len(_list(runtime.get("tool_specs"))),
    "event_count": len(_list(runtime.get("events"))),
  }


def build_langchain_messages(
  *,
  system_prompt: str,
  user_prompt: str,
  memory_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
  messages = [{"role": "system", "content": system_prompt.strip()}]
  memory_context = format_memory_context(memory_items or [])
  if memory_context:
    messages.append({"role": "system", "content": f"Relevant persisted memory:\n{memory_context}"})
  messages.append({"role": "user", "content": user_prompt.strip()})
  return messages


def format_memory_context(memory_items: list[dict[str, Any]]) -> str:
  lines: list[str] = []
  for item in memory_items:
    if not isinstance(item, dict):
      continue
    namespace = _text(item.get("namespace"), "memory")
    key = _text(item.get("key"), "item")
    kind = _text(item.get("kind"), "summary")
    content = _text(item.get("content"), "")
    if not content:
      continue
    lines.append(f"[{namespace}/{kind}/{key}] {content}")
  return "\n".join(lines)


def build_thread_config(thread_id: str) -> dict[str, dict[str, str]]:
  cleaned = thread_id.strip()
  if not cleaned:
    raise LangChainRuntimeError("thread_id is required for LangGraph persistence.")
  return {"configurable": {"thread_id": cleaned}}


def build_langgraph_node_projection(*, agentic_flow: dict[str, Any], a2a_runtime: dict[str, Any]) -> list[dict[str, Any]]:
  return _build_langgraph_nodes(runtime_trace=agentic_flow, a2a_runtime=a2a_runtime)


def langchain_package_status() -> dict[str, dict[str, Any]]:
  return _package_status_pair()


def google_adk_package_status() -> dict[str, Any]:
  return _google_adk_package_status()


def execute_google_adk_runtime(
  *,
  user_prompt: str,
  model: str,
  routing_result: dict[str, Any],
  agentic_flow: dict[str, Any],
  a2a_runtime: dict[str, Any],
) -> dict[str, Any]:
  runtime = build_adk_trace_from_runtime(
    user_prompt=user_prompt,
    model=model,
    routing_result=routing_result,
    runtime_trace=agentic_flow,
    a2a_runtime=a2a_runtime,
  )
  runtime["source_of_truth"] = False
  runtime["source_of_truth_runtime"] = "worktual-real-agent-runtime-loop"
  runtime["projection_source"] = "real_agent_runtime_steps"
  runtime["execution_note"] = (
    "Google ADK metadata mirrors the real Python agent runtime. Gemini is the control and artifact model, "
    "while Python executes backend tools and validates commits."
  )
  return runtime


def execute_langchain_runtime(
  *,
  user_prompt: str,
  routing_result: dict[str, Any],
  agentic_flow: dict[str, Any],
  a2a_runtime: dict[str, Any],
  google_adk_runtime: dict[str, Any],
) -> dict[str, Any]:
  runtime = build_langchain_trace_from_runtime(
    user_prompt=user_prompt,
    routing_result=routing_result,
    runtime_trace=agentic_flow,
    a2a_runtime=a2a_runtime,
    google_adk_runtime=google_adk_runtime,
  )
  runtime["source_of_truth"] = False
  runtime["source_of_truth_runtime"] = "worktual-real-agent-runtime-loop"
  runtime["projection_source"] = "real_agent_runtime_steps"
  return runtime


build_adk_runtime_summary = build_adk_trace_summary
build_langchain_runtime_summary = build_langchain_trace_summary
