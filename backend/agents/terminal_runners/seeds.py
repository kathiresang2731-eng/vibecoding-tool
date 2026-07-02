from __future__ import annotations

from typing import Any

from ..agent_runtime.state import initial_runtime_state
from ..agent_runtime.supervision import apply_direct_generation_workflow
from ..agent_runtime.values import object_value
from .catalog import actions_for_agent_name
from .mock_provider import TerminalMockProvider, build_terminal_mock_artifact


def empty_read_result() -> dict[str, Any]:
  return {"files": [], "file_count": 0, "file_index": [], "status": "ok"}


def empty_memory_result() -> dict[str, Any]:
  return {"memories": [], "status": "ok"}


def mock_brief(prompt: str) -> dict[str, Any]:
  provider = TerminalMockProvider()
  return provider._prompt_analyst_payload(prompt)


def mock_plan(prompt: str) -> dict[str, Any]:
  provider = TerminalMockProvider()
  return provider._planner_payload(prompt)


def mock_update_analysis(prompt: str) -> dict[str, Any]:
  return {
    "summary": f"Update project for: {prompt}",
    "update_mode": "content_patch",
    "request_kind": "content",
    "execution_strategy": "scoped_patch",
    "scope": "small",
    "reason": "Terminal seeded update analysis.",
    "candidate_files": ["src/App.jsx"],
    "candidate_new_files": [],
    "scoped_update_tasks": [
      {
        "id": "task_1",
        "summary": prompt,
        "candidate_files": ["src/App.jsx"],
        "candidate_new_files": [],
      }
    ],
  }


def mock_generated_website(prompt: str) -> dict[str, Any]:
  artifact = build_terminal_mock_artifact(prompt)
  return object_value(artifact.get("generated_website"))


def seed_state_for_agent(
  *,
  agent_name: str,
  prompt: str,
  project_id: str = "terminal-test-project",
  operation: str = "generate",
  seed_mode: str = "default",
) -> dict[str, Any]:
  routing_result = {
    "intent": "website_update" if operation == "update" else "website_generation",
    "confidence": 0.99,
  }
  state = initial_runtime_state(project_id=project_id, prompt=prompt, routing_result=routing_result)
  state["operation"] = operation
  state["read_result"] = empty_read_result()
  state["memory_result"] = empty_memory_result()

  if agent_name in {
    "Planner Agent",
    "Agent Registry Agent",
    "UX Review Agent",
    "Accessibility Agent",
    "Code Agent",
    "Code Generator Agent",
    "Materialize Agent",
    "Repair Agent",
    "Validation Agent",
    "Preview Agent",
    "Visual QA Agent",
    "Commit Agent",
    "Scoped Update Agent",
  }:
    state["brief"] = mock_brief(prompt)

  if agent_name in {
    "Planner Agent",
    "Agent Registry Agent",
    "UX Review Agent",
    "Accessibility Agent",
    "Code Agent",
    "Code Generator Agent",
    "Materialize Agent",
    "Repair Agent",
    "Validation Agent",
    "Preview Agent",
    "Visual QA Agent",
    "Commit Agent",
  }:
    state["plan"] = mock_plan(prompt)

  if agent_name == "Agent Registry Agent" and seed_mode == "dynamic_specialists":
    from ..dynamic_agents import create_dynamic_workflow

    registry_workflow = create_dynamic_workflow(
      prompt,
      routing_result=routing_result,
      brief=object_value(state.get("brief")),
      provider=TerminalMockProvider(),
    )
    state["dynamic_workflow_plan"] = registry_workflow
    state["dynamic_specialists_completed"] = False

  if agent_name == "Update Analysis Agent":
    state["update_analysis"] = mock_update_analysis(prompt)

  if agent_name == "Scoped Update Agent":
    state["update_analysis"] = mock_update_analysis(prompt)

  if agent_name in {
    "Code Agent",
    "Materialize Agent",
    "Repair Agent",
    "Validation Agent",
    "Preview Agent",
    "Visual QA Agent",
    "Commit Agent",
    "Code Generator Agent",
  }:
    generated = mock_generated_website(prompt)
    state["generated_website"] = generated
    state["artifact_response"] = {"generated_website": generated}
    state["candidate_files"] = list(generated.get("files") or [])

  if agent_name in {"UX Review Agent", "Accessibility Agent"}:
    state["ux_review"] = None
    state["accessibility_review"] = None

  if agent_name == "Code Generator Agent":
    state["dynamic_specialists_completed"] = True
    state["candidate_changes"] = []
    state["dynamic_patch_integrated"] = False

  if agent_name in {"Validation Agent", "Preview Agent", "Visual QA Agent", "Commit Agent"}:
    state["files_materialized"] = agent_name != "Materialize Agent"
    state["materialized_file_paths"] = ["src/App.jsx"]
    state["ux_review"] = {"status": "reviewed", "issues": [], "recommendations": []}
    state["accessibility_review"] = {"status": "reviewed", "issues": [], "recommendations": []}
    state["dynamic_specialists_completed"] = True
    state["dynamic_patch_integrated"] = True

  if agent_name == "Commit Agent":
    state["validation_result"] = {"status": "passed", "issues": []}
    state["preview_result"] = {"status": "passed"}
    state["visual_qa_result"] = {"status": "passed"}

  if operation == "generate" and seed_mode != "dynamic_planner" and seed_mode != "dynamic_specialists":
    if agent_name != "Agent Registry Agent" and "RUN_DYNAMIC_AGENT_PLANNER" not in actions_for_agent_name(agent_name):
      apply_direct_generation_workflow(state)
  elif operation == "generate" and seed_mode == "dynamic_planner":
    # Leave dynamic workflow empty so RUN_DYNAMIC_AGENT_PLANNER can create spawned agents.
    state.pop("dynamic_workflow_plan", None)
    state["dynamic_specialists_completed"] = False

  return state
