from backend.llm.agentic_flow import AGENTIC_RUNTIME_NAME, execute_agentic_flow


def website_response():
  return {
    "multi_agent_system": {
      "intent": "website_generation",
      "routing_result": {
        "intent": "website_generation",
        "next_tool": "analyze_prompt",
        "reason": "The user requested a website.",
      },
      "conversation_response": {"message": "Generated the website preview from the provided prompt."},
      "shared_state": {"prompt": "Generate a CRM website"},
    },
    "orchestration_flow": {
      "generated_website": {
        "title": "AI Native CRM",
        "headline": "Close deals faster",
        "subheadline": "CRM for AI native teams.",
        "primary_cta": "Start",
        "secondary_cta": "Demo",
        "sections": [{"name": "Hero"}, {"name": "Features"}],
        "files": [{"path": "src/App.jsx"}, {"path": "package.json"}],
      }
    },
    "proactive_thinking": {"self_checks": ["Includes src/App.jsx"]},
  }


def conversation_response():
  return {
    "multi_agent_system": {
      "intent": "greeting",
      "routing_result": {
        "intent": "greeting",
        "next_tool": "handle_greeting",
        "reason": "The user only greeted.",
      },
      "conversation_response": {
        "message": "Hello. Tell me what website you want to build.",
        "next_prompt_guidance": ["Share website type", "Share brand name"],
      },
      "shared_state": {"prompt": "hi"},
    },
    "orchestration_flow": {"generated_website": {"files": []}},
    "proactive_thinking": {},
  }


def simple_code_response():
  return {
    "multi_agent_system": {
      "intent": "simple_code",
      "routing_result": {
        "intent": "simple_code",
        "next_tool": "generate_simple_code_file",
        "reason": "The user requested standalone code.",
      },
      "conversation_response": {"message": "Generated the standalone code file."},
      "shared_state": {"prompt": "write a code for armstrong number"},
    },
    "orchestration_flow": {
      "generated_website": {
        "title": "Armstrong Number",
        "headline": "Standalone Python program",
        "sections": [],
        "files": [{"path": "armstrong_number.py"}],
      }
    },
    "proactive_thinking": {"self_checks": ["Generated one Python file"]},
  }


def test_execute_agentic_flow_for_website_generation_has_real_agent_steps():
  flow = execute_agentic_flow(website_response())

  assert flow["runtime"] == AGENTIC_RUNTIME_NAME
  assert flow["branch"] == "website_generation"
  assert [step["agent"] for step in flow["steps"]] == [
    "Orchestrator",
    "Context Agent",
    "Context Agent",
    "Quality Gate Service",
    "Quality Gate Service",
    "Website Builder Agent",
    "Quality Gate Service",
    "Quality Gate Service",
    "Quality Gate Service",
    "Website Builder Agent",
    "Context Agent",
  ]
  assert flow["steps"][1]["internal_agent"] == "Prompt Analyst Agent"
  assert flow["steps"][5]["internal_agent"] == "Code Agent"
  assert flow["steps"][5]["tool_calls"] == []
  assert flow["steps"][6]["tool_calls"] == ["VALIDATE_PROJECT_ARTIFACT"]
  assert flow["steps"][7]["tool_calls"] == ["BUILD_STAGED_PROJECT_PREVIEW"]
  assert flow["steps"][8]["tool_calls"] == ["RUN_PREVIEW_VISUAL_QA"]
  assert flow["steps"][9]["tool_calls"] == ["WRITE_PROJECT_FILES"]
  assert flow["steps"][10]["tool_calls"] == ["PERSIST_PROJECT_MEMORY"]
  assert len(flow["handoffs"]) == len(flow["steps"]) - 1
  first_handoff = flow["handoffs"][0]
  assert first_handoff["sender"] == "Orchestrator"
  assert first_handoff["receiver"] == "Context Agent"
  assert first_handoff["from_internal_agent"] == "Intent Router Agent"
  assert first_handoff["to_internal_agent"] == "Prompt Analyst Agent"
  assert first_handoff["from_agent"] == first_handoff["sender"]
  assert first_handoff["to_agent"] == first_handoff["receiver"]
  assert first_handoff["next_action"] == "extract_website_brief"
  assert first_handoff["task"] == "Run extract_website_brief after route_user_turn."
  assert isinstance(first_handoff["input"], dict)
  assert isinstance(first_handoff["output"], dict)
  assert 0 <= first_handoff["confidence"] <= 1
  assert flow["final_output"]["file_count"] == 2


def test_execute_agentic_flow_for_simple_code_uses_short_non_website_flow():
  flow = execute_agentic_flow(simple_code_response())

  assert flow["runtime"] == AGENTIC_RUNTIME_NAME
  assert flow["branch"] == "simple_code"
  assert [step["internal_agent"] for step in flow["steps"]] == [
    "Intent Router Agent",
    "Simple Code Writer Agent",
    "Validation Agent",
    "Commit Agent",
    "Memory Agent",
  ]
  assert [step["action"] for step in flow["steps"]] == [
    "route_user_turn",
    "generate_simple_code_file",
    "validate_standalone_code_artifact",
    "write_standalone_code_file",
    "persist_project_memory",
  ]
  all_tool_calls = [
    tool
    for step in flow["steps"]
    for tool in step["tool_calls"]
  ]
  assert "BUILD_STAGED_PROJECT_PREVIEW" not in all_tool_calls
  assert "RUN_PREVIEW_VISUAL_QA" not in all_tool_calls
  assert all_tool_calls == [
    "generate_simple_code_file",
    "VALIDATE_STANDALONE_CODE_ARTIFACT",
    "WRITE_PROJECT_FILES",
    "PERSIST_PROJECT_MEMORY",
  ]
  assert flow["final_output"]["file_count"] == 1


def test_execute_agentic_flow_for_conversation_never_generates_files():
  flow = execute_agentic_flow(conversation_response())

  assert flow["branch"] == "conversation"
  assert [step["agent"] for step in flow["steps"]] == [
    "Orchestrator",
    "Orchestrator",
    "Context Agent",
  ]
  assert flow["steps"][1]["internal_agent"] == "Intent Router Agent"
  assert flow["steps"][1]["action"] == "handle_greeting_without_file_generation"
  assert flow["steps"][1]["output"]["generated_files"] == 0
  assert flow["final_output"]["file_count"] == 0
