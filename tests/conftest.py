from __future__ import annotations

import pytest

from backend.audit_logging import StructuredAuditLogger, set_audit_logger_for_tests
from backend.gemini_token_usage_logger import (
  GeminiTokenUsageLogger,
  set_gemini_token_usage_logger_for_tests,
)


@pytest.fixture(autouse=True)
def isolate_global_audit_logger(tmp_path):
  set_audit_logger_for_tests(StructuredAuditLogger(root_dir=tmp_path / "audit_logs"))
  set_gemini_token_usage_logger_for_tests(GeminiTokenUsageLogger(root_dir=tmp_path / "gemini_token_usage"))
  try:
    yield
  finally:
    set_audit_logger_for_tests(None)
    set_gemini_token_usage_logger_for_tests(None)


@pytest.fixture(autouse=True)
def stable_agentic_test_env(monkeypatch):
  """Keep tests deterministic when another test loads project .env into os.environ."""
  monkeypatch.setenv("DYNAMIC_AGENT_PROMOTION_MIN_SUCCESSES", "3")
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "48")
  monkeypatch.setenv("ENABLE_DYNAMIC_AGENT_TOOL_LOOP", "false")


@pytest.fixture
def use_direct_generation_workflow_in_tests(monkeypatch):
  """Hierarchical bootstrap with direct-generation policy (skip dynamic specialist planner)."""
  monkeypatch.setenv("ENABLE_FULL_DYNAMIC_GENERATION", "0")


@pytest.fixture(autouse=True)
def reset_dynamic_agent_registry_between_tests():
  try:
    from backend.llm.dynamic_agents import reset_global_agent_registry
  except ImportError:
    from agents.dynamic_agents import reset_global_agent_registry
  reset_global_agent_registry()
  yield
  reset_global_agent_registry()
