from backend.llm.budget_config import load_agent_budget_settings


def test_agent_budget_defaults_are_large_enough_for_scoped_updates(monkeypatch):
  monkeypatch.delenv("SCOPED_UPDATE_MAX_OUTPUT_TOKENS", raising=False)
  monkeypatch.delenv("TARGETED_UPDATE_CONTEXT_MAX_CHARS", raising=False)

  budgets = load_agent_budget_settings()

  assert budgets.scoped_update_output_tokens == 32_768
  assert budgets.targeted_update_chars == 36_000
  assert budgets.feature_update_chars == 72_000
  assert budgets.chat_context_chars == 96_000


def test_agent_budgets_accept_environment_overrides_and_enforce_ceiling(monkeypatch):
  monkeypatch.setenv("SCOPED_UPDATE_MAX_OUTPUT_TOKENS", "49152")
  monkeypatch.setenv("TARGETED_UPDATE_CONTEXT_MAX_CHARS", "90000")
  monkeypatch.setenv("ROUTING_MAX_OUTPUT_TOKENS", "999999")

  budgets = load_agent_budget_settings()

  assert budgets.scoped_update_output_tokens == 49_152
  assert budgets.targeted_update_chars == 90_000
  assert budgets.routing_output_tokens == 8_192


def test_agent_budgets_reject_non_positive_and_invalid_values(monkeypatch):
  monkeypatch.setenv("MEMORY_MAX_OUTPUT_TOKENS", "not-a-number")
  monkeypatch.setenv("PROJECT_CONTEXT_MAX_FILES", "0")

  budgets = load_agent_budget_settings()

  assert budgets.memory_output_tokens == 2_048
  assert budgets.project_context_files == 20
