from backend.agents.agent_runtime.parallel_actions import run_parallel_tasks


def test_run_parallel_tasks_executes_all_workers():
  results = run_parallel_tasks(
    {
      "alpha": lambda: 1,
      "beta": lambda: 2,
    },
    max_workers=2,
    engine="test",
  )

  assert results["alpha"] == 1
  assert results["beta"] == 2
  assert results["parallel_execution_engine"] == "test"


def test_available_runtime_actions_prefers_parallel_bootstrap(monkeypatch):
  from backend.agents.agent_runtime.supervision import available_runtime_actions

  monkeypatch.setenv("ENABLE_RUNTIME_PARALLEL_ACTIONS", "true")
  options = available_runtime_actions({}, max_repair_attempts=1)
  assert options[0]["name"] == "RUN_PARALLEL_PROJECT_BOOTSTRAP"


def test_available_runtime_actions_prefers_parallel_reviews(monkeypatch):
  from backend.agents.agent_runtime.supervision import available_runtime_actions

  monkeypatch.setenv("ENABLE_RUNTIME_PARALLEL_ACTIONS", "true")
  state = {
    "read_result": {"file_count": 0},
    "memory_result": {"memory_count": 0},
    "brief": {"operation": "generate"},
    "dynamic_workflow_plan": {"tasks": []},
    "plan": {"sections": ["Hero"]},
    "dynamic_specialists_completed": True,
    "operation": "generate",
  }
  options = available_runtime_actions(state, max_repair_attempts=1)
  assert options[0]["name"] == "RUN_PARALLEL_REVIEW_AGENTS"
