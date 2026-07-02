import pytest

from backend.llm.orchestration_graph import (
  ORCHESTRATION_NODE_MAP,
  build_edges,
  create_orchestration_trace,
  execute_orchestration_stage_graph,
)


def test_create_orchestration_trace_sets_generation_branch():
  trace = create_orchestration_trace("website_generation")

  assert trace["runtime"] == "worktual-python-orchestration-graph"
  assert trace["entrypoint"] == "route_user_intent"
  assert trace["branch"] == "website_generation"
  assert trace["nodes"] == []
  assert trace["edges"] == build_edges()


def test_create_orchestration_trace_sets_conversation_branch():
  trace = create_orchestration_trace("greeting")

  assert trace["branch"] == "conversation"


def test_execute_orchestration_stage_graph_runs_all_nodes_in_order():
  executed_stages = []
  progress_events = []

  trace = execute_orchestration_stage_graph(
    intent="website_generation",
    routing_result={"intent": "website_generation", "next_tool": "analyze_prompt"},
    execute_stage=lambda stage_name: executed_stages.append(stage_name),
    emit_progress=lambda step, message, **kwargs: progress_events.append({"step": step, "message": message, **kwargs}),
  )

  assert executed_stages == [node["stage"] for node in ORCHESTRATION_NODE_MAP[1:]]
  assert [node["status"] for node in trace["nodes"]] == ["completed"] * len(ORCHESTRATION_NODE_MAP)
  assert trace["nodes"][0]["node"] == "route_user_intent"
  assert trace["nodes"][0]["output"]["next_tool"] == "analyze_prompt"
  assert trace["nodes"][-1]["node"] == "prepare_execution_summary"
  assert progress_events[-1]["step"] == "graph.prepare_execution_summary.completed"
  assert progress_events[-1]["status"] == "completed"


def test_execute_orchestration_stage_graph_records_failure_before_reraising():
  progress_events = []

  def fail_on_tool_contract(stage_name):
    if stage_name == "gemini_tool_calling_setup":
      raise RuntimeError("tool setup failed")

  with pytest.raises(RuntimeError, match="tool setup failed"):
    execute_orchestration_stage_graph(
      intent="website_generation",
      routing_result={"intent": "website_generation"},
      execute_stage=fail_on_tool_contract,
      emit_progress=lambda step, message, **kwargs: progress_events.append({"step": step, **kwargs}),
    )

  assert progress_events[-1]["step"] == "graph.prepare_tool_contract.failed"
  assert progress_events[-1]["status"] == "failed"
