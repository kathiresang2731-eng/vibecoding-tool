"""Unified website update hot path must not load legacy routing modules."""

from __future__ import annotations

import sys
from unittest.mock import patch

from backend.agents.runtime_config import (
  parallel_stream_orchestrator_enabled,
  unified_website_updates_active,
)
from backend.agents.streaming.file_agent import select_system_instruction, streaming_file_agent_step_limit


def test_unified_website_updates_active_by_default() -> None:
  assert unified_website_updates_active()
  assert not parallel_stream_orchestrator_enabled()


def test_unified_select_instruction_skips_legacy_module() -> None:
  legacy_mod = "backend.agents.streaming.legacy_update_routing"
  original = sys.modules.get(legacy_mod)
  try:
    if legacy_mod in sys.modules:
      del sys.modules[legacy_mod]
    with patch.dict(sys.modules, {legacy_mod: None}):
      instruction = select_system_instruction(
        intent="website_update",
        prompt="cart button in header not working",
      )
    assert "SCOPED UPDATE" in instruction or "str_replace" in instruction
  finally:
    if original is not None:
      sys.modules[legacy_mod] = original
    elif legacy_mod in sys.modules and sys.modules[legacy_mod] is None:
      del sys.modules[legacy_mod]


def test_unified_step_limit_without_auth_ui_heuristics() -> None:
  with patch(
    "backend.agents.streaming.file_agent.is_auth_flow_update_prompt",
    side_effect=AssertionError("legacy auth heuristic must not run on unified path"),
  ), patch(
    "backend.agents.streaming.file_agent.is_ui_interaction_repair_prompt",
    side_effect=AssertionError("legacy ui heuristic must not run on unified path"),
  ):
    steps = streaming_file_agent_step_limit(
      intent="website_update",
      prompt="cart button in header not working",
      request_kind="interaction_wiring_update",
    )
  assert steps >= 10


def test_runner_lazy_imports_parallel_orchestrator() -> None:
  from pathlib import Path

  runner_path = Path(__file__).resolve().parents[1] / "backend/agents/orchestration/runner.py"
  source = runner_path.read_text()
  header, _body = source.split("class ", 1)
  assert "parallel_orchestrator" not in header
  assert "from ..streaming.parallel_orchestrator import run_parallel_stream_orchestrator" in source
