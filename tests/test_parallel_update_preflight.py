from __future__ import annotations

from backend.agents.streaming.parallel_file_workers import _build_worker_prompt
from backend.agents.streaming.shared_work_memory import SharedWorkMemory
from backend.agents.streaming.task_planner import plan_file_work
from backend.agents.streaming.update_preflight import (
  build_heuristic_update_analysis,
  format_update_analysis_worker_block,
  merge_preflight_analyses,
  run_parallel_update_preflight,
  tasks_from_update_analysis,
)


def _files(*paths: str) -> list[dict[str, str]]:
  return [{"path": path, "content": f"export default function X(){{ /* {path} */ }}"} for path in paths]


def test_heuristic_update_preflight_finds_mentioned_paths() -> None:
  files = _files("src/components/Navbar.jsx", "src/components/Footer.jsx", "src/pages/Home.jsx")
  analysis = build_heuristic_update_analysis(
    "Update Navbar.jsx spacing and Footer.jsx copyright",
    files,
  )
  assert analysis["update_mode"] == "feature_patch"
  assert "src/components/Navbar.jsx" in analysis["candidate_files"]
  assert "src/components/Footer.jsx" in analysis["candidate_files"]
  assert len(analysis["scoped_update_tasks"]) >= 2


def test_heuristic_update_preflight_targets_auth_onboarding_flow_repair() -> None:
  files = _files(
    "src/App.jsx",
    "src/pages/Auth.jsx",
    "src/pages/Onboarding.jsx",
    "src/pages/Dashboard.jsx",
    "src/pages/Leads.jsx",
  )
  analysis = build_heuristic_update_analysis(
    "update the code to perfect flow because right we directly sowing the dashbaord",
    files,
  )

  assert analysis["preflight_source"] == "heuristic_auth_onboarding_flow"
  assert analysis["request_kind"] == "flow_patch"
  assert analysis["candidate_files"] == [
    "src/App.jsx",
    "src/pages/Auth.jsx",
    "src/pages/Onboarding.jsx",
    "src/pages/Dashboard.jsx",
  ]
  assert analysis["scoped_update_tasks"][0]["group_paths"] is True


def test_tasks_from_update_analysis_keeps_flow_repair_files_grouped() -> None:
  analysis = build_heuristic_update_analysis(
    "fix the proper flow because it is directly showing dashboard",
    _files("src/App.jsx", "src/pages/Auth.jsx", "src/pages/Onboarding.jsx", "src/pages/Dashboard.jsx"),
  )
  tasks = tasks_from_update_analysis(analysis)

  assert len(tasks) == 1
  assert tasks[0]["kind"] == "file_group"
  assert tasks[0]["paths"] == analysis["candidate_files"]


def test_tasks_from_update_analysis_maps_scoped_tasks() -> None:
  analysis = {
    "summary": "Navbar and footer refresh",
    "candidate_files": ["src/components/Navbar.jsx", "src/components/Footer.jsx"],
    "scoped_update_tasks": [
      {"summary": "Navbar spacing", "candidate_files": ["src/components/Navbar.jsx"]},
      {"summary": "Footer copy", "candidate_files": ["src/components/Footer.jsx"]},
    ],
  }
  tasks = tasks_from_update_analysis(analysis)
  assert len(tasks) == 2
  paths = {task["paths"][0] for task in tasks}
  assert paths == {"src/components/Navbar.jsx", "src/components/Footer.jsx"}


def test_plan_file_work_prefers_update_analysis_tasks() -> None:
  files = _files("src/components/Navbar.jsx", "src/components/Footer.jsx", "src/pages/Home.jsx")
  analysis = build_heuristic_update_analysis(
    "Update Navbar.jsx spacing and Footer.jsx copyright",
    files,
  )
  plan = plan_file_work(
    "Update Navbar.jsx spacing and Footer.jsx copyright",
    intent="website_update",
    project_files=files,
    update_analysis=analysis,
  )
  assert plan["planning_source"] == "update_preflight_tasks"
  assert plan["use_parallel_workers"] is True
  assert plan["task_count"] >= 2
  assert plan.get("update_analysis") == analysis


def test_plan_file_work_groups_auth_onboarding_flow_repair_without_preflight(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_LEGACY_PARALLEL_UPDATES", "true")
  files = _files("src/App.jsx", "src/pages/Auth.jsx", "src/pages/Onboarding.jsx", "src/pages/Dashboard.jsx")
  plan = plan_file_work(
    "update the code to perfect flow because right we directly sowing the dashbaord",
    intent="website_update",
    project_files=files,
  )

  assert plan["planning_source"] == "deterministic_file_planner"
  assert plan["task_count"] == 1
  assert plan["tasks"][0]["kind"] == "file_group"
  assert plan["tasks"][0]["paths"] == [
    "src/App.jsx",
    "src/pages/Auth.jsx",
    "src/pages/Onboarding.jsx",
    "src/pages/Dashboard.jsx",
  ]
  assert plan["scoped_targets"] == plan["tasks"][0]["paths"]


def test_run_parallel_update_preflight_defaults_to_heuristic(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "false")
  monkeypatch.setenv("ENABLE_PARALLEL_UPDATE_LLM_ANALYSIS", "false")
  monkeypatch.setenv("WORKTUAL_ENV", "")
  files = _files("src/components/Navbar.jsx")
  payload = run_parallel_update_preflight(prompt="fix navbar spacing", project_files=files)
  assert payload["preflight_source"] == "heuristic_code_search"
  assert payload["update_analysis"]["candidate_files"] == ["src/components/Navbar.jsx"]
  assert payload["llm_analysis_used"] is False


def test_merge_preflight_analyses_keeps_llm_candidates_and_heuristic_fallback() -> None:
  heuristic = build_heuristic_update_analysis(
    "Update Navbar.jsx spacing and Footer.jsx copyright",
    _files("src/components/Navbar.jsx", "src/components/Footer.jsx"),
  )
  llm = {
    "update_mode": "feature_patch",
    "summary": "Refresh navbar spacing only",
    "candidate_files": ["src/components/Navbar.jsx"],
    "scoped_update_tasks": [],
  }
  merged = merge_preflight_analyses(heuristic, llm, preflight_source="llm_update_analysis_agent")
  assert "src/components/Footer.jsx" in merged["candidate_files"]
  assert merged["scoped_update_tasks"]


class _SlowControlProvider:
  model = "gemini-test"

  def generate_json(self, *_args, **_kwargs):
    import time

    time.sleep(2)
    return {"update_mode": "targeted_patch", "candidate_files": ["src/components/Navbar.jsx"], "scoped_update_tasks": []}


class _FastControlProvider:
  model = "gemini-test"

  def generate_json(self, *_args, **_kwargs):
    return {
      "update_mode": "feature_patch",
      "summary": "Navbar spacing and footer copy",
      "candidate_files": ["src/components/Navbar.jsx", "src/components/Footer.jsx"],
      "scoped_update_tasks": [
        {"summary": "Navbar", "candidate_files": ["src/components/Navbar.jsx"]},
        {"summary": "Footer", "candidate_files": ["src/components/Footer.jsx"]},
      ],
    }


def test_llm_preflight_timeout_falls_back_to_heuristic(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "false")
  monkeypatch.setenv("ENABLE_PARALLEL_UPDATE_LLM_ANALYSIS", "true")
  monkeypatch.setattr(
    "backend.agents.streaming.update_preflight.parallel_update_llm_timeout_seconds",
    lambda: 1,
  )
  payload = run_parallel_update_preflight(
    prompt="Update Navbar.jsx spacing and Footer.jsx copyright",
    project_files=_files("src/components/Navbar.jsx", "src/components/Footer.jsx"),
    control_provider=_SlowControlProvider(),
  )
  assert payload["llm_analysis_used"] is False
  assert payload["preflight_source"] == "heuristic_llm_timeout_fallback"
  assert len(payload["update_analysis"]["candidate_files"]) >= 2


def test_llm_preflight_uses_memory_and_merges_tasks(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "false")
  monkeypatch.setenv("ENABLE_PARALLEL_UPDATE_LLM_ANALYSIS", "true")
  monkeypatch.setenv("PARALLEL_UPDATE_LLM_TIMEOUT_SECONDS", "10")

  class _MemoryStoreStub:
    def get_memory_chat_session_state(self, user, *, chat_session_id):
      return {"update_count": 2, "rolling_summary": "Prior navbar update completed."}

    def list_memory_episodes(self, user, *, project_id, chat_session_id, scope, limit):
      return [
        {
          "id": "ep-1",
          "searchable_summary": "Navbar spacing tightened previously",
          "outcome": "completed",
          "metadata_json": {"intent": "website_update", "changed_paths": ["src/components/Navbar.jsx"]},
        }
      ]

  payload = run_parallel_update_preflight(
    prompt="Update Navbar.jsx spacing and Footer.jsx copyright",
    project_files=_files("src/components/Navbar.jsx", "src/components/Footer.jsx"),
    control_provider=_FastControlProvider(),
    store=_MemoryStoreStub(),
    user=type("U", (), {"id": "user-1"})(),
    project_id="project-1",
    chat_session_id="session-1",
  )
  assert payload["llm_analysis_used"] is True
  assert payload["memory_items_loaded"] >= 1
  assert payload["preflight_source"] == "llm_update_analysis_agent"
  assert len(payload["update_analysis"]["scoped_update_tasks"]) >= 2


def test_staging_env_auto_enables_llm_preflight(monkeypatch) -> None:
  monkeypatch.delenv("ENABLE_PARALLEL_UPDATE_LLM_ANALYSIS", raising=False)
  monkeypatch.setenv("WORKTUAL_ENV", "staging")
  from backend.agents.runtime_config import parallel_update_llm_analysis_enabled

  assert parallel_update_llm_analysis_enabled() is True


def test_worker_prompt_includes_update_analysis_block() -> None:
  memory = SharedWorkMemory(project_id="p1", files={})
  analysis = {
    "update_mode": "targeted_patch",
    "summary": "Tighten navbar spacing",
    "candidate_files": ["src/components/Navbar.jsx"],
  }
  task = {"id": "file-src-components-navbar-jsx", "kind": "file", "paths": ["src/components/Navbar.jsx"], "scope": "update analysis"}
  prompt = _build_worker_prompt(
    user_prompt="fix navbar spacing",
    task=task,
    shared_memory=memory,
    update_analysis_block=format_update_analysis_worker_block(analysis, task=task),
  )
  assert "Update analysis (scoped parallel execution)" in prompt
  assert "Tighten navbar spacing" in prompt
