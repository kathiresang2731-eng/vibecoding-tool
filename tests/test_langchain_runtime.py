import pytest

from backend.llm.langchain_runtime import (
  LANGCHAIN_STAGE_ORDER,
  LANGCHAIN_RUNTIME_NAME,
  LangChainRuntimeError,
  build_langchain_messages,
  build_langchain_runtime_summary,
  build_langgraph_node_projection,
  build_thread_config,
  execute_langchain_runtime,
  format_memory_context,
  langchain_package_status,
)


def test_build_thread_config_matches_langgraph_thread_persistence_shape():
  assert build_thread_config("project-run-1") == {"configurable": {"thread_id": "project-run-1"}}


def test_build_thread_config_requires_thread_id():
  with pytest.raises(LangChainRuntimeError, match="thread_id"):
    build_thread_config(" ")


def test_build_langchain_messages_includes_relevant_memory_before_user_prompt():
  messages = build_langchain_messages(
    system_prompt="You are Worktual AI Dev.",
    user_prompt="Generate a CRM website.",
    memory_items=[
      {
        "namespace": "project",
        "kind": "summary",
        "key": "latest_generation_summary",
        "content": "Last run generated AI Native CRM.",
      }
    ],
  )

  assert messages[0] == {"role": "system", "content": "You are Worktual AI Dev."}
  assert messages[1]["role"] == "system"
  assert "Relevant persisted memory" in messages[1]["content"]
  assert "AI Native CRM" in messages[1]["content"]
  assert messages[2] == {"role": "user", "content": "Generate a CRM website."}


def test_format_memory_context_ignores_empty_items():
  assert format_memory_context([{}, {"content": "  "}]) == ""
  assert format_memory_context([{"namespace": "project", "key": "a", "kind": "fact", "content": "Use black and purple."}]) == (
    "[project/fact/a] Use black and purple."
  )


def test_langchain_stage_order_is_explicit_and_stable():
  assert LANGCHAIN_STAGE_ORDER == [
    "router",
    "supervisor",
    "memory",
    "planner",
    "ux_review",
    "accessibility",
    "tool_executor",
    "validator",
    "preview",
    "visual_qa",
    "repair",
    "memory_writer",
  ]


def test_build_langgraph_node_projection_maps_agents_to_expected_nodes():
  nodes = build_langgraph_node_projection(
    agentic_flow={
      "steps": [
        {
          "agent": "Intent Router Agent",
          "action": "route_user_turn",
          "status": "completed",
          "output": {"intent": "website_generation"},
        },
        {
          "agent": "UX Review Agent",
          "action": "review_ux_plan",
          "status": "completed",
          "output": {"status": "reviewed"},
        },
        {
          "agent": "Accessibility Agent",
          "action": "review_accessibility_plan",
          "status": "completed",
          "output": {"status": "reviewed"},
        },
        {
          "agent": "Code Agent",
          "action": "package_generated_project_files",
          "status": "completed",
          "input": {"section_count": 3},
          "output": {"file_count": 4},
          "tool_calls": ["WRITE_PROJECT_FILES"],
        },
        {
          "agent": "Visual QA Agent",
          "action": "run_preview_visual_qa",
          "status": "completed",
          "output": {"status": "passed"},
          "tool_calls": ["RUN_PREVIEW_VISUAL_QA"],
        },
        {
          "agent": "Memory Agent",
          "action": "persist_project_memory",
          "status": "completed",
          "output": {"memory_kind": "summary"},
          "tool_calls": ["PERSIST_PROJECT_MEMORY"],
        },
      ]
    },
    a2a_runtime={
      "messages": [
        {
          "message_id": "a2a-1",
          "from_agent": "Intent Router Agent",
          "to_agent": "UX Review Agent",
        },
        {
          "message_id": "a2a-2",
          "from_agent": "Code Agent",
          "to_agent": "Visual QA Agent",
        },
        {
          "message_id": "a2a-3",
          "from_agent": "Visual QA Agent",
          "to_agent": "Memory Agent",
        },
      ]
    },
  )

  assert [node["node"] for node in nodes] == ["router", "ux_review", "accessibility", "tool_executor", "visual_qa", "memory_writer"]
  assert nodes[3]["tool_calls"] == ["WRITE_PROJECT_FILES"]
  assert nodes[1]["a2a_received_message_id"] == "a2a-1"
  assert nodes[4]["a2a_received_message_id"] == "a2a-2"
  assert nodes[4]["a2a_sent_message_id"] == "a2a-3"


def test_execute_langchain_runtime_builds_valid_dry_run_payload():
  runtime = execute_langchain_runtime(
    user_prompt="Generate a CRM website",
    routing_result={"intent": "website_generation"},
    agentic_flow={
      "branch": "website_generation",
      "final_output": {"file_count": 2},
      "steps": [
        {
          "agent": "Intent Router Agent",
          "action": "route_user_turn",
          "status": "completed",
          "output": {"intent": "website_generation"},
        },
        {
          "agent": "Planner Agent",
          "action": "plan_sections_and_conversion_path",
          "status": "completed",
          "output": {"section_order": ["Hero"]},
        },
        {
          "agent": "Memory Agent",
          "action": "prepare_generation_memory",
          "status": "completed",
          "output": {"memory_kind": "summary"},
        },
      ],
    },
    a2a_runtime={"protocol": "worktual-a2a-v1", "messages": []},
    google_adk_runtime={"execution_mode": "dry_run"},
  )
  summary = build_langchain_runtime_summary(runtime)

  assert runtime["runtime"] == LANGCHAIN_RUNTIME_NAME
  assert runtime["validation"]["status"] == "valid"
  assert runtime["thread_config"]["configurable"]["thread_id"].startswith("langgraph-website_generation-")
  assert runtime["messages"][0]["role"] == "system"
  assert runtime["graph"]["entrypoint"] == "router"
  assert runtime["graph"]["terminal"] == "memory_writer"
  assert summary["runtime"] == LANGCHAIN_RUNTIME_NAME
  assert summary["validation_status"] == "valid"
  assert summary["source_of_truth"] is False
  assert summary["source_of_truth_runtime"] == "worktual-real-agent-runtime-loop"
  assert runtime["projection_source"] == "real_agent_runtime_steps"


def test_langchain_package_status_is_explicit_for_both_packages():
  status = langchain_package_status()

  assert set(status) == {"langchain", "langgraph"}
  assert isinstance(status["langchain"]["installed"], bool)
  assert isinstance(status["langgraph"]["installed"], bool)
