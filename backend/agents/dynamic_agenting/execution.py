from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from threading import Thread
from typing import Any, Callable
try:
  from ...runtime_control import submit_with_runtime_context
except ImportError:
  from runtime_control import submit_with_runtime_context

try:
  from ...audit_logging import current_telemetry_context, log_dynamic_agent_event, run_with_telemetry_context
  from ...agent_tools import website_tool_schemas
except ImportError:
  from audit_logging import current_telemetry_context, log_dynamic_agent_event, run_with_telemetry_context
  from agent_tools import website_tool_schemas

from ..artifacts import ArtifactValidationError, normalize_artifact_path, normalize_generated_file_code
from .config import (
  dynamic_agent_max_patch_bytes,
  dynamic_agent_max_patch_files,
  dynamic_agent_tool_loop_enabled,
)
from .constants import (
  ALLOWED_DYNAMIC_TOOLS,
  SPECIALIST_ITEM_MAX_CHARS,
  SPECIALIST_SUMMARY_MAX_CHARS,
)
from .models import AgentDefinition
from .prompts import build_specialist_task_prompt, compact_json_for_prompt
from .registry import AgentRegistry
from .utils import (
  list_value,
  object_value,
  parse_json_object,
  sha256_text,
  string_list,
  text_value,
)


def _clone_provider_for_thread(provider: Any) -> Any:
  try:
    from ..providers.thread_clone import clone_llm_provider
  except ImportError:
    from agents.providers.thread_clone import clone_llm_provider
  return clone_llm_provider(provider)


def execute_dynamic_specialists(
  provider: Any,
  workflow_plan: dict[str, Any],
  *,
  prompt: str,
  brief: dict[str, Any],
  plan: dict[str, Any],
  registry: AgentRegistry | None = None,
  execute_tool: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
  registry = registry or AgentRegistry()
  assignments = {
    text_value(item.get("task_id")): item
    for item in list_value(workflow_plan.get("assignments"))
    if isinstance(item, dict)
  }
  results: dict[str, Any] = {}
  completed: list[str] = []
  tasks_by_id = {
    text_value(task.get("id")): task
    for task in list_value(workflow_plan.get("tasks"))
    if isinstance(task, dict) and task.get("runtime_action") == "RUN_DYNAMIC_SPECIALISTS"
  }
  parallel_groups = list_value(workflow_plan.get("parallel_groups")) or [list(tasks_by_id)]
  executed_groups: list[list[str]] = []
  telemetry = current_telemetry_context()
  for raw_group in parallel_groups:
    group_task_ids = [
      text_value(task_id)
      for task_id in list_value(raw_group)
      if text_value(task_id) in tasks_by_id and text_value(task_id) not in completed
    ]
    if not group_task_ids:
      continue
    group_results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(group_task_ids))) as executor:
      futures = {
        task_id: submit_with_runtime_context(
          executor,
          run_with_telemetry_context,
          telemetry,
          execute_specialist_task,
          _clone_provider_for_thread(provider),
          tasks_by_id[task_id],
          assignments.get(task_id) or {},
          prompt=prompt,
          brief=brief,
          plan=plan,
          registry=registry,
          execute_tool=execute_tool,
        )
        for task_id in group_task_ids
      }
      for task_id in group_task_ids:
        group_results[task_id] = futures[task_id].result()
    results.update(group_results)
    completed.extend(group_task_ids)
    executed_groups.append(group_task_ids)
  candidate_changes = [
    change
    for result in results.values()
    if isinstance(result, dict)
    for change in list_value(result.get("accepted_candidate_changes"))
    if isinstance(change, dict)
  ]
  rejected_changes = [
    change
    for result in results.values()
    if isinstance(result, dict)
    for change in list_value(result.get("rejected_candidate_changes"))
    if isinstance(change, dict)
  ]
  max_patch_files = dynamic_agent_max_patch_files()
  if len(candidate_changes) > max_patch_files:
    overflow = candidate_changes[max_patch_files:]
    candidate_changes = candidate_changes[:max_patch_files]
    rejected_changes.extend(
      {
        "path": item.get("path"),
        "agent_id": item.get("agent_id"),
        "task_id": item.get("task_id"),
        "reason": f"Workflow candidate file limit of {max_patch_files} exceeded.",
      }
      for item in overflow
    )
  executions = [
    {
      "task_id": task_id,
      "agent_id": result.get("agent_id"),
      "agent": result.get("agent"),
      "status": result.get("status"),
      "source": result.get("source"),
      "duration_ms": result.get("duration_ms"),
      "tool_calls": compact_dynamic_tool_calls(result.get("tool_calls")),
      "safety_violations": list_value(result.get("safety_violations")),
      "execution_failed": bool(result.get("execution_failed")),
      "fallback_reason": result.get("fallback_reason"),
    }
    for task_id, result in list(results.items())
    if isinstance(result, dict)
  ]
  return {
    "status": "completed",
    "results": results,
    "completed_task_ids": completed,
    "parallel_groups_executed": executed_groups,
    "candidate_changes": candidate_changes,
    "candidate_change_summary": candidate_change_summary(candidate_changes, rejected_changes),
    "dynamic_agent_executions": executions,
  }


def execute_specialist_task(
  provider: Any,
  task_item: dict[str, Any],
  assignment: dict[str, Any],
  *,
  prompt: str,
  brief: dict[str, Any],
  plan: dict[str, Any],
  registry: AgentRegistry,
  execute_tool: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
  fallback = deterministic_specialist_result(task_item, assignment)
  agent = registry.agents.get(text_value(assignment.get("agent_id")))
  if agent is None:
    return unavailable_specialist_result(
      fallback,
      task_item,
      assignment,
      reason="Assigned dynamic agent was not found in the registry.",
    )
  if provider is None:
    return unavailable_specialist_result(
      fallback,
      task_item,
      assignment,
      reason="Dynamic agent provider is unavailable.",
    )
  started_at = time.monotonic()
  specialist_prompt = build_specialist_task_prompt(
    task_item=task_item,
    user_prompt=prompt,
    brief=brief,
    plan=plan,
  )
  response: Any = None
  tool_calls: list[dict[str, Any]] = []
  safety_violations: list[str] = []
  try:
    if (
      dynamic_agent_tool_loop_enabled()
      and execute_tool is not None
      and hasattr(provider, "run_tool_loop")
      and agent.allowed_tools
    ):
      tool_schemas = allowed_dynamic_tool_schemas(agent.allowed_tools)
      guarded_executor = build_guarded_dynamic_tool_executor(
        agent,
        execute_tool=execute_tool,
        safety_violations=safety_violations,
      )
      tool_result = run_with_timeout(
        lambda: provider.run_tool_loop(
          messages=[
            {
              "role": "user",
              "content": f"{agent.system_prompt}\n\n{specialist_prompt}",
            }
          ],
          tools=tool_schemas,
          execute_tool=guarded_executor,
          max_steps=agent.tool_call_budget,
          mode=os.getenv("GEMINI_TOOL_CALLING_MODE", "VALIDATED"),
          trace_label=f"dynamic_agent_{agent.id}",
        ),
        timeout_seconds=agent.timeout_seconds,
        label=agent.id,
      )
      tool_calls = list_value(object_value(tool_result).get("tool_calls"))
      response = parse_json_object(text_value(object_value(tool_result).get("output_text")))
    elif hasattr(provider, "generate_json"):
      response = run_with_timeout(
        lambda: provider.generate_json(
          specialist_prompt,
          system_instruction=agent.system_prompt,
          trace_label=f"dynamic_agent_{agent.id}",
        ),
        timeout_seconds=agent.timeout_seconds,
        label=agent.id,
      )
    else:
      return unavailable_specialist_result(
        fallback,
        task_item,
        assignment,
        reason="Dynamic agent provider does not support generate_json or run_tool_loop.",
      )
  except Exception as exc:
    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    record_agent_execution_metrics(agent, duration_ms=duration_ms, accepted_changes=0, rejected_changes=0)
    log_dynamic_agent_event(
      "agent.execution_failed",
      status="failed",
      payload={"agent_id": agent.id, "task_id": task_item.get("id"), "error": str(exc)},
      duration_ms=duration_ms,
    )
    optional = bool(task_item.get("optional"))
    return {
      **fallback,
      "status": "skipped" if optional else "completed",
      "source": "optional_dynamic_agent_skipped" if optional else "guarded_required_task_fallback",
      "agent_id": agent.id,
      "duration_ms": duration_ms,
      "tool_calls": tool_calls,
      "safety_violations": safety_violations,
      "execution_failed": True,
      "fallback_reason": str(exc)[:400],
    }
  normalized = normalize_specialist_result(response, fallback=fallback)
  accepted, rejected = validate_candidate_changes(
    object_value(response).get("candidate_changes"),
    agent=agent,
    task_id=text_value(task_item.get("id")),
  )
  duration_ms = round((time.monotonic() - started_at) * 1000, 2)
  record_agent_execution_metrics(
    agent,
    duration_ms=duration_ms,
    accepted_changes=len(accepted),
    rejected_changes=len(rejected),
  )
  normalized.update(
    {
      "agent_id": agent.id,
      "duration_ms": duration_ms,
      "tool_calls": tool_calls,
      "safety_violations": safety_violations,
      "accepted_candidate_changes": accepted,
      "rejected_candidate_changes": rejected,
      "execution_failed": False,
    }
  )
  log_dynamic_agent_event(
    "agent.executed",
    status="completed" if not safety_violations else "degraded",
    payload={
      "agent_id": agent.id,
      "task_id": task_item.get("id"),
      "tool_calls": tool_calls,
      "candidate_changes": accepted,
      "rejected_candidate_changes": rejected,
      "safety_violations": safety_violations,
    },
    duration_ms=duration_ms,
  )
  return normalized


def deterministic_specialist_result(task_item: dict[str, Any], assignment: dict[str, Any]) -> dict[str, Any]:
  capability = text_value(task_item.get("required_capability"))
  return {
    "status": "completed",
    "summary": f"Prepared guarded {capability} recommendations.",
    "recommendations": [f"Include complete {capability.replace('_', ' ')} behavior in the generated website."],
    "requirements": [f"Represent {capability.replace('_', ' ')} with realistic content and interactions."],
    "risks": ["Validate the capability in the staged preview before commit."],
    "agent": text_value(assignment.get("agent_name")),
    "agent_id": text_value(assignment.get("agent_id")),
    "source": "deterministic_specialist_fallback",
    "tool_calls": [],
    "safety_violations": [],
    "accepted_candidate_changes": [],
    "rejected_candidate_changes": [],
  }


def unavailable_specialist_result(
  fallback: dict[str, Any],
  task_item: dict[str, Any],
  assignment: dict[str, Any],
  *,
  reason: str,
) -> dict[str, Any]:
  optional = bool(task_item.get("optional"))
  return {
    **fallback,
    "status": "skipped" if optional else "failed",
    "source": "optional_dynamic_agent_unavailable" if optional else "required_dynamic_agent_unavailable",
    "agent": text_value(assignment.get("agent_name")),
    "agent_id": text_value(assignment.get("agent_id")),
    "execution_failed": not optional,
    "fallback_reason": reason,
  }


def normalize_specialist_result(response: Any, *, fallback: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(response, dict):
    return fallback
  normalized = dict(fallback)
  normalized["status"] = "completed"
  normalized["source"] = "dynamic_agent"
  for key in ("summary",):
    value = response.get(key)
    if isinstance(value, str) and value.strip():
      normalized[key] = trim_text(value, SPECIALIST_SUMMARY_MAX_CHARS)
  for key in ("recommendations", "requirements", "risks"):
    limit = 3 if key == "risks" else 5
    values = limited_string_list(response.get(key), limit=limit, max_chars=SPECIALIST_ITEM_MAX_CHARS)
    if values:
      normalized[key] = values
  return normalized


def trim_text(value: Any, max_chars: int) -> str:
  text = str(value or "").strip()
  if len(text) <= max_chars:
    return text
  return f"{text[: max_chars - 15].rstrip()}... [truncated]"


def limited_string_list(value: Any, *, limit: int, max_chars: int) -> list[str]:
  return [trim_text(item, max_chars) for item in string_list(value)[:limit]]


def allowed_dynamic_tool_schemas(allowed_tools: list[str]) -> list[dict[str, Any]]:
  allowed = set(allowed_tools).intersection(ALLOWED_DYNAMIC_TOOLS)
  schemas: list[dict[str, Any]] = []
  for source in website_tool_schemas():
    if text_value(source.get("name")) not in allowed:
      continue
    schema = json.loads(json.dumps(source))
    parameters = object_value(schema.get("parameters"))
    properties = object_value(parameters.get("properties"))
    properties.pop("project_id", None)
    parameters["properties"] = properties
    parameters["required"] = [item for item in list_value(parameters.get("required")) if item != "project_id"]
    schema["parameters"] = parameters
    schemas.append(schema)
  return schemas


def build_guarded_dynamic_tool_executor(
  agent: AgentDefinition,
  *,
  execute_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
  safety_violations: list[str],
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
  call_count = 0
  allowed = set(agent.allowed_tools).intersection(ALLOWED_DYNAMIC_TOOLS)

  def guarded(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    nonlocal call_count
    call_count += 1
    if call_count > agent.tool_call_budget:
      reason = f"Dynamic agent {agent.id} exceeded tool-call budget of {agent.tool_call_budget}."
      safety_violations.append(reason)
      log_dynamic_agent_event(
        "tool.rejected",
        status="rejected",
        payload={"agent_id": agent.id, "tool_name": name, "reason": reason},
      )
      raise RuntimeError(reason)
    if name not in allowed:
      reason = f"Dynamic agent {agent.id} requested forbidden or unknown tool {name}."
      safety_violations.append(reason)
      log_dynamic_agent_event(
        "tool.rejected",
        status="rejected",
        payload={"agent_id": agent.id, "tool_name": name, "reason": reason},
      )
      raise RuntimeError(reason)
    log_dynamic_agent_event(
      "tool.accepted",
      status="running",
      payload={"agent_id": agent.id, "tool_name": name, "arguments": arguments},
    )
    return execute_tool(name, arguments if isinstance(arguments, dict) else {})

  return guarded


def validate_candidate_changes(
  value: Any,
  *,
  agent: AgentDefinition,
  task_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
  accepted: list[dict[str, Any]] = []
  rejected: list[dict[str, Any]] = []
  seen_paths: set[str] = set()
  max_files = int(agent.candidate_change_limits.get("max_files") or dynamic_agent_max_patch_files())
  max_bytes = int(agent.candidate_change_limits.get("max_bytes_per_file") or dynamic_agent_max_patch_bytes())
  for index, raw_change in enumerate(list_value(value), start=1):
    rejection = {"agent_id": agent.id, "task_id": task_id, "index": index}
    if not isinstance(raw_change, dict):
      rejected.append({**rejection, "reason": "Candidate change must be an object."})
      continue
    if len(accepted) >= max_files:
      rejected.append({**rejection, "path": text_value(raw_change.get("path")), "reason": f"Candidate file limit of {max_files} exceeded."})
      continue
    operation = text_value(raw_change.get("operation") or raw_change.get("action")).lower()
    if operation in {"delete", "remove"} or raw_change.get("delete") is True:
      rejected.append({**rejection, "path": text_value(raw_change.get("path")), "reason": "Dynamic agents cannot delete files."})
      continue
    try:
      path = normalize_artifact_path(text_value(raw_change.get("path")))
    except ArtifactValidationError as exc:
      rejected.append({**rejection, "path": text_value(raw_change.get("path")), "reason": str(exc)})
      continue
    if path in seen_paths:
      rejected.append({**rejection, "path": path, "reason": "Duplicate candidate path from the same dynamic agent."})
      continue
    content = raw_change.get("content")
    if not isinstance(content, str):
      content = raw_change.get("code")
    if not isinstance(content, str):
      rejected.append({**rejection, "path": path, "reason": "Candidate change content must be a string."})
      continue
    byte_count = len(content.encode("utf-8"))
    if byte_count > max_bytes:
      rejected.append({**rejection, "path": path, "reason": f"Candidate file exceeds {max_bytes} bytes.", "byte_count": byte_count})
      continue
    normalized_content = normalize_generated_file_code(path, content)
    normalized_byte_count = len(normalized_content.encode("utf-8"))
    if normalized_byte_count > max_bytes:
      rejected.append(
        {
          **rejection,
          "path": path,
          "reason": f"Normalized candidate file exceeds {max_bytes} bytes.",
          "byte_count": normalized_byte_count,
        }
      )
      continue
    seen_paths.add(path)
    accepted.append(
      {
        "path": path,
        "content": normalized_content,
        "agent_id": agent.id,
        "task_id": task_id,
        "byte_count": normalized_byte_count,
        "sha256": sha256_text(normalized_content),
        "validation_status": "accepted",
      }
    )
  for item in accepted:
    log_dynamic_agent_event(
      "candidate_change.accepted",
      payload={key: value for key, value in item.items() if key != "content"},
    )
  for item in rejected:
    log_dynamic_agent_event("candidate_change.rejected", status="rejected", payload=item)
  return accepted, rejected


def candidate_change_summary(
  accepted: list[dict[str, Any]],
  rejected: list[dict[str, Any]],
) -> dict[str, Any]:
  return {
    "accepted_count": len(accepted),
    "rejected_count": len(rejected),
    "accepted": [
      {
        "path": item.get("path"),
        "agent_id": item.get("agent_id"),
        "task_id": item.get("task_id"),
        "byte_count": item.get("byte_count"),
        "sha256": item.get("sha256"),
        "validation_status": item.get("validation_status"),
      }
      for item in accepted
    ],
    "rejected": rejected,
  }


def compact_dynamic_tool_calls(value: Any) -> list[dict[str, Any]]:
  return [
    {
      "call_id": item.get("call_id"),
      "name": item.get("name"),
      "status": item.get("status"),
      "error": item.get("error"),
    }
    for item in list_value(value)
    if isinstance(item, dict)
  ]


def record_agent_execution_metrics(
  agent: AgentDefinition,
  *,
  duration_ms: float,
  accepted_changes: int,
  rejected_changes: int,
) -> None:
  execution_count = int(agent.metrics.get("execution_count") or 0) + 1
  previous_average = float(agent.metrics.get("avg_execution_ms") or 0)
  agent.metrics["execution_count"] = execution_count
  agent.metrics["avg_execution_ms"] = round(
    ((previous_average * (execution_count - 1)) + duration_ms) / execution_count,
    2,
  )
  agent.metrics["accepted_candidate_changes"] = int(agent.metrics.get("accepted_candidate_changes") or 0) + accepted_changes
  agent.metrics["rejected_candidate_changes"] = int(agent.metrics.get("rejected_candidate_changes") or 0) + rejected_changes


def run_with_timeout(function: Callable[[], Any], *, timeout_seconds: int, label: str) -> Any:
  result_queue: Queue[tuple[str, Any]] = Queue(maxsize=1)
  telemetry = current_telemetry_context()

  def target() -> None:
    try:
      result_queue.put(("ok", run_with_telemetry_context(telemetry, function)))
    except Exception as exc:
      result_queue.put(("error", exc))

  worker = Thread(target=target, name=f"dynamic-agent-{label}", daemon=True)
  worker.start()
  worker.join(timeout_seconds)
  if worker.is_alive():
    raise TimeoutError(f"Dynamic agent {label} exceeded timeout budget of {timeout_seconds}s.")
  try:
    status, value = result_queue.get_nowait()
  except Empty as exc:
    raise RuntimeError(f"Dynamic agent {label} completed without returning a result.") from exc
  if status == "error":
    raise value
  return value


def parse_json_object(value: str) -> dict[str, Any]:
  text = value.strip()
  if text.startswith("```"):
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
  try:
    parsed = json.loads(text)
  except json.JSONDecodeError:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
      return {}
    try:
      parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
      return {}
  return parsed if isinstance(parsed, dict) else {}


def sha256_text(value: str) -> str:
  import hashlib

  return hashlib.sha256(value.encode("utf-8")).hexdigest()
