from __future__ import annotations

from backend.agents.agent_runtime.actions.dispatcher import ACTION_HANDLERS
from backend.agents.agent_runtime.supervision import ACTION_REGISTRY as SUPERVISOR_ACTION_REGISTRY
from backend.agents.runtime_agents.registry import ACTION_REGISTRY, RUNTIME_AGENT_GROUPS, actions_for_agent
from backend.agents.mas.graph import RUNTIME_AGENT_CONTRACTS
from backend.agents.tools import execute_website_tool, run_browser_preview_qa, website_tool_schemas


def test_runtime_agent_registry_is_supervisor_source_of_truth():
  assert SUPERVISOR_ACTION_REGISTRY is ACTION_REGISTRY


def test_runtime_agent_registry_covers_all_executable_actions():
  executable_actions = set(ACTION_HANDLERS)
  registered_actions = set(ACTION_REGISTRY) - {"DONE"}

  assert executable_actions == registered_actions


def test_runtime_agent_groups_cover_action_registry():
  grouped_actions = {
    action
    for actions in RUNTIME_AGENT_GROUPS.values()
    for action in actions
  }

  assert grouped_actions == set(ACTION_REGISTRY)
  assert actions_for_agent("Memory Agent")[0]["action"] == "READ_PROJECT_FILES"


def test_agents_tools_facade_exports_runtime_tool_contracts():
  assert callable(execute_website_tool)
  assert callable(run_browser_preview_qa)
  assert isinstance(website_tool_schemas(), list)


def test_mas_contracts_derive_actions_and_tools_from_runtime_registry():
  contracts = {contract.name: contract for contract in RUNTIME_AGENT_CONTRACTS}

  assert set(contracts) == set(RUNTIME_AGENT_GROUPS) - {"Supervisor Agent"}
  for agent_name, contract in contracts.items():
    actions = RUNTIME_AGENT_GROUPS[agent_name]
    expected_tools = []
    for action in actions:
      for tool in ACTION_REGISTRY[action]["tools"]:
        if tool not in expected_tools:
          expected_tools.append(tool)
    assert contract.allowed_actions == actions
    assert list(contract.allowed_tools) == expected_tools

  assert ACTION_REGISTRY["WRITE_PROJECT_FILES"]["agent"] == "Commit Agent"
