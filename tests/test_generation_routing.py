from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from backend.agents.orchestration.state import GenerationPipelineState


def test_runner_unified_fast_path_is_update_only() -> None:
  runner_path = Path(__file__).resolve().parents[1] / "backend/agents/orchestration/runner.py"
  source = runner_path.read_text()
  assert "state.intent == \"website_update\"" in source
  assert "unified_website_updates_active()" in source
  assert "run_website_generation(" in source


def test_runner_routes_generation_through_greenfield_engine() -> None:
  runner_path = Path(__file__).resolve().parents[1] / "backend/agents/orchestration/runner.py"
  source = runner_path.read_text()
  generation_idx = source.index("run_website_generation(")
  parallel_idx = source.index("if use_parallel_stream_for_website:")
  assert generation_idx < parallel_idx


def test_generation_pipeline_state_carries_confirmation_brief() -> None:
  state = GenerationPipelineState(
    user_prompt="Build a CRM",
    intent="website_generation",
    confirmation_brief={"summary": "CRM app", "planned_changes": ["Generate pages"]},
  )
  assert state.confirmation_brief is not None
  assert state.confirmation_brief["summary"] == "CRM app"
