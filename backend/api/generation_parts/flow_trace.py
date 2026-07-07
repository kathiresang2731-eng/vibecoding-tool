from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.conversation_flow_logger import get_conversation_flow_logger
from backend.debug_trace import snapshot_backend_flow_capture


_REPO_ROOT = Path.cwd()
_GREETING_SEMANTIC_FUNCTIONS = {
  "generate_conversation_response",
  "ConversationTool.handle_greeting",
  "build_conversation_generation_response",
  "build_fast_greeting_generation",
}


def _normalize_path(value: str) -> str:
  raw = str(value or "").strip()
  if not raw:
    return ""
  try:
    path = Path(raw)
    if path.is_absolute():
      return path.relative_to(_REPO_ROOT).as_posix()
  except Exception:
    return raw.replace("\\", "/")
  return raw.replace("\\", "/")


def _build_semantic_and_infra_views(
  *,
  files: list[str],
  functions_by_file: dict[str, list[str]],
  process: list[str],
  intent: str,
  adaptive_route_name: str,
) -> dict[str, Any]:
  if intent != "greeting" and adaptive_route_name != "tiny_chat":
    return {
      "semantic_files": [],
      "semantic_functions_by_file": {},
      "semantic_process": [],
      "infra_files": [],
      "infra_functions_by_file": {},
      "infra_process": [],
    }

  semantic_functions_by_file: dict[str, list[str]] = {}
  infra_functions_by_file: dict[str, list[str]] = {}
  semantic_files: list[str] = []
  infra_files: list[str] = []
  semantic_process: list[str] = []
  infra_process: list[str] = []

  for path in files:
    labels = list(functions_by_file.get(path) or [])
    semantic_labels = [label for label in labels if label in _GREETING_SEMANTIC_FUNCTIONS]
    infra_labels = [label for label in labels if label not in _GREETING_SEMANTIC_FUNCTIONS]
    if semantic_labels:
      semantic_files.append(path)
      semantic_functions_by_file[path] = semantic_labels
    if infra_labels:
      infra_files.append(path)
      infra_functions_by_file[path] = infra_labels

  for item in process:
    if any(marker in item for marker in ("handle_greeting", "generate_conversation_response", "build_conversation_generation_response")):
      semantic_process.append(item)
    else:
      infra_process.append(item)

  return {
    "semantic_files": semantic_files,
    "semantic_functions_by_file": semantic_functions_by_file,
    "semantic_process": semantic_process,
    "infra_files": infra_files,
    "infra_functions_by_file": infra_functions_by_file,
    "infra_process": infra_process,
  }


def _normalize_runtime_capture(
  runtime_capture: dict[str, Any],
  *,
  event_type: str,
  intent: str,
  adaptive_route_name: str,
) -> dict[str, Any]:
  files = [_normalize_path(item) for item in (runtime_capture.get("files") or []) if _normalize_path(item)]
  functions_by_file = {
    _normalize_path(path): [
      str(label).strip()
      for label in labels
      if str(label).strip()
    ]
    for path, labels in (runtime_capture.get("functions_by_file") or {}).items()
    if _normalize_path(path)
  }
  process = [str(item).strip() for item in (runtime_capture.get("process") or []) if str(item).strip()]

  if intent == "greeting" or adaptive_route_name == "tiny_chat":
    for path, labels in list(functions_by_file.items()):
      filtered = [label for label in labels if label not in {"generate_website", "record_project_chat_message"}]
      if filtered:
        functions_by_file[path] = filtered
      else:
        functions_by_file.pop(path, None)
    process = [
      item for item in process
      if item not in {"enter.generate_website", "exit.generate_website", "enter.record_project_chat_message", "exit.record_project_chat_message"}
    ]

  filtered_files: list[str] = []
  for path in files:
    if intent == "greeting" or adaptive_route_name == "tiny_chat":
      labels = functions_by_file.get(path) or []
      if not labels and path.endswith("generation.py"):
        continue
    if path not in filtered_files:
      filtered_files.append(path)

  if event_type.endswith("preflight") and adaptive_route_name == "tiny_chat":
    has_conversation_signal = any(
      label in _GREETING_SEMANTIC_FUNCTIONS
      for labels in functions_by_file.values()
      for label in labels
    )
    if not has_conversation_signal:
      return {
        "events": runtime_capture.get("events") or [],
        "files": [],
        "functions_by_file": {},
        "process": [],
      }

  split_views = _build_semantic_and_infra_views(
    files=filtered_files,
    functions_by_file=functions_by_file,
    process=process,
    intent=intent,
    adaptive_route_name=adaptive_route_name,
  )

  return {
    "events": runtime_capture.get("events") or [],
    "files": filtered_files,
    "functions_by_file": functions_by_file,
    "process": process,
    **split_views,
  }


def _backend_flow_functions_for_event(
  *,
  event_type: str,
  routing_result: dict[str, Any] | None = None,
  adaptive_route: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
  route = routing_result if isinstance(routing_result, dict) else {}
  adaptive = adaptive_route if isinstance(adaptive_route, dict) else {}
  intent = str(route.get("intent") or "").strip().lower()
  adaptive_route_name = str(adaptive.get("route") or "").strip().lower()

  if adaptive_route_name == "tiny_chat" and event_type.endswith("preflight"):
    return {
      "backend/agents/request_complexity.py": ["classify_adaptive_request_route"],
      "backend/agents/memory/topic_clustering.py": ["resolve_chat_topic"],
      "backend/api/generation_parts/preflight.py": ["prepare_generation_pipeline_inputs"],
    }

  mapping: dict[str, list[str]] = {
    "backend/api/generation.py": [
      "_run_generation_pipeline_unlocked",
      "log_generation_flow_trace",
    ],
    "backend/api/generation_parts/preflight.py": [
      "prepare_generation_pipeline_inputs",
    ],
    "backend/api/generation_parts/postflight.py": [
      "finalize_generation_success",
    ],
    "backend/api/generation_parts/failure.py": [
      "report_generation_failure",
    ],
    "backend/api/generation_parts/flow_trace.py": [
      "log_generation_flow_trace",
      "_backend_flow_files_for_event",
      "_backend_flow_functions_for_event",
      "_backend_flow_process_for_event",
    ],
    "backend/agents/chat_history.py": [
      "apply_chat_context_budget",
      "model_chat_history_messages_for_prompt",
    ],
    "backend/agents/memory/topic_clustering.py": [
      "resolve_chat_topic",
    ],
    "backend/agents/orchestration/runner_parts/core.py": [
      "WorktualGenerationOrchestrator.run",
    ],
    "backend/agents/orchestration/runner_parts/execution.py": [
      "run_orchestration_flow",
    ],
    "backend/agents/orchestration/runner_parts/core_parts/routing.py": [
      "route_generation_action_tool",
      "build_target_resolution",
      "build_project_inspection_context",
    ],
  }

  if event_type.endswith("preflight"):
    mapping["backend/agents/request_complexity.py"] = ["classify_adaptive_request_route"]
    mapping["backend/agents/memory/context.py"] = ["build_agent_flow_memory_block"]

  if adaptive_route_name in {"conversation", "routing_pending", "tiny_chat"}:
    mapping["backend/agents/orchestration/conversation.py"] = ["generate_conversation_response"]
    mapping["backend/agents/orchestration/conversation_parts/assembly.py"] = ["build_conversation_generation_response"]

  if intent == "document_artifact":
    mapping["backend/agents/orchestration/runner_parts/document_artifact.py"] = [
      "run_document_artifact_flow",
    ]
    mapping["backend/agents/orchestration/artifact_response_parts/normalization.py"] = [
      "normalize_artifact_response",
    ]
    mapping["backend/agents/orchestration/artifact_response_parts/response.py"] = [
      "build_artifact_generation_response",
    ]
    mapping["backend/agents/prompting/builders.py"] = ["build_document_artifact_prompt"]
    mapping["backend/agents/prompting/instructions.py"] = ["DOCUMENT_ARTIFACT_SYSTEM_INSTRUCTION"]
  elif intent == "project_info":
    mapping["backend/agents/project_inspection.py"] = [
      "build_project_inspection_context",
      "build_target_resolution",
      "build_grounded_project_info_response",
    ]
    mapping["backend/agents/orchestration/conversation.py"] = ["generate_conversation_response"]
    mapping["backend/agents/orchestration/conversation_parts/response.py"] = [
      "generate_conversation_response",
      "clean_conversation_message",
    ]
  elif intent in {"website_update", "website_generation", "simple_code"}:
    mapping["backend/agents/agent_runtime/loop_core.py"] = ["run_agent_runtime_loop"]
    mapping["backend/agents/agent_runtime/state.py"] = ["build_requirement_trace"]
    mapping["backend/agents/agent_runtime/actions/analysis_parts/core.py"] = [
      "run_analysis_stage",
      "apply_targeted_update_shortcut",
    ]
    mapping["backend/agents/agent_runtime/actions/project_io_parts/commit.py"] = [
      "apply_generated_files",
      "write_linked_project_files",
    ]

  return mapping


def _backend_flow_process_for_event(
  *,
  event_type: str,
  routing_result: dict[str, Any] | None = None,
  adaptive_route: dict[str, Any] | None = None,
) -> list[str]:
  route = routing_result if isinstance(routing_result, dict) else {}
  adaptive = adaptive_route if isinstance(adaptive_route, dict) else {}
  intent = str(route.get("intent") or "").strip().lower()
  adaptive_route_name = str(adaptive.get("route") or "").strip().lower()

  if adaptive_route_name == "tiny_chat" and event_type.endswith("preflight"):
    return [
      "api.generation.request_received",
      "memory.topic.resolve_chat_topic",
      "adaptive_route.tiny_chat",
      "conversation.flow.preflight_logged",
    ]

  process = [
    "api.generation.request_received",
    "api.generation.preflight_started",
    "memory.topic.resolve_chat_topic",
    f"adaptive_route.{adaptive_route_name or 'unknown'}",
  ]
  if event_type.endswith("preflight"):
    process.append("conversation.flow.preflight_logged")
    return process

  process.append(f"orchestration.intent.{intent or 'unknown'}")
  if adaptive_route_name in {"routing_pending", "conversation", "tiny_chat"}:
    process.append("orchestration.routing.route_generation_action_tool")
  if intent == "greeting":
    process.extend([
      "conversation.handle_greeting",
      "conversation.response_built",
    ])
  elif intent == "project_info":
    process.extend([
      "project_inspection.build_context",
      "conversation.generate_project_info_response",
    ])
  elif intent == "document_artifact":
    process.extend([
      "artifact.document_prompt_built",
      "artifact.document_response_normalized",
    ])
  elif intent in {"website_update", "website_generation", "simple_code"}:
    process.extend([
      "agent_runtime.analysis_stage",
      "agent_runtime.commit_stage",
    ])
  process.append(f"conversation.flow.{event_type.rsplit('.', 1)[-1]}")
  return process


def _backend_flow_files_for_event(
  *,
  event_type: str,
  routing_result: dict[str, Any] | None = None,
  adaptive_route: dict[str, Any] | None = None,
) -> list[str]:
  route = routing_result if isinstance(routing_result, dict) else {}
  adaptive = adaptive_route if isinstance(adaptive_route, dict) else {}
  intent = str(route.get("intent") or "").strip().lower()
  adaptive_route_name = str(adaptive.get("route") or "").strip().lower()

  if adaptive_route_name == "tiny_chat" and event_type.endswith("preflight"):
    return [
      "backend/api/generation_parts/preflight.py",
      "backend/agents/request_complexity.py",
      "backend/agents/memory/topic_clustering.py",
    ]

  files = [
    "backend/api/generation.py",
    "backend/api/generation_parts/preflight.py",
    "backend/api/generation_parts/postflight.py",
    "backend/api/generation_parts/failure.py",
    "backend/api/generation_parts/flow_trace.py",
    "backend/agents/chat_history.py",
    "backend/agents/memory/topic_clustering.py",
    "backend/agents/orchestration/runner_parts/core.py",
    "backend/agents/orchestration/runner_parts/execution.py",
    "backend/agents/orchestration/runner_parts/core_parts/routing.py",
  ]

  if event_type.endswith("preflight"):
    files.extend(
      [
        "backend/agents/request_complexity.py",
        "backend/agents/memory/context.py",
      ]
    )

  if adaptive_route_name in {"conversation", "routing_pending"}:
    files.extend(
      [
        "backend/agents/orchestration/conversation.py",
        "backend/agents/orchestration/conversation_parts/assembly.py",
      ]
    )

  if intent == "document_artifact":
    files.extend(
      [
        "backend/agents/orchestration/runner_parts/document_artifact.py",
        "backend/agents/orchestration/artifact_response_parts/normalization.py",
        "backend/agents/orchestration/artifact_response_parts/response.py",
        "backend/agents/prompting/builders.py",
        "backend/agents/prompting/instructions.py",
      ]
    )
  elif intent == "project_info":
    files.extend(
      [
        "backend/agents/orchestration/conversation.py",
        "backend/agents/orchestration/conversation_parts/assembly.py",
      ]
    )
  elif intent in {"website_update", "website_generation", "simple_code"}:
    files.extend(
      [
        "backend/agents/agent_runtime/loop_core.py",
        "backend/agents/agent_runtime/state.py",
        "backend/agents/agent_runtime/actions/analysis_parts/core.py",
        "backend/agents/agent_runtime/actions/project_io_parts/commit.py",
      ]
    )

  deduped: list[str] = []
  seen: set[str] = set()
  for path in files:
    if path not in seen:
      seen.add(path)
      deduped.append(path)
  return deduped


def log_generation_flow_trace(
  event_type: str,
  *,
  prompt: str,
  project_id: str,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  topic_resolution: dict[str, Any] | None = None,
  routing_result: dict[str, Any] | None = None,
  adaptive_route: dict[str, Any] | None = None,
  selected_files: list[str] | None = None,
  generated_files: list[dict[str, Any]] | None = None,
  project_files: list[dict[str, Any]] | None = None,
  provider: str | None = None,
  model: str | None = None,
  status: str = "completed",
  extra: dict[str, Any] | None = None,
) -> None:
  route = routing_result if isinstance(routing_result, dict) else {}
  adaptive = adaptive_route if isinstance(adaptive_route, dict) else {}
  intent = str(route.get("intent") or "").strip().lower()
  adaptive_route_name = str(adaptive.get("route") or "").strip().lower()
  runtime_capture = _normalize_runtime_capture(
    snapshot_backend_flow_capture(),
    event_type=event_type,
    intent=intent,
    adaptive_route_name=adaptive_route_name,
  )
  backend_flow_files = _backend_flow_files_for_event(
    event_type=event_type,
    routing_result=routing_result,
    adaptive_route=adaptive_route,
  )
  backend_flow_functions = _backend_flow_functions_for_event(
    event_type=event_type,
    routing_result=routing_result,
    adaptive_route=adaptive_route,
  )
  backend_flow_process = _backend_flow_process_for_event(
    event_type=event_type,
    routing_result=routing_result,
    adaptive_route=adaptive_route,
  )
  get_conversation_flow_logger().log(
    event_type=event_type,
    prompt=prompt,
    project_id=project_id,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
    topic_resolution=topic_resolution,
    routing_result=routing_result,
    adaptive_route=adaptive_route,
    selected_files=selected_files,
    generated_files=generated_files,
    project_files=project_files,
    provider=provider,
    model=model,
    status=status,
    extra={
      **(extra or {}),
      "backend_flow_files": runtime_capture.get("files") or backend_flow_files,
      "backend_flow_functions": runtime_capture.get("functions_by_file") or backend_flow_functions,
      "backend_flow_process": runtime_capture.get("process") or backend_flow_process,
      "semantic_flow_files": runtime_capture.get("semantic_files") or [],
      "semantic_flow_functions": runtime_capture.get("semantic_functions_by_file") or {},
      "semantic_flow_process": runtime_capture.get("semantic_process") or [],
      "infra_flow_files": runtime_capture.get("infra_files") or [],
      "infra_flow_functions": runtime_capture.get("infra_functions_by_file") or {},
      "infra_flow_process": runtime_capture.get("infra_process") or [],
    },
  )
