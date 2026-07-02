from __future__ import annotations

import json
from typing import Any

from ..graph_runtime.hierarchical_teams import team_for_action, team_label
from .catalog import agent_catalog_entry


def _banner(title: str) -> None:
  line = "=" * 72
  print(f"\n{line}\n{title}\n{line}")


def print_agent_header(agent_name: str, *, prompt: str, provider_mode: str) -> None:
  entry = agent_catalog_entry(agent_name)
  _banner(f"AGENT: {agent_name}")
  print(f"Prompt      : {prompt}")
  print(f"Provider    : {provider_mode}")
  print(f"Phase       : {entry.get('phase_title') or 'n/a'}")
  print(f"Team        : {entry.get('team_label') or 'n/a'}")
  print(f"Actions     : {', '.join(entry.get('actions') or [])}")


def print_action_result(action: str, state: dict[str, Any]) -> None:
  _banner(f"ACTION COMPLETE: {action}")
  keys = _output_keys_for_action(action)
  printed = False
  for key in keys:
    value = state.get(key)
    if value is None:
      continue
    printed = True
    print(f"\n[{key}]")
    print(_format_value(value))
  if not printed:
    steps = state.get("agent_steps") or []
    if steps:
      print("\n[last agent step]")
      print(_format_value(steps[-1]))
  _print_parallel_details(state)


def _output_keys_for_action(action: str) -> tuple[str, ...]:
  mapping = {
    "READ_PROJECT_FILES": ("read_result",),
    "LOAD_PROJECT_MEMORY": ("memory_result",),
    "RUN_PARALLEL_PROJECT_BOOTSTRAP": ("read_result", "memory_result"),
    "RUN_PROMPT_ANALYST": ("brief",),
    "RUN_PLANNER": ("plan",),
    "RUN_UPDATE_ANALYST": ("update_analysis",),
    "RUN_ERROR_HANDLING_AGENT": ("error_diagnosis",),
    "RUN_DYNAMIC_AGENT_PLANNER": ("dynamic_workflow_plan", "spawned_dynamic_agents"),
    "RUN_DYNAMIC_SPECIALISTS": ("dynamic_specialist_results", "dynamic_agent_executions"),
    "RUN_DYNAMIC_PATCH_INTEGRATOR": ("candidate_change_summary",),
    "RUN_CODE_AGENT": ("generated_website", "artifact_response"),
    "RUN_UX_REVIEW_AGENT": ("ux_review",),
    "RUN_ACCESSIBILITY_AGENT": ("accessibility_review",),
    "RUN_PARALLEL_REVIEW_AGENTS": ("ux_review", "accessibility_review"),
    "VALIDATE_PROJECT_ARTIFACT": ("validation_result",),
    "BUILD_STAGED_PROJECT_PREVIEW": ("preview_result",),
    "RUN_PREVIEW_VISUAL_QA": ("visual_qa_result",),
    "WRITE_PROJECT_FILES": ("write_result",),
    "PERSIST_PROJECT_MEMORY": ("memory",),
  }
  return mapping.get(action, ("agent_steps",))


def _print_parallel_details(state: dict[str, Any]) -> None:
  blocks: list[tuple[str, Any]] = []
  specialist_results = state.get("dynamic_specialist_results")
  if isinstance(specialist_results, dict):
    engine = specialist_results.get("parallel_execution_engine")
    if engine:
      blocks.append(("dynamic_specialists_parallel_engine", engine))
    groups = specialist_results.get("parallel_groups_executed")
    if groups:
      blocks.append(("dynamic_parallel_groups", groups))
    executions = specialist_results.get("dynamic_agent_executions")
    if executions:
      blocks.append(("dynamic_agent_executions", executions))
  for step in reversed(state.get("agent_steps") or []):
    if not isinstance(step, dict):
      continue
    output = step.get("output")
    if isinstance(output, dict) and output.get("parallel_execution_engine"):
      blocks.append(("parallel_execution_engine", output.get("parallel_execution_engine")))
      blocks.append(("parallel_step_output", output))
      break
  if not blocks:
    return
  print("\n[parallel execution]")
  for label, value in blocks:
    print(f"  {label}:")
    print(_indent(_format_value(value), 4))


def print_next_steps(state: dict[str, Any], available_actions: list[dict[str, Any]]) -> None:
  _banner("NEXT NODE / AGENT ACTIONS")
  if not available_actions:
    print("No further legal actions. Flow may be complete or blocked.")
    return
  for index, option in enumerate(available_actions, start=1):
    action = str(option.get("name") or option.get("action") or "")
    agent = str(option.get("agent") or "Agent")
    team = team_for_action(action)
    team_name = team_label(team) if team else "n/a"
    print(f"{index}. {agent}")
    print(f"   action : {action}")
    print(f"   team   : {team_name}")
    print(f"   node   : {team or 'chief_supervisor'}")
    if option.get("description"):
      print(f"   note   : {option['description']}")
  chief_action = available_actions[0]
  action_name = str(chief_action.get("name") or "")
  print("\nSuggested next terminal command:")
  agent = str(chief_action.get("agent") or "")
  from .catalog import AGENT_SCRIPT_NAMES

  script = AGENT_SCRIPT_NAMES.get(agent, "run_flow")
  print(f"  python backend/agents/terminal_runners/{script}.py")


def print_flow_summary(state: dict[str, Any]) -> None:
  _banner("RUN SUMMARY")
  print(f"project_id : {state.get('project_id')}")
  print(f"operation  : {state.get('operation')}")
  print(f"completed  : {bool(state.get('completed'))}")
  history = list(state.get("action_history") or [])
  print(f"actions run: {' → '.join(history) if history else '(none)'}")
  if state.get("spawned_dynamic_agents"):
    spawned = state.get("spawned_dynamic_agents") or []
    print(f"spawned    : {len(spawned)} dynamic agent(s)")
    for item in spawned:
      if isinstance(item, dict):
        print(f"  - {item.get('name')} ({item.get('agent_id')})")


def _format_value(value: Any, *, max_chars: int = 6000) -> str:
  try:
    text = json.dumps(value, indent=2, ensure_ascii=False)
  except TypeError:
    text = json.dumps(str(value), indent=2, ensure_ascii=False)
  if len(text) > max_chars:
    return text[:max_chars] + "\n... [truncated]"
  return text


def _indent(text: str, spaces: int) -> str:
  prefix = " " * spaces
  return "\n".join(prefix + line for line in text.splitlines())
