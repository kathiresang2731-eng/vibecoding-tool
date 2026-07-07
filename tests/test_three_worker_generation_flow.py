from __future__ import annotations

import pytest

from backend.agents.generation_engine import greenfield_runner
from backend.agents.generation_engine.project_docs import completed_plan_files, initial_plan_files
from backend.agents.streaming.parallel_file_workers import _assign_worker_step_budgets, _worker_max_steps_for_task
from backend.agents.streaming.task_planner import plan_greenfield_parallel_tasks
from backend.api.generation_parts.status import extract_preview_status_from_generation
from backend.agents.streaming.build_gate import run_post_update_build_gate
from backend.storage import UserContext


def test_greenfield_plan_has_exactly_three_concurrent_disjoint_workers() -> None:
  plan = plan_greenfield_parallel_tasks(
    "Build a CRM with auth onboarding dashboard leads contacts deals sales projects products and AI chat"
  )

  assert plan["task_count"] == 3
  assert plan["worker_count"] == 3
  assert plan["waves"] == [[
    "greenfield-integration",
    "greenfield-pages-primary",
    "greenfield-features-secondary",
  ]]
  owned: set[str] = set()
  for task in plan["tasks"]:
    task_paths = set(task["paths"])
    assert task_paths
    assert owned.isdisjoint(task_paths)
    owned |= task_paths
  assert "src/App.jsx" in owned
  assert "src/pages/Auth.jsx" in owned
  assert "src/pages/Onboarding.jsx" in owned
  assert "src/pages/Dashboard.jsx" in owned
  assert "src/pages/Deals.jsx" in owned


def test_route_contract_makes_auth_entry_and_connects_every_page() -> None:
  plan = plan_greenfield_parallel_tasks("Build auth then onboarding then dashboard and settings")
  routes = {
    item["file_path"]: item["route"]
    for item in plan["coordination_contract"]["route_contract"]
  }

  assert routes["src/pages/Auth.jsx"] == "/"
  assert routes["src/pages/Onboarding.jsx"] == "/onboarding"
  assert routes["src/pages/Dashboard.jsx"] == "/dashboard"
  assert routes["src/pages/Settings.jsx"] == "/settings"


def test_group_worker_budget_covers_each_assigned_file() -> None:
  plan = plan_greenfield_parallel_tasks("Build a CRM with auth onboarding dashboard and analytics")
  for task in plan["tasks"]:
    assert _worker_max_steps_for_task(task) >= len(task["paths"]) + 3


def test_full_stack_three_worker_budget_covers_all_owned_paths() -> None:
  plan = plan_greenfield_parallel_tasks(
    "Build a full stack CRM with auth onboarding dashboard leads contacts deals sales projects products "
    "AI chat and a FastAPI PostgreSQL backend"
  )
  budgets = _assign_worker_step_budgets(plan["tasks"], intent="website_generation")
  for task in plan["tasks"]:
    assert budgets[task["id"]] >= len(task["paths"]) + 2


def test_generation_writes_plan_and_final_description_documents() -> None:
  plan = plan_greenfield_parallel_tasks("Build auth onboarding dashboard")
  initial = initial_plan_files(prompt="Build auth onboarding dashboard", work_plan=plan)
  assert [item["path"] for item in initial] == ["todo.md"]
  assert "exactly three coding workers concurrently" in initial[0]["content"]

  runtime = {
    "final_output": {
      "preview_status": "ready",
      "preview_url": "/api/previews/project/version/",
      "visual_qa_status": "passed",
    },
    "repair_iterations": 1,
  }
  validation = {"complete": True, "page_count": 4, "issues": []}
  completed = completed_plan_files(
    prompt="Build auth onboarding dashboard",
    work_plan=plan,
    validation=validation,
    runtime=runtime,
  )
  by_path = {item["path"]: item["content"] for item in completed}
  assert set(by_path) == {"todo.md", "WEBSITE.md"}
  assert "- [x] Publish the preview" in by_path["todo.md"]
  assert "/api/previews/project/version/" in by_path["WEBSITE.md"]


def test_generation_does_not_inject_scaffold_before_plan_documents_are_accepted(monkeypatch) -> None:
  scaffold_calls: list[bool] = []

  def fail_plan_documents(**_kwargs):
    raise RuntimeError("plan document rejected")

  def record_scaffold_injection(**_kwargs):
    scaffold_calls.append(True)
    return []

  monkeypatch.setattr(greenfield_runner, "_persist_plan_documents", fail_plan_documents)
  monkeypatch.setattr(greenfield_runner, "_inject_vite_scaffold_if_needed", record_scaffold_injection)

  with pytest.raises(RuntimeError, match="plan document rejected"):
    greenfield_runner.run_website_generation(
      project_id="project-1",
      user=UserContext(id="user-1", email="user@example.com", role="admin"),
      tool_context=object(),
      prompt="Build a farming website",
      artifact_provider=None,
      emit_progress=lambda *_args, **_kwargs: None,
    )

  assert scaffold_calls == []


def test_preview_status_reads_normalized_final_output_contract() -> None:
  generation = {
    "multi_agent_system": {
      "agentic_runtime": {
        "final_output": {
          "preview_status": "ready",
          "preview_url": "/api/previews/project/version/",
          "preview": {
            "status": "ready",
            "preview_url": "/api/previews/project/version/",
          },
        }
      }
    }
  }
  assert extract_preview_status_from_generation(generation) == "ready"


def test_generation_build_gate_allows_only_one_repair_and_exposes_preview(monkeypatch) -> None:
  files = [{"path": "src/App.jsx", "content": "export default function App(){ return <main /> }"}]
  builds = [
    {
      "version": {
        "id": "v1",
        "status": "failed",
        "preview_url": None,
        "build_log": "src/App.jsx:1:1: ERROR broken",
      }
    },
    {
      "version": {
        "id": "v2",
        "status": "ready",
        "preview_url": "/api/previews/project/v2/",
        "build_log": "built",
      }
    },
  ]
  events: list[dict] = []

  monkeypatch.setattr("backend.agents.streaming.build_gate.post_update_build_gate_enabled", lambda: True)
  monkeypatch.setattr("backend.agents.streaming.build_gate._list_tool_files", lambda *_args: files)
  monkeypatch.setattr("backend.agents.streaming.build_gate._project_title", lambda *_args: "Demo")
  monkeypatch.setattr(
    "backend.agents.streaming.build_gate.normalize_files_before_build",
    lambda current, **_kwargs: (current, []),
  )
  monkeypatch.setattr(
    "backend.agents.streaming.build_gate._run_staged_build",
    lambda *_args: builds.pop(0),
  )
  monkeypatch.setattr(
    "backend.agents.streaming.build_gate.apply_deterministic_build_repair",
    lambda current, *_args, **_kwargs: (current, ["src/App.jsx"], "module_contracts"),
  )
  monkeypatch.setattr("backend.agents.streaming.build_gate._persist_files", lambda *_args, **_kwargs: None)

  result = run_post_update_build_gate(
    project_id="project",
    user=UserContext(id="user", email="u@example.com", role="owner"),
    tool_context=object(),
    prompt="Build a website",
    intent="website_generation",
    artifact_provider=object(),
    emit_progress=lambda step, message, **kwargs: events.append(
      {"step": step, "message": message, **kwargs}
    ),
    changed_paths=["src/App.jsx"],
    max_repair_attempts=1,
    max_build_attempts=2,
  )

  assert result["status"] == "ready"
  assert result["build_attempts"] == 2
  assert result["repair_iterations"] == 1
  assert result["preview_url"] == "/api/previews/project/v2/"
  assert len([event for event in events if event["step"] == "terminal.command.started"]) == 2
