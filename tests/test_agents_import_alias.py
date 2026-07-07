from __future__ import annotations

import importlib
import sys


def test_agents_import_alias_resolves_backend_package() -> None:
  import backend.agents

  backend.agents.install_agents_import_alias()

  module = importlib.import_module("agents.runtime_config")
  assert module.__name__ == "backend.agents.runtime_config"


def test_agents_nested_import_alias_for_generation_hot_path() -> None:
  import backend.agents

  backend.agents.install_agents_import_alias()

  from agents.streaming.task_planner import plan_greenfield_parallel_tasks
  from agents.agent_runtime.update_analysis import build_update_code_search_matches
  from agents.generation_engine.greenfield_runner import run_website_generation

  assert callable(plan_greenfield_parallel_tasks)
  assert callable(build_update_code_search_matches)
  assert callable(run_website_generation)


def test_agents_alias_is_idempotent() -> None:
  import backend.agents

  finder_count = sum(
    1 for finder in sys.meta_path if finder.__class__.__name__ == "_AgentsAliasFinder"
  )
  backend.agents.install_agents_import_alias()
  backend.agents.install_agents_import_alias()
  assert (
    sum(1 for finder in sys.meta_path if finder.__class__.__name__ == "_AgentsAliasFinder")
    == finder_count
  )
