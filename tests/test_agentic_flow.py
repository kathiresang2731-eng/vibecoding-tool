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


def test_execute_agentic_flow_for_website_generation_has_real_agent_steps():
  flow = execute_agentic_flow(website_response())

  assert flow["runtime"] == AGENTIC_RUNTIME_NAME
  assert flow["branch"] == "website_generation"
  assert [step["agent"] for step in flow["steps"]] == [
    "Intent Router Agent",
    "Prompt Analyst Agent",
    "Planner Agent",
    "UX Review Agent",
    "Accessibility Agent",
    "Code Agent",
    "Validation Agent",
    "Preview Agent",
    "Visual QA Agent",
    "Code Agent",
    "Memory Agent",
  ]
  assert flow["steps"][5]["tool_calls"] == []
  assert flow["steps"][6]["tool_calls"] == ["VALIDATE_PROJECT_ARTIFACT"]
  assert flow["steps"][7]["tool_calls"] == ["BUILD_STAGED_PROJECT_PREVIEW"]
  assert flow["steps"][8]["tool_calls"] == ["RUN_PREVIEW_VISUAL_QA"]
  assert flow["steps"][9]["tool_calls"] == ["WRITE_PROJECT_FILES"]
  assert flow["steps"][10]["tool_calls"] == ["PERSIST_PROJECT_MEMORY"]
  assert len(flow["handoffs"]) == len(flow["steps"]) - 1
  first_handoff = flow["handoffs"][0]
  assert first_handoff["sender"] == "Intent Router Agent"
  assert first_handoff["receiver"] == "Prompt Analyst Agent"
  assert first_handoff["from_agent"] == first_handoff["sender"]
  assert first_handoff["to_agent"] == first_handoff["receiver"]
  assert first_handoff["next_action"] == "extract_website_brief"
  assert first_handoff["task"] == "Run extract_website_brief after route_user_turn."
  assert isinstance(first_handoff["input"], dict)
  assert isinstance(first_handoff["output"], dict)
  assert 0 <= first_handoff["confidence"] <= 1
  assert flow["final_output"]["file_count"] == 2


def test_execute_agentic_flow_for_conversation_never_generates_files():
  flow = execute_agentic_flow(conversation_response())

  assert flow["branch"] == "conversation"
  assert [step["agent"] for step in flow["steps"]] == [
    "Intent Router Agent",
    "Conversation Agent",
    "Memory Agent",
  ]
  assert flow["steps"][1]["output"]["generated_files"] == 0
  assert flow["final_output"]["file_count"] == 0
