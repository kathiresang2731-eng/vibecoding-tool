from backend.llm.google_adk_runtime import (
  ADK_AGENT_ORDER,
  ADK_APP_NAME,
  ADK_RUNTIME_NAME,
  build_adk_agent_plan,
  build_adk_runtime_summary,
  build_adk_tool_specs,
  execute_google_adk_runtime,
  google_adk_package_status,
  supervisor_instruction,
)


def test_build_adk_agent_plan_defines_real_runtime_agent_sequence():
  plan = build_adk_agent_plan("gemini-3.1-pro-preview")
  agent_names = [agent["name"] for agent in plan["agents"]]

  assert plan["app_name"] == ADK_APP_NAME
  assert plan["model"] == "gemini-3.1-pro-preview"
  assert plan["root_agent"] == "orchestrator"
  assert agent_names == ADK_AGENT_ORDER
  assert agent_names == [
    "orchestrator",
    "read_only_assistant_agent",
    "simple_code_writer_agent",
    "document_artifact_agent",
    "context_agent",
    "website_builder_agent",
    "quality_gate_service",
    "save_memory_service",
  ]
  assert "prompt_analyst_agent" not in agent_names
  assert "prompt_analyst_agent" in plan["agents"][4]["internal_agents"]
  assert "LOAD_PROJECT_MEMORY" in plan["agents"][4]["tools"]
  assert "PERSIST_PROJECT_MEMORY" in plan["agents"][4]["tools"]
  assert "code_agent" in plan["agents"][5]["internal_agents"]
  assert "WRITE_PROJECT_FILES" in plan["agents"][5]["tools"]
  assert "VALIDATE_PROJECT_ARTIFACT" in plan["agents"][6]["tools"]
  assert "BUILD_STAGED_PROJECT_PREVIEW" in plan["agents"][6]["tools"]
  assert "BUILD_PROJECT_PREVIEW" in plan["agents"][6]["tools"]
  assert "RUN_PREVIEW_VISUAL_QA" in plan["agents"][6]["tools"]


def test_supervisor_instruction_keeps_preview_and_filesystem_rules_explicit():
  instruction = supervisor_instruction()

  assert "backend tools" in instruction
  assert "unsafe filesystem paths" in instruction
  assert "Gemini" in instruction
  assert "Python" in instruction


def test_build_adk_tool_specs_include_backend_and_memory_tools():
  tool_names = {tool["name"] for tool in build_adk_tool_specs()}

  assert "route_generation_action" in tool_names
  assert "load_memory" in tool_names
  assert "LOAD_PROJECT_MEMORY" in tool_names
  assert "PERSIST_PROJECT_MEMORY" in tool_names
  assert "READ_PROJECT_FILES" in tool_names
  assert "WRITE_PROJECT_FILES" in tool_names
  assert "VALIDATE_PROJECT_ARTIFACT" in tool_names
  assert "BUILD_STAGED_PROJECT_PREVIEW" in tool_names
  assert "BUILD_PROJECT_PREVIEW" in tool_names
  assert "RUN_PREVIEW_VISUAL_QA" in tool_names


def test_execute_google_adk_runtime_projects_agentic_and_a2a_flow():
  agentic_flow = {
    "runtime": "worktual-python-agentic-flow",
    "branch": "website_generation",
    "steps": [
      {
        "agent": "Intent Router Agent",
        "action": "route_user_turn",
        "status": "completed",
        "output": {"intent": "website_generation"},
      },
      {
        "agent": "Prompt Analyst Agent",
        "action": "extract_website_brief",
        "status": "completed",
        "input": {"routing_result": {"intent": "website_generation"}},
        "output": {"title": "CRM"},
      },
      {
        "agent": "Memory Agent",
        "action": "prepare_generation_memory",
        "status": "completed",
        "input": {"title": "CRM"},
        "output": {"memory_kind": "generation_summary"},
      },
    ],
  }
  a2a_runtime = {
    "protocol": "worktual-a2a-v1",
    "messages": [
      {
        "message_id": "a2a-1",
        "from_agent": "Intent Router Agent",
        "to_agent": "Prompt Analyst Agent",
      },
      {
        "message_id": "a2a-2",
        "from_agent": "Prompt Analyst Agent",
        "to_agent": "Memory Agent",
      },
    ],
  }

  runtime = execute_google_adk_runtime(
    user_prompt="Generate a CRM website",
    model="gemini-3.1-pro-preview",
    routing_result={"intent": "website_generation"},
    agentic_flow=agentic_flow,
    a2a_runtime=a2a_runtime,
  )
  summary = build_adk_runtime_summary(runtime)

  assert runtime["runtime"] == ADK_RUNTIME_NAME
  assert runtime["validation"]["status"] == "valid"
  assert runtime["session"]["state"]["a2a_message_count"] == 2
  assert [event["author"] for event in runtime["events"]] == [
    "intent_router_agent",
    "prompt_analyst_agent",
    "memory_agent",
  ]
  assert runtime["events"][1]["a2a_received_message_id"] == "a2a-1"
  assert summary["runtime"] == ADK_RUNTIME_NAME
  assert summary["event_count"] == 3
  assert summary["validation_status"] == "valid"
  assert summary["source_of_truth"] is False
  assert summary["source_of_truth_runtime"] == "worktual-real-agent-runtime-loop"
  assert runtime["projection_source"] == "real_agent_runtime_steps"


def test_google_adk_package_status_is_explicit_boolean():
  status = google_adk_package_status()

  assert status["module"] == "google.adk"
  assert isinstance(status["installed"], bool)
